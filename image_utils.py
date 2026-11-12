# image_utils.py
# Cleans up room photos before they're shown or sent to the AI.

import io
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

# Let Pillow open iPhone HEIC/HEIF photos
register_heif_opener()

# Longest side in pixels. Bigger photos cost more to scan without being more accurate.
MAX_SIZE = 1568

# The number EXIF uses for the "GPS info" section of a photo's hidden data
GPS_TAG = 0x8825


def prepare_image(uploaded_file):
    """
    Takes an uploaded photo and returns:
      - clean JPEG bytes (rotated correctly, resized, no hidden data)
      - True/False: did the original photo contain GPS location?
    """
    img = Image.open(uploaded_file)

    # Check for hidden location data before we remove it
    had_location = GPS_TAG in img.getexif()

    # Phones often save photos sideways plus a "rotate me" note. Apply the rotation for real.
    img = ImageOps.exif_transpose(img)

    # Convert to standard colour (handles PNGs with transparency, etc.)
    img = img.convert("RGB")

    # Shrink so the longest side is at most MAX_SIZE (never enlarges)
    img.thumbnail((MAX_SIZE, MAX_SIZE))

    # Rebuild the image from pixels only. This leaves ALL hidden data behind.
    clean = Image.frombytes("RGB", img.size, img.tobytes())

    # Save as a JPEG in memory (not to disk)
    buffer = io.BytesIO()
    clean.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue(), had_location


def has_metadata(jpeg_bytes):
    """Safety check: returns True if any hidden EXIF data survived cleaning."""
    img = Image.open(io.BytesIO(jpeg_bytes))
    return len(img.getexif()) > 0
