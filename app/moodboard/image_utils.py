import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

# Admin uploads are often full-resolution, multi-MB phone-camera photos.
# A moodboard tile never needs more than this, so downsize + recompress on
# upload rather than serving the original bytes to every visitor.
MAX_DIMENSION = 2000
JPEG_QUALITY = 85

# Grid tiles show a photo at most ~330px wide on desktop and ~375px tall on
# phones (3x pixel density), so 1000px is sharp everywhere at a quarter of the
# bytes; the full-size image only loads when a photo is opened.
THUMB_DIMENSION = 1000
THUMB_QUALITY = 80


def make_thumbnail(file_obj, name):
    """Small grid-tile version of an image. Returns a ContentFile."""
    return optimize_image_file(file_obj, name, max_dimension=THUMB_DIMENSION, quality=THUMB_QUALITY)


def optimize_image_file(file_obj, name, max_dimension=MAX_DIMENSION, quality=JPEG_QUALITY):
    """Downsize + recompress an uploaded/stored image file. Returns a ContentFile."""
    img = Image.open(file_obj)
    img_format = (img.format or 'JPEG').upper()
    if img_format not in ('JPEG', 'PNG', 'WEBP'):
        img_format = 'JPEG'

    img = ImageOps.exif_transpose(img)
    if img.width > max_dimension or img.height > max_dimension:
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    if img_format == 'JPEG' and img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    save_kwargs = {'optimize': True}
    if img_format in ('JPEG', 'WEBP'):
        save_kwargs['quality'] = quality

    buffer = io.BytesIO()
    img.save(buffer, format=img_format, **save_kwargs)
    buffer.seek(0)
    return ContentFile(buffer.read(), name=name)
