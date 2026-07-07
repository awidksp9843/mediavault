"""
MediaVault - Thumbnail Generator
Generates WebP thumbnails for images (Pillow) and videos (FFmpeg).
Simultaneously computes pHash from the in-memory thumbnail image.
"""
from pathlib import Path
from io import BytesIO

import imagehash
from PIL import Image

from backend.config import THUMBNAIL_DIR, THUMBNAIL_MAX_SIZE, logger


def _get_thumbnail_path(file_id: int) -> Path:
    """Get the filesystem path for a thumbnail by file ID."""
    # Shard thumbnails into subdirectories to avoid too many files in one dir
    shard = str(file_id % 256).zfill(3)
    thumb_dir = THUMBNAIL_DIR / shard
    thumb_dir.mkdir(parents=True, exist_ok=True)
    return thumb_dir / f"{file_id}.webp"


def _compute_phash(img: Image.Image) -> str | None:
    """Compute perceptual hash from PIL Image object already in memory."""
    try:
        h = imagehash.phash(img)
        return str(h)
    except Exception as e:
        logger.warning("pHash computation failed: %s", e)
        return None


def generate_image_thumbnail(file_path: Path, file_id: int) -> tuple[str, str | None] | None:
    """
    Generate a WebP thumbnail for an image file.
    Returns (relative_thumb_path, phash_string) or None on failure.
    """
    try:
        thumb_path = _get_thumbnail_path(file_id)

        with Image.open(file_path) as img:
            # Convert to RGB if necessary (handle RGBA, palette, etc.)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")

            # Compute pHash from the full image loaded in memory
            phash_value = _compute_phash(img)

            # Generate thumbnail
            img.thumbnail((THUMBNAIL_MAX_SIZE, THUMBNAIL_MAX_SIZE), Image.LANCZOS)
            img.save(thumb_path, "WEBP", quality=80)

        # Return path relative to THUMBNAIL_DIR for DB storage
        rel_path = thumb_path.relative_to(THUMBNAIL_DIR).as_posix()
        return rel_path, phash_value

    except Exception as e:
        logger.error("Image thumbnail generation failed for %s: %s", file_path, e)
        return None


def generate_video_thumbnail(file_path: Path, file_id: int) -> tuple[str, str | None] | None:
    """
    Generate a WebP thumbnail for a video file using FFmpeg.
    Extracts a frame at 1 second (or first frame if shorter).
    Returns (relative_thumb_path, phash_string) or None on failure.
    """
    try:
        import ffmpeg

        thumb_path = _get_thumbnail_path(file_id)

        # Extract frame at 1s, output raw RGB
        out, _ = (
            ffmpeg
            .input(str(file_path), ss=1)
            .filter("scale", THUMBNAIL_MAX_SIZE, -1)
            .output("pipe:", vframes=1, format="rawvideo", pix_fmt="rgb24")
            .run(capture_stdout=True, capture_stderr=True, quiet=True)
        )

        if not out:
            # Try first frame if 1s fails
            out, _ = (
                ffmpeg
                .input(str(file_path), ss=0)
                .filter("scale", THUMBNAIL_MAX_SIZE, -1)
                .output("pipe:", vframes=1, format="rawvideo", pix_fmt="rgb24")
                .run(capture_stdout=True, capture_stderr=True, quiet=True)
            )

        if not out:
            logger.warning("No video frame extracted from %s", file_path)
            return None

        # Probe to get actual dimensions after scaling
        probe = ffmpeg.probe(str(file_path))
        video_stream = next(
            (s for s in probe.get("streams", []) if s["codec_type"] == "video"),
            None,
        )
        if not video_stream:
            return None

        orig_w = int(video_stream["width"])
        orig_h = int(video_stream["height"])
        scaled_w = THUMBNAIL_MAX_SIZE
        scaled_h = int(orig_h * (THUMBNAIL_MAX_SIZE / orig_w))

        img = Image.frombytes("RGB", (scaled_w, scaled_h), out)
        phash_value = _compute_phash(img)
        img.save(thumb_path, "WEBP", quality=80)

        rel_path = thumb_path.relative_to(THUMBNAIL_DIR).as_posix()
        return rel_path, phash_value

    except Exception as e:
        logger.error("Video thumbnail generation failed for %s: %s", file_path, e)
        return None


def generate_thumbnail(file_path: Path, file_id: int, media_type: str) -> tuple[str, str | None] | None:
    """
    Generate thumbnail based on media type.
    Returns (relative_thumb_path, phash_string) or None on failure.
    """
    if media_type == "image":
        return generate_image_thumbnail(file_path, file_id)
    elif media_type == "video":
        return generate_video_thumbnail(file_path, file_id)
    return None


def get_thumbnail_absolute_path(relative_thumb_path: str) -> Path:
    """Convert relative thumbnail path back to absolute filesystem path."""
    return THUMBNAIL_DIR / relative_thumb_path
