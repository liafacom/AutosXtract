"""Image dimensions, read from the header alone — with no dependency at all.

This exists for a packaging reason. The detailed engine contract has to turn
normalised coordinates into pixels, and for that it needs the image size.
Decoding the whole image just to read two numbers would require Pillow or
OpenCV — and on macOS the default install brings neither, because the engine
there is Apple Vision, which reads the raw bytes.

PNG and JPEG both declare their size in the header. Reading 30 bytes settles
it, and keeps the library core down to the two dependencies it already had.
"""

from __future__ import annotations

import struct

_PNG = b"\x89PNG\r\n\x1a\n"
# JPEG SOF markers that carry width and height. ``SOF4`` (0xC4), ``SOF8``
# (0xC8) and ``SOFC`` (0xCC) are deliberately excluded: they are Huffman
# tables, a JPEG extension and an arithmetic-coding definition — not frames.
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def dimensions(image: bytes) -> tuple[float, float]:
    """``(width, height)`` in pixels; ``(0.0, 0.0)`` when it cannot be read.

    Zero is the honest answer for an unknown format, and callers treat it as
    "I don't know": the layers that depend on position on the page simply do
    not classify margins, rather than classifying them wrongly.
    """
    if image.startswith(_PNG):
        return _png(image)
    if image[:2] == b"\xff\xd8":
        return _jpeg(image)
    return 0.0, 0.0


def _png(image: bytes) -> tuple[float, float]:
    # IHDR is always the first chunk: 8 bytes of signature, 4 of length and 4
    # of name, then width and height as big-endian 32-bit integers.
    if len(image) < 24 or image[12:16] != b"IHDR":
        return 0.0, 0.0
    width, height = struct.unpack(">II", image[16:24])
    return float(width), float(height)


def _jpeg(image: bytes) -> tuple[float, float]:
    i, n = 2, len(image)
    while i + 9 < n:
        if image[i] != 0xFF:
            i += 1
            continue
        marker = image[i + 1]
        # Padding (repeated 0xFF) and payload-less markers carry no length.
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        size = struct.unpack(">H", image[i + 2 : i + 4])[0]
        if marker in _SOF:
            height, width = struct.unpack(">HH", image[i + 5 : i + 9])
            return float(width), float(height)
        i += 2 + size
    return 0.0, 0.0
