from django.db import transaction
from django.http import Http404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PageText
from .pages import PAGES


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
