"""Checking and cleaning uploaded question images (PRD QB-06; SECURITY_AND_ACCESS.md)."""

import io

import pytest
from PIL import Image

from app.core.errors import AppError
from app.images.service import MAX_BYTES, MAX_SIDE, reencode


def encode(image: Image.Image, fmt: str, **options: object) -> bytes:
    out = io.BytesIO()
    image.save(out, fmt, **options)
    return out.getvalue()


def refused(data: bytes) -> str:
    with pytest.raises(AppError) as caught:
        reencode(data)
    assert caught.value.code == "INVALID_IMAGE"
    return caught.value.message


def test_exif_and_gps_are_removed() -> None:
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # camera make
    exif[0x8825] = {2: (12.0, 58.0, 0.0)}  # GPS latitude
    photo = encode(Image.new("RGB", (64, 48), "teal"), "JPEG", exif=exif.tobytes())
    assert b"SecretCam" in photo

    clean, width, height = reencode(photo)
    assert b"SecretCam" not in clean and b"Exif" not in clean
    stored = Image.open(io.BytesIO(clean))
    assert stored.format == "WEBP" and dict(stored.getexif()) == {} and (width, height) == (64, 48)


def test_photos_stay_upright() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90°": the camera held sideways
    _, width, height = reencode(encode(Image.new("RGB", (80, 40)), "JPEG", exif=exif.tobytes()))
    assert (width, height) == (40, 80)


def test_large_images_are_scaled_down() -> None:
    _, width, height = reencode(encode(Image.new("RGB", (4000, 1000)), "PNG"))
    assert (width, height) == (MAX_SIDE, MAX_SIDE // 4)


def test_transparency_is_kept() -> None:
    clean, _, _ = reencode(encode(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), "PNG"))
    assert Image.open(io.BytesIO(clean)).mode == "RGBA"


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_allowed_formats(fmt: str) -> None:
    assert reencode(encode(Image.new("RGB", (8, 8)), fmt))[1:] == (8, 8)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"just some text with a .png name", "isn't a PNG, JPEG or WebP"),
        (b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', "isn't a PNG"),
        (b"%PDF-1.7\n", "isn't a PNG"),
        (b"", "isn't a PNG"),
    ],
    ids=["text", "svg", "pdf", "empty"],
)
def test_non_images_are_refused(data: bytes, message: str) -> None:
    assert message in refused(data)


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF"])
def test_other_image_formats_are_refused(fmt: str) -> None:
    assert "Use a PNG, JPEG or WebP" in refused(encode(Image.new("RGB", (8, 8)), fmt))


def test_too_many_bytes() -> None:
    assert "larger than 2 MB" in refused(b"\x89PNG" + b"\0" * MAX_BYTES)


def test_decompression_bomb() -> None:
    # Tiny on disk, 48 million pixels once decoded: refused from the header, before decoding.
    bomb = encode(Image.new("1", (8000, 6000)), "PNG")
    assert len(bomb) < MAX_BYTES
    assert "too many pixels" in refused(bomb)


def test_damaged_file() -> None:
    whole = encode(Image.new("RGB", (200, 200), "red"), "JPEG")
    assert "damaged" in refused(whole[: len(whole) // 2])
