import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

# Admin uploads are often full-resolution, multi-MB phone-camera photos.
# A moodboard tile never needs more than this, so downsize + recompress on
# upload rather than serving the original bytes to every visitor.
MAX_DIMENSION = 2000
JPEG_QUALITY = 85


def optimize_image_file(file_obj, name):
    """Downsize + recompress an uploaded/stored image file. Returns a ContentFile."""
    img = Image.open(file_obj)
    img_format = (img.format or 'JPEG').upper()
    if img_format not in ('JPEG', 'PNG', 'WEBP'):
        img_format = 'JPEG'

    img = ImageOps.exif_transpose(img)
    if img.width > MAX_DIMENSION or img.height > MAX_DIMENSION:
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)
    if img_format == 'JPEG' and img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    save_kwargs = {'optimize': True}
    if img_format in ('JPEG', 'WEBP'):
        save_kwargs['quality'] = JPEG_QUALITY

    buffer = io.BytesIO()
    img.save(buffer, format=img_format, **save_kwargs)
    buffer.seek(0)
    return ContentFile(buffer.read(), name=name)
