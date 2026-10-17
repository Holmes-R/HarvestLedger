"""Admin restriction tests.

The admin is a guardrail only (see ``procurement.admin``). These tests pin the
intended posture: reference data is administrable, price history is append-only,
and financial records are view-only so the admin cannot bypass future services.
"""

import pytest
from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory

import procurement.admin  # noqa: F401  (ensure registrations are loaded)
from procurement.models import (
    Advance,
    Crop,
    CropGrade,
    Delivery,
    Farmer,
    Payout,
    PriceListEntry,
)


@pytest.fixture
def request_with_superuser(db):
    user = User.objects.create_superuser("boss", "boss@example.com", "pw")
    request = RequestFactory().get("/admin/")
    request.user = user
    return request


def _model_admin(model):
    return admin.site._registry[model]


def test_price_history_is_append_only(request_with_superuser):
    model_admin = _model_admin(PriceListEntry)
    assert model_admin.has_add_permission(request_with_superuser) is True
    assert model_admin.has_change_permission(request_with_superuser) is False
    assert model_admin.has_delete_permission(request_with_superuser) is False


@pytest.mark.parametrize("model", [Advance, Delivery, Payout])
def test_financial_records_are_view_only(request_with_superuser, model):
    model_admin = _model_admin(model)
    assert model_admin.has_add_permission(request_with_superuser) is False
    assert model_admin.has_change_permission(request_with_superuser) is False
    assert model_admin.has_delete_permission(request_with_superuser) is False


def test_farmer_reference_edits_allowed_but_balance_is_readonly(request_with_superuser):
    model_admin = _model_admin(Farmer)
    assert model_admin.has_add_permission(request_with_superuser) is True
    assert model_admin.has_change_permission(request_with_superuser) is True
    assert "outstanding_advance" in model_admin.get_readonly_fields(
        request_with_superuser
    )


@pytest.mark.parametrize("model", [Crop, CropGrade])
def test_reference_data_is_administrable(request_with_superuser, model):
    model_admin = _model_admin(model)
    assert model_admin.has_add_permission(request_with_superuser) is True
    assert model_admin.has_change_permission(request_with_superuser) is True
