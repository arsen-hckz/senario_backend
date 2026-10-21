import math

from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


def _has_non_finite(value):
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_has_non_finite(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_non_finite(v) for v in value)
    return False


class ObjectJSONParser(JSONParser):
    """JSON bodies must be an object of finite values; anything else is a 400.

    Views read fields with request.data.get(...), so a list or string body
    was an AttributeError, and a number like 1e400 parses to infinity, which
    int() can't convert (OverflowError). Both were 500s, and every 500 emails
    staff, so anyone could flood the inbox through the public endpoints.
    """

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        if not isinstance(data, dict):
            raise ParseError('The request body must be a JSON object.')
        if _has_non_finite(data):
            raise ParseError('Numbers must be finite.')
        return data
