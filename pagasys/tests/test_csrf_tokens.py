import re

from django.middleware import csrf
from django.test import RequestFactory


def _lowercase_token(token: str) -> bool:
    return re.fullmatch(r"[a-z0-9]{64}", token) is not None


def test_get_token_generates_lowercase_token():
    request = RequestFactory().get("/")
    token = csrf.get_token(request)
    assert _lowercase_token(token)


def test_uppercase_cookie_is_replaced():
    request = RequestFactory().get("/")
    request.META["CSRF_COOKIE"] = "A" * csrf.CSRF_SECRET_LENGTH
    token = csrf.get_token(request)
    assert _lowercase_token(token)
    assert request.META["CSRF_COOKIE"].islower()


def test_cookie_with_invalid_characters_is_replaced():
    request = RequestFactory().get("/")
    request.META["CSRF_COOKIE"] = ("$" * csrf.CSRF_SECRET_LENGTH)
    token = csrf.get_token(request)
    assert _lowercase_token(token)
    assert request.META["CSRF_COOKIE"].islower()
