"""
MediaVault - AI Model Wrappers
Lazy-loading wrappers for BLIP, Places365, and InsightFace models.
All models run on CPU with batch_size=1.
"""
import json
import logging
from pathlib import Path

import numpy as np
from PIL import Image

from backend.config import AI_MODEL_CACHE_DIR, logger

logger = logging.getLogger("mediavault.models")


class BLIPCaptioner:
    """BLIP image captioning via HuggingFace transformers."""

    def __init__(self):
        self._processor = None
        self._model = None
        self._loaded = False

    @property
    def is_loaded(self):
        return self._loaded

    def load(self):
        if self._loaded:
            return
        logger.info("Loading BLIP model (CPU)...")
        from transformers import BlipProcessor, BlipForConditionalGeneration

        cache_dir = str(AI_MODEL_CACHE_DIR / "blip")
        self._processor = BlipProcessor.from_pretrained(
            "Salesforce/blip-image-captioning-base",
            cache_dir=cache_dir,
        )
        self._model = BlipForConditionalGeneration.from_pretrained(
            "Salesforce/blip-image-captioning-base",
            cache_dir=cache_dir,
        )
        self._model.eval()
        self._loaded = True
        logger.info("BLIP model loaded")

    def unload(self):
        self._model = None
        self._processor = None
        self._loaded = False
        import gc
        gc.collect()
        logger.info("BLIP model unloaded")

    def predict(self, image_path: str | Path) -> list[str]:
        self.load()
        raw_image = Image.open(image_path).convert("RGB")
        inputs = self._processor(raw_image, return_tensors="pt")
        out = self._model.generate(**inputs, max_new_tokens=30)
        caption = self._processor.decode(out[0], skip_special_tokens=True)
        # Extract meaningful keywords from caption
        words = [w.strip().lower() for w in caption.split() if len(w.strip()) > 2]
        return words


class Places365Classifier:
    """Places365 scene classification via torch hub."""

    _CATEGORIES = None

    def __init__(self):
        self._model = None
        self._loaded = False
        self._transform = None

    @property
    def is_loaded(self):
        return self._loaded

    def load(self):
        if self._loaded:
            return
        logger.info("Loading Places365 model (CPU)...")
        import torch
        import torchvision.transforms as T

        cache_dir = str(AI_MODEL_CACHE_DIR / "places365")
        self._model = torch.hub.load(
            "zhoubolei/places365",
            "resnet18_places365",
            pretrained=True,
            force_reload=False,
            source="github",
        )
        self._model.eval()
        self._transform = T.Compose([
            T.Resize(256),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        # Load category labels
        cat_path = Path(__file__).parent / "places365_categories.txt"
        if not cat_path.exists():
            self._download_categories(cat_path)
        if cat_path.exists():
            with open(cat_path, encoding="utf-8") as f:
                self._CATEGORIES = [line.strip() for line in f if line.strip()]

        self._loaded = True
        logger.info("Places365 model loaded")

    def _download_categories(self, dest: Path):
        import urllib.request
        url = "https://raw.githubusercontent.com/zhoubolei/places365/master/categories_places365.txt"
        try:
            urllib.request.urlretrieve(url, str(dest))
        except Exception as e:
            logger.warning("Failed to download Places365 categories: %s", e)

    def unload(self):
        self._model = None
        self._transform = None
        self._loaded = False
        import gc
        gc.collect()
        logger.info("Places365 model unloaded")

    def predict(self, image_path: str | Path) -> list[dict]:
        self.load()
        import torch
        raw_image = Image.open(image_path).convert("RGB")
        input_tensor = self._transform(raw_image).unsqueeze(0)
        with torch.no_grad():
            logits = self._model(input_tensor)
            probs = torch.softmax(logits, dim=1)[0]
        top5 = probs.topk(5)
        results = []
        for score, idx in zip(top5.values.tolist(), top5.indices.tolist()):
            label = self._CATEGORIES[idx] if self._CATEGORIES and idx < len(self._CATEGORIES) else f"scene_{idx}"
            # Clean label: "beach/sand" -> "beach"
            label = label.split("/")[0].strip()
            results.append({"label": label, "confidence": round(score, 3)})
        return results


class InsightFaceDetector:
    """Face detection and recognition via InsightFace + ONNX Runtime (CPU)."""

    def __init__(self):
        self._app = None
        self._loaded = False

    @property
    def is_loaded(self):
        return self._loaded

    def load(self):
        if self._loaded:
            return
        logger.info("Loading InsightFace model (CPU)...")
        import insightface
        from insightface.model_zoo import get_model
        # Set model root to project-local path
        model_root = AI_MODEL_CACHE_DIR / "insightface"
        model_root.mkdir(parents=True, exist_ok=True)
        self._app = get_model("buffalo_l", root=str(model_root))
        self._app.prepare(ctx_id=-1)  # -1 = CPU
        self._loaded = True
        logger.info("InsightFace model loaded")

    def unload(self):
        self._app = None
        self._loaded = False
        import gc
        gc.collect()
        logger.info("InsightFace model unloaded")

    def predict(self, image_path: str | Path) -> list[dict]:
        self.load()
        import cv2
        img = cv2.imread(str(image_path))
        if img is None:
            logger.warning("InsightFace: cannot read image %s", image_path)
            return []
        faces = self._app.get(img)
        results = []
        for face in faces:
            bbox = face.bbox.astype(int).tolist()
            results.append({
                "bbox": {"x": bbox[0], "y": bbox[1], "w": bbox[2] - bbox[0], "h": bbox[3] - bbox[1]},
                "confidence": round(float(face.det_score), 3),
                "embedding": face.normed_embedding.tolist() if hasattr(face, "normed_embedding") else None,
            })
        return results
