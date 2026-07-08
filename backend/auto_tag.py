import asyncio
from pathlib import Path

from backend.config import logger
from backend.database import File, Tag, FileTag, Workspace, SessionLocal
from backend.exiftool_worker import exiftool_queue
from backend.websocket_manager import ws_manager


class YOLOModel:
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self):
        if self._model is not None:
            return self._model
        logger.info("Loading YOLO model (yolo11n)...")
        from ultralytics import YOLO
        self._model = YOLO("yolo11n.pt")
        logger.info("YOLO model loaded")
        return self._model

    def predict(self, image_path: str):
        model = self.load()
        results = model(image_path, device="cpu", verbose=False)
        return results[0]

    @property
    def class_names(self):
        return self.load().names


yolo_model = YOLOModel()


_STOP_WORDS = frozenset({
    "a", "an", "the", "this", "that", "with", "and", "of", "in", "on",
    "at", "to", "for", "is", "are", "was", "were", "it", "its", "there",
    "some", "has", "have", "been", "being", "be", "very", "too", "up",
    "down", "out", "off", "over", "all", "no", "not", "so", "as",
})



class BLIPModel:
    _instance = None
    _processor = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self):
        if self._model is not None:
            return self._processor, self._model
        logger.info("Loading BLIP v1 model (Salesforce/blip-image-captioning-base)...")
        from transformers import BlipProcessor, BlipForConditionalGeneration
        self._processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        self._model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
        logger.info("BLIP v1 model loaded")
        return self._processor, self._model

    def caption(self, image_path: str) -> str:
        from PIL import Image
        processor, model = self.load()
        raw = Image.open(image_path).convert("RGB")
        inputs = processor(raw, return_tensors="pt")
        out = model.generate(**inputs, max_new_tokens=30)
        return processor.decode(out[0], skip_special_tokens=True)


blip_model = BLIPModel()


def _caption_to_tags(caption: str) -> list[str]:
    import re
    caption = caption.lower().strip()
    caption = re.sub(r"[^a-z0-9\uac00-\ud7af\s]", "", caption)
    words = caption.split()
    seen = set()
    tags = []
    for w in words:
        w = w.strip()
        if not w or w in _STOP_WORDS or len(w) <= 2:
            continue
        if w not in seen:
            seen.add(w)
            tags.append(w)
    return tags


async def smart_tag_single_file(file_id: int):
    """Run YOLO (objects) + BLIP (scene) on one image, overwrite tags."""
    db = SessionLocal()
    try:
        file_record = db.query(File).filter(
            File.id == file_id, File.is_deleted == False, File.media_type == "image"
        ).first()
        if not file_record:
            return {"error": "File not found or not an image"}
        workspace = db.query(Workspace).filter(
            Workspace.id == file_record.workspace_id
        ).first()
        if not workspace:
            return {"error": "Workspace not found"}
        full_path = Path(workspace.absolute_path) / file_record.relative_path
        if not full_path.exists():
            return {"error": "File not found on disk"}

        # YOLO
        yolo_result = yolo_model.predict(str(full_path))
        detected = sorted(set(
            yolo_model.class_names[int(c)].lower() for c in yolo_result.boxes.cls.tolist()
        ))

        # BLIP
        caption = blip_model.caption(str(full_path))
        blip_tags = _caption_to_tags(caption)
        logger.info("BLIP caption for %s: %s", file_record.filename, caption)

        all_tags = list(dict.fromkeys(detected + blip_tags))

        db.query(FileTag).filter(
            FileTag.file_id == file_record.id, FileTag.source == "manual",
        ).delete()
        for tag_name in all_tags:
            tag = db.query(Tag).filter(Tag.name == tag_name).first()
            if not tag:
                tag = Tag(name=tag_name)
                db.add(tag)
                db.flush()
            db.add(FileTag(file_id=file_record.id, tag_id=tag.id, source="manual"))
        db.commit()

        current_tags = [
            ft.tag.name for ft in db.query(FileTag)
            .filter(FileTag.file_id == file_record.id).all() if ft.tag
        ]
        metadata = {
            "is_favorite": file_record.is_favorite,
            "tags": ",".join(current_tags),
        }
        await exiftool_queue.enqueue(full_path, metadata)

        db.close()
        return {
            "tags": current_tags,
            "yolo_tags": detected,
            "blip_caption": caption,
            "blip_tags": blip_tags,
        }

    except Exception as e:
        db.close()
        logger.error("Smart tag failed for file %d: %s", file_id, e)
        return {"error": str(e)}


async def auto_tag_files(file_ids: list[int]):
    db = SessionLocal()

    try:
        files_to_process = (
            db.query(File)
            .filter(
                File.id.in_(file_ids),
                File.is_deleted == False,
                File.media_type == "image",
            )
            .all()
        )
    except Exception as e:
        logger.error("DB query failed: %s", e)
        db.close()
        return

    total = len(files_to_process)
    processed = 0
    errors = 0

    await ws_manager.broadcast_immediate("auto_tag_started", {"total": total})

    if total == 0:
        await ws_manager.broadcast_immediate("auto_tag_completed", {
            "processed": 0, "errors": 0, "total": 0,
        })
        db.close()
        return

    for file_record in files_to_process:
        try:
            workspace = db.query(Workspace).filter(
                Workspace.id == file_record.workspace_id
            ).first()
            if not workspace:
                errors += 1
                continue

            full_path = Path(workspace.absolute_path) / file_record.relative_path
            if not full_path.exists():
                errors += 1
                continue

            # YOLO
            yolo_result = yolo_model.predict(str(full_path))
            yolo_tags = sorted(set(
                yolo_model.class_names[int(c)].lower()
                for c in yolo_result.boxes.cls.tolist()
            ))

            # BLIP
            caption = blip_model.caption(str(full_path))
            blip_tags = _caption_to_tags(caption)

            all_tags = list(dict.fromkeys(yolo_tags + blip_tags))

            if all_tags:
                db.query(FileTag).filter(
                    FileTag.file_id == file_record.id,
                    FileTag.source == "manual",
                ).delete()

                for tag_name in all_tags:
                    tag = db.query(Tag).filter(Tag.name == tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name)
                        db.add(tag)
                        db.flush()
                    db.add(FileTag(
                        file_id=file_record.id,
                        tag_id=tag.id,
                        source="manual",
                    ))

                db.commit()

                current_tags = [
                    ft.tag.name
                    for ft in db.query(FileTag)
                    .filter(FileTag.file_id == file_record.id)
                    .all()
                    if ft.tag
                ]
                metadata = {
                    "is_favorite": file_record.is_favorite,
                    "tags": ",".join(current_tags),
                }
                await exiftool_queue.enqueue(full_path, metadata)

            processed += 1

            await ws_manager.broadcast_immediate("auto_tag_progress", {
                "file_id": file_record.id,
                "filename": file_record.filename,
                "tags": all_tags,
                "blip_caption": caption,
                "current": processed,
                "total": total,
            })

        except Exception as e:
            logger.error("Auto-tag failed for file %d: %s", file_record.id, e)
            errors += 1
            processed += 1

    db.close()

    await ws_manager.broadcast_immediate("auto_tag_completed", {
        "processed": processed,
        "errors": errors,
        "total": total,
    })
