"""Question images (PRD QB-06; SECURITY_AND_ACCESS.md: PNG, JPEG or WebP, at most 2 MB).

The file's content decides what it is, never its name or declared type. Every image is decoded
and saved again as WebP: that drops EXIF (camera, GPS), comments and anything hidden after the
image data, and caps the size. Stored privately as `<institution>/<id>.webp`.

Question text refers to an image as `/api/v1/images/<id>`; `sign_refs` turns those into
short-lived links when the text is sent, so stored text never holds an expiring URL.
"""

import io
import re
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import AppError
from app.core.ids import uuid7
from app.core.storage import IMAGES, Storage

MAX_BYTES = 2 * 1024 * 1024
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
MAX_SIDE = 2000  # larger images are scaled down; plenty for a question on screen
MAX_PIXELS = 40_000_000  # refuse "decompression bombs" before decoding them
QUALITY = 85

REF = re.compile(r"/api/v1/images/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


def _refuse(message: str) -> AppError:
    return AppError(
        "INVALID_IMAGE",
        message,
        status_code=422,
        details=[{"field": "file", "message": message, "type": "image"}],
    )


def reencode(data: bytes) -> tuple[bytes, int, int]:
    """Check the bytes are a PNG, JPEG or WebP image and return a clean WebP copy and its size."""
    if len(data) > MAX_BYTES:
        raise _refuse("The image is larger than 2 MB.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise _refuse("Use a PNG, JPEG or WebP image.")
            if probe.width * probe.height > MAX_PIXELS:
                raise _refuse("The image has too many pixels.")
            probe.verify()  # structural check; the file must be reopened to read pixels
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            image: Image.Image = ImageOps.exif_transpose(opened)  # upright once EXIF is dropped
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            out = io.BytesIO()
            image.save(out, "WEBP", quality=QUALITY, method=4)  # no exif=, so none is written
            return out.getvalue(), image.width, image.height
    except AppError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError):
        raise _refuse("This file isn't a PNG, JPEG or WebP image.") from None
    except (OSError, ValueError, SyntaxError):  # truncated or corrupt image data
        raise _refuse("The image is damaged and can't be read.") from None


def key_of(institution_id: uuid.UUID, image_id: uuid.UUID) -> str:
    return f"{institution_id}/{image_id}.webp"


async def store(
    storage: Storage, institution_id: uuid.UUID, data: bytes
) -> tuple[uuid.UUID, int, int, int]:
    """Re-encode and upload. Returns the image id, width, height and stored size."""
    clean, width, height = reencode(data)
    image_id = uuid7()
    await storage.put(IMAGES, key_of(institution_id, image_id), clean, "image/webp")
    return image_id, width, height, len(clean)


def sign_refs(text: str, institution_id: uuid.UUID, storage: Storage, seconds: int) -> str:
    """Replace each `/api/v1/images/<id>` with a link valid for `seconds`.

    The key includes the caller's institution, so a reference to another institution's image
    points at a key that doesn't exist: storage answers 404 and nothing leaks.
    """
    return REF.sub(
        lambda m: storage.signed_url(
            IMAGES, key_of(institution_id, uuid.UUID(m.group(1))), seconds
        ),
        text,
    )


def signed_links(
    texts: list[str], institution_id: uuid.UUID, storage: Storage, seconds: int
) -> dict[str, str]:
    """`{reference: signed link}` for every image referenced in `texts`.

    For editors: the text keeps its permanent references (saving it never stores an expiring
    link) and the page swaps them for these links only when showing it.
    """
    refs = {m.group(0): uuid.UUID(m.group(1)) for text in texts for m in REF.finditer(text)}
    return {
        ref: storage.signed_url(IMAGES, key_of(institution_id, image_id), seconds)
        for ref, image_id in refs.items()
    }
