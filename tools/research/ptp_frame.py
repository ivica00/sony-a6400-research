"""Pure JPEG validation for the PTP liveview probe. No camera or COM access."""
import hashlib


def _be16(data, index):
    return (data[index] << 8) | data[index + 1]


def jpeg_sof_dimensions(data):
    """Return (width, height) from the first SOF marker, or None."""
    if not data or len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        return None
    index = 2
    while index + 1 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            return None
        marker = data[index]
        index += 1
        if marker in (0xD9, 0xDA):
            return None
        if index + 2 > len(data):
            return None
        segment = _be16(data, index)
        if segment < 2 or segment > len(data) - index:
            return None
        if ((0xC0 <= marker <= 0xC3) or (0xC5 <= marker <= 0xC7) or
                (0xC9 <= marker <= 0xCB) or (0xCD <= marker <= 0xCF)):
            if segment < 7:
                return None
            height = _be16(data, index + 3)
            width = _be16(data, index + 5)
            if not width or not height:
                return None
            return width, height
        index += segment
    return None


def parse_expect(text):
    """"1024x680" -> (1024, 680); None for empty."""
    if not text:
        return None
    try:
        width, height = text.lower().split('x', 1)
        width, height = int(width), int(height)
    except (ValueError, AttributeError):
        raise ValueError('Expected WIDTHxHEIGHT')
    if width <= 0 or height <= 0:
        raise ValueError('Expected positive dimensions')
    return width, height


def evaluate_frame(data, expected=None, min_bytes=100):
    reasons = []
    if not data or len(data) < min_bytes:
        reasons.append('too_small')
    dimensions = jpeg_sof_dimensions(data) if data else None
    if dimensions is None:
        reasons.append('no_sof')
    if expected and dimensions and dimensions != tuple(expected):
        reasons.append('dimension_mismatch')
    return {
        'ok': not reasons,
        'bytes': len(data) if data else 0,
        'sha256': hashlib.sha256(data).hexdigest() if data else None,
        'dimensions': dimensions,
        'expected': list(expected) if expected else None,
        'reasons': reasons,
    }
