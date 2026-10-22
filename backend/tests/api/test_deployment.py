"""Deployment-facing checks that do not need hosted infrastructure."""

from django.conf import settings
from django.urls import reverse


def test_root_health_is_safe_json(client):
    assert reverse("health") == "/health/"
    response = client.get("/health/", secure=True)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {"status": "ok"}


def test_deployment_static_and_proxy_settings():
    assert settings.STORAGES["staticfiles"]["BACKEND"] == (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in settings.MIDDLEWARE
    assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert settings.STATIC_ROOT.name == "staticfiles"
    assert settings.STATIC_URL == "/static/"
