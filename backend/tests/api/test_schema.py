"""M3: OpenAPI schema and documentation endpoints."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.m3


@pytest.mark.django_db
def test_openapi_schema_is_served(api_client):
    response = api_client.get(reverse("schema"), HTTP_ACCEPT="application/json")
    assert response.status_code == 200
    assert "openapi" in response.json()


@pytest.mark.django_db
def test_swagger_ui_is_served(api_client):
    response = api_client.get(reverse("docs"))
    assert response.status_code == 200
