from __future__ import annotations
import os, io, hashlib
from uuid import uuid4
from typing import Iterable, Optional

from flask import current_app
from werkzeug.utils import secure_filename
from PIL import Image, UnidentifiedImageError

DEFAULT_SIZE = 50

def allowed_image(filename: str) -> bool:
    """Check extension against Config.ALLOWED_IMAGE_EXTS."""
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    exts = current_app.config.get("ALLOWED_IMAGE_EXTS", {"png", "jpg", "jpeg", "webp"})
    return ext in exts

def open_image(file_or_stream) -> Image.Image:
    """Load an image or raise ValueError."""
    try:
        img = Image.open(file_or_stream)
        img.load()
        return img
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("Invalid image") from e

def square(img: Image.Image, size: int = DEFAULT_SIZE) -> Image.Image:
    """Center-crop to square and resize with LANCZOS."""
    img = img.convert("RGBA")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def save_png(pil: Image.Image, subfolder: str, name_key: str) -> str:
    """
    Save PIL image as PNG under /static/<subfolder> with a short content hash suffix.
    Returns a web path like /static/icons/badge-1a2b3c4d.png
    """
    base = secure_filename(name_key).lower() or uuid4().hex[:8]
    # hash content so duplicates get de-duped filenames
    buf = io.BytesIO()
    pil.save(buf, format="PNG", optimize=True)
    digest = hashlib.sha1(buf.getvalue()).hexdigest()[:8]
    filename = f"{base}-{digest}.png"

    root = current_app.root_path
    save_dir = os.path.join(root, "static", subfolder)
    _ensure_dir(save_dir)
    fp = os.path.join(save_dir, filename)

    with open(fp, "wb") as f:
        f.write(buf.getvalue())

    return f"/static/{subfolder}/{filename}"

def remove_web_path(web_path: Optional[str]) -> None:
    """Delete a previously saved /static/... file; ignore errors."""
    if not web_path:
        return
    try:
        fp = os.path.join(current_app.root_path, web_path.lstrip("/"))
        if os.path.exists(fp):
            os.remove(fp)
    except OSError:
        pass

# -------- Deterministic avatar pickers --------

def _solid_placeholder() -> Image.Image:
    return Image.new("RGBA", (DEFAULT_SIZE, DEFAULT_SIZE), (220, 220, 220, 255))

def _pick_avatar_for_key(key: str, subfolder: str, choices: Iterable[str]) -> Image.Image:
    """
    Deterministically pick an avatar from /static/<subfolder>/<choice>.
    Falls back to a solid placeholder if no files exist or errors occur.
    """
    root = current_app.root_path
    files = [os.path.join(root, "static", subfolder, c) for c in choices]
    files = [fp for fp in files if os.path.exists(fp)]
    if not files:
        return _solid_placeholder()

    digest = hashlib.md5((key or "").strip().lower().encode("utf-8")).hexdigest()
    fp = files[int(digest, 16) % len(files)]
    try:
        img = Image.open(fp); img.load()
        return img
    except Exception:
        return _solid_placeholder()

# Avatars to look for; put these files in /static/icons and /static/avatars respectively.
_BADGE_AVATARS = ["dog_1.png","dog_2.png","dog_3.png","dog_4.png","dog_5.png"]
_USER_AVATARS  = ["dog_1.png","dog_2.png","dog_3.png","dog_4.png","dog_5.png"]

def badge_fallback(name: str=None) -> Image.Image:
    """Fallback icon for a badge when none supplied/valid."""
    return _pick_avatar_for_key(name, "icons", _BADGE_AVATARS)

def user_fallback(key: str) -> Image.Image:
    """Fallback avatar for a user when none supplied/valid."""
    return _pick_avatar_for_key(key, "avatars", _USER_AVATARS)
