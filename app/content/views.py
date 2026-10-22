from django.db import transaction
from django.http import Http404
from rest_framework import permissions, serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PageImage, PageText
from .pages import PAGE_IMAGES, PAGES


def _fields(page):
    if page not in PAGES:
        raise Http404
    return PAGES[page]


def _texts(page):
    saved = dict(PageText.objects.filter(page=page).values_list('key', 'value'))
    return {key: saved.get(key, default) for key, _label, default, _max, _multi in _fields(page)}


class PageTextView(APIView):
    """GET /api/content/<page>/ — every text of the page, edited or default."""
    permission_classes = (permissions.AllowAny,)

    def get(self, request, page):
        return Response(_texts(page))


class PageTextAdminView(APIView):
    """GET lists the page's fields for the edit form; PATCH takes {key: text}.
    A blank text, or the default text, goes back to the default."""
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request, page):
        texts = _texts(page)
        return Response([
            {'key': key, 'label': label, 'value': texts[key], 'default': default,
             'max_length': max_length, 'multiline': multiline}
            for key, label, default, max_length, multiline in _fields(page)
        ])

    def patch(self, request, page):
        fields = {f[0]: f for f in _fields(page)}
        if not isinstance(request.data, dict):
            return Response({'detail': 'Send an object of texts.'}, status=status.HTTP_400_BAD_REQUEST)

        errors, cleaned = {}, {}
        for key, value in request.data.items():
            if key not in fields:
                errors[key] = 'Unknown text.'
                continue
            _key, _label, default, max_length, multiline = fields[key]
            if not isinstance(value, str):
                errors[key] = 'Must be text.'
                continue
            value = value.replace('\r\n', '\n').strip()
            if not multiline:
                value = ' '.join(value.split())
            if '\x00' in value:
                errors[key] = 'Invalid characters.'
            elif len(value) > max_length:
                errors[key] = f'At most {max_length} characters.'
            else:
                cleaned[key] = '' if value == default else value
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            for key, value in cleaned.items():
                if value:
                    PageText.objects.update_or_create(page=page, key=key, defaults={'value': value})
                else:
                    PageText.objects.filter(page=page, key=key).delete()
        return self.get(request, page)


def _image_slots(page):
    if page not in PAGE_IMAGES:
        raise Http404
    return PAGE_IMAGES[page]


def _image_urls(request, page):
    """{key: absolute URL of the uploaded photo, or None for the page's own}."""
    saved = {img.key: img for img in PageImage.objects.filter(page=page)}
    return {
        key: request.build_absolute_uri(saved[key].image.url) if key in saved else None
        for key, _label in _image_slots(page)
    }


class PageImageView(APIView):
    """GET /api/content/<page>/images/ — {key: url or null (keep the built-in photo)}."""
    permission_classes = (permissions.AllowAny,)

    def get(self, request, page):
        return Response(_image_urls(request, page))


class _UploadSerializer(serializers.Serializer):
    image = serializers.ImageField()


class PageImageAdminView(APIView):
    """GET lists the page's photo slots. POST /<key>/ (multipart `image`)
    replaces a photo; DELETE /<key>/ goes back to the page's own photo."""
    permission_classes = (permissions.IsAdminUser,)
    parser_classes = (MultiPartParser, FormParser)

    def get(self, request, page, key=None):
        urls = _image_urls(request, page)
        return Response([{'key': k, 'label': label, 'url': urls[k]} for k, label in _image_slots(page)])

    def _slot(self, page, key):
        if key not in dict(_image_slots(page)):
            raise Http404

    def post(self, request, page, key=None):
        self._slot(page, key)
        upload = _UploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        with transaction.atomic():
            PageImage.objects.filter(page=page, key=key).delete()  # the signal removes the old file
            PageImage.objects.create(page=page, key=key, image=upload.validated_data['image'])
        return self.get(request, page)

    def delete(self, request, page, key=None):
        self._slot(page, key)
        with transaction.atomic():
            PageImage.objects.filter(page=page, key=key).delete()
        return self.get(request, page)
