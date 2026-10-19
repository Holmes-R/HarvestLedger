"""M3: API foundation and configuration."""

import pytest
from django.conf import settings
from django.urls import reverse

pytestmark = pytest.mark.m3


def test_api_is_versioned_under_v1():
    assert reverse("api:health") == "/api/v1/health/"
    assert reverse("api:delivery-list") == "/api/v1/deliveries/"


def test_explicit_anonymous_access_policy():
    assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == []
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.AllowAny"
    ]


def test_json_renderer_and_decimal_strings_configured():
    assert (
        "rest_framework.renderers.JSONRenderer"
        in (settings.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"])
    )
    assert settings.REST_FRAMEWORK["COERCE_DECIMAL_TO_STRING"] is True


def test_cors_middleware_runs_before_common_and_has_no_wildcard():
    middleware = settings.MIDDLEWARE
    cors = middleware.index("corsheaders.middleware.CorsMiddleware")
    common = middleware.index("django.middleware.common.CommonMiddleware")
    assert cors < common
    assert getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False) is False
    assert settings.CORS_ALLOWED_ORIGINS  # non-empty, from env


@pytest.mark.django_db
def test_allowed_origin_is_reflected(client):
    response = client.get(reverse("api:health"), HTTP_ORIGIN="http://localhost:5173")
    assert response.status_code == 200
    assert response["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.django_db
def test_disallowed_origin_is_not_reflected(client):
    response = client.get(reverse("api:health"), HTTP_ORIGIN="http://evil.example")
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response


@pytest.mark.django_db
def test_health_returns_json(client):
    response = client.get(reverse("api:health"))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_admin_login_still_works(client):
    response = client.get("/admin/login/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_openapi_lists_versioned_paths(api_client):
    response = api_client.get(reverse("schema"), HTTP_ACCEPT="application/json")
    paths = response.json()["paths"]
    assert paths
    assert all(path.startswith("/api/v1/") for path in paths)
    assert "/api/v1/farmers/" in paths
