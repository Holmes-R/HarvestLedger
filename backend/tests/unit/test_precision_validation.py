"""M1 precision validation tests.

These pin the numeric contract documented in :mod:`procurement.precision`:

* every weight/moisture/price/money field declares the right
  ``max_digits``/``decimal_places``;
* excess input precision is *rejected* (via ``full_clean``/ModelForms), never
  silently rounded;
* ``save()`` does not run ``full_clean`` -- the reason M2 services must validate
  their own input before writing.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from procurement.models import (
    Advance,
    Crop,
    CropGrade,
    Delivery,
    DeliveryKind,
    Farmer,
    Payout,
    PriceListEntry,
)
from procurement.precision import (
    GROSS_KG_PLACES,
    MONEY_PLACES,
    quantize,
    validate_precision,
)

DECLARED_PLACES = [
    (Farmer, "outstanding_advance", 14, 2),
    (Crop, "moisture_threshold", 5, 2),
    (Crop, "max_moisture", 5, 2),
    (PriceListEntry, "price_per_kg", 12, 2),
    (Advance, "amount", 14, 2),
    (Payout, "gross_amount", 14, 2),
    (Payout, "advance_deduction", 14, 2),
    (Payout, "net_amount", 14, 2),
    (Delivery, "gross_weight_kg", 12, 3),
    (Delivery, "moisture_percent", 5, 2),
    (Delivery, "threshold_used", 5, 2),
    (Delivery, "deduction_kg", 15, 5),
    (Delivery, "net_kg", 15, 5),
    (Delivery, "applied_price", 12, 2),
    (Delivery, "amount", 14, 2),
    (Delivery, "correction_magnitude", 14, 2),
]


def _field(model, name):
    return model._meta.get_field(name)


@pytest.mark.parametrize(
    ("model", "name", "max_digits", "decimal_places"),
    DECLARED_PLACES,
    ids=[f"{m.__name__}.{n}" for m, n, _, _ in DECLARED_PLACES],
)
def test_fields_declare_deliberate_precision(model, name, max_digits, decimal_places):
    field = _field(model, name)
    assert field.max_digits == max_digits
    assert field.decimal_places == decimal_places
    assert field.get_internal_type() == "DecimalField"


OVER_PRECISE = [
    (Farmer, "outstanding_advance", "1.234"),
    (Crop, "moisture_threshold", "14.123"),
    (PriceListEntry, "price_per_kg", "24.505"),
    (Advance, "amount", "10.001"),
    (Payout, "net_amount", "10.001"),
    (Delivery, "gross_weight_kg", "100.0001"),
    (Delivery, "moisture_percent", "14.001"),
    (Delivery, "deduction_kg", "1.000001"),
    (Delivery, "net_kg", "99.000001"),
    (Delivery, "applied_price", "24.505"),
    (Delivery, "amount", "2450.001"),
    (Delivery, "correction_magnitude", "50.001"),
]


@pytest.mark.parametrize(
    ("model", "name", "value"),
    OVER_PRECISE,
    ids=[f"{m.__name__}.{n}" for m, n, _ in OVER_PRECISE],
)
def test_excess_precision_is_rejected(model, name, value):
    with pytest.raises(ValidationError):
        _field(model, name).clean(Decimal(value), None)


BOUNDARY_OK = [
    (Farmer, "outstanding_advance", "1.23"),
    (PriceListEntry, "price_per_kg", "24.50"),
    (Delivery, "gross_weight_kg", "100.000"),
    (Delivery, "moisture_percent", "14.00"),
    (Delivery, "deduction_kg", "1.00000"),
    (Delivery, "net_kg", "99.00000"),
    (Delivery, "amount", "2450.00"),
]


@pytest.mark.parametrize(
    ("model", "name", "value"),
    BOUNDARY_OK,
    ids=[f"{m.__name__}.{n}" for m, n, _ in BOUNDARY_OK],
)
def test_boundary_precision_is_accepted(model, name, value):
    _field(model, name).clean(Decimal(value), None)


def test_trailing_zeros_beyond_the_limit_are_rejected():
    # "1.2300" is 4 decimal places as written, even though it equals 1.23.
    with pytest.raises(ValidationError):
        _field(Farmer, "outstanding_advance").clean(Decimal("1.2300"), None)


def test_total_digits_are_still_bounded():
    with pytest.raises(ValidationError):
        _field(Delivery, "gross_weight_kg").clean(Decimal("100000000000.000"), None)


def test_non_finite_values_are_rejected():
    with pytest.raises(ValidationError):
        _field(Delivery, "gross_weight_kg").clean(Decimal("NaN"), None)


@pytest.mark.django_db
def test_full_clean_rejects_excess_precision_on_a_model():
    farmer = Farmer(name="Asha", phone="9000000000", village="Kolar")
    farmer.outstanding_advance = Decimal("1.234")
    with pytest.raises(ValidationError) as excinfo:
        farmer.full_clean()
    assert "outstanding_advance" in excinfo.value.message_dict


@pytest.fixture
def delivery(db):
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    grade = CropGrade.objects.create(crop=crop, code="A")
    price = PriceListEntry.objects.create(
        crop_grade=grade, price_per_kg=Decimal("24.50"), effective_from=date(2026, 1, 1)
    )
    farmer = Farmer.objects.create(name="Asha", phone="9000000000", village="Kolar")
    return Delivery(
        farmer=farmer,
        kind=DeliveryKind.PROCUREMENT,
        crop_grade=grade,
        delivered_on=date(2026, 1, 6),
        accounting_date=date(2026, 1, 6),
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("15.00"),
        applied_price=Decimal("24.50"),
        price_list_entry=price,
        amount=Decimal("2450.00"),
    )


def test_save_does_not_run_full_clean(delivery):
    # Documents the write-path gap: an over-precise value can be saved, so M2
    # services must validate input themselves instead of trusting the model.
    delivery.full_clean()
    delivery.gross_weight_kg = Decimal("100.0001")
    delivery.save()
    with pytest.raises(ValidationError):
        delivery.full_clean()


def test_validate_precision_helper_rejects_and_accepts():
    validate_precision(Decimal("24.50"), MONEY_PLACES, "price_per_kg")
    validate_precision(None, MONEY_PLACES, "price_per_kg")
    with pytest.raises(ValidationError) as excinfo:
        validate_precision(Decimal("24.505"), MONEY_PLACES, "price_per_kg")
    assert excinfo.value.code == "too_many_decimal_places"


def test_quantize_uses_round_half_up():
    assert GROSS_KG_PLACES == 3
    assert quantize(Decimal("1.0005"), 3) == Decimal("1.001")
    assert quantize(Decimal("4.999995"), 2) == Decimal("5.00")
    assert quantize(Decimal("2.675"), 2) == Decimal("2.68")
    assert isinstance(quantize(Decimal(1), 2), Decimal)
