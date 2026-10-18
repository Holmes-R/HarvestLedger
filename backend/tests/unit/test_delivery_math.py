"""Delivery moisture/money engine rules (M2).

These tests exercise the implemented M2 service layer (marker ``m2``); they run
against the real code, not a pending stub.

Contract exercised
------------------
``procurement.services.delivery.calculate_breakdown(
    gross_weight_kg, moisture_percent, price_per_kg, threshold, max_moisture
) -> Breakdown``

``Breakdown`` exposes ``deduction_percent`` (2 dp), ``deduction_kg`` (5 dp),
``net_kg`` (5 dp) and ``amount`` (2 dp). It raises
``procurement.services.delivery.MoistureExceedsMaximum`` when the moisture is
above ``max_moisture``. All arithmetic uses ``Decimal``/``ROUND_HALF_UP``; the
identity ``gross_weight_kg == deduction_kg + net_kg`` must hold exactly at 5 dp.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

pytestmark = pytest.mark.m2


def _service():
    from procurement.services import delivery

    return delivery


def _breakdown(**kwargs):
    return _service().calculate_breakdown(**kwargs)


def test_moisture_at_threshold_has_no_deduction():
    result = _breakdown(
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
        price_per_kg=Decimal("24.50"),
        threshold=Decimal("14.00"),
        max_moisture=Decimal("20.00"),
    )
    assert result.deduction_percent == Decimal("0.00")
    assert result.deduction_kg == Decimal("0.00000")
    assert result.net_kg == Decimal("100.00000")
    assert result.amount == Decimal("2450.00")


def test_threshold_plus_0_99_still_floors_to_zero():
    result = _breakdown(
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.99"),
        price_per_kg=Decimal("24.50"),
        threshold=Decimal("14.00"),
        max_moisture=Decimal("20.00"),
    )
    assert result.deduction_percent == Decimal("0.00")
    assert result.net_kg == Decimal("100.00000")


def test_full_point_flooring():
    # 15.99 - 14.00 = 1.99 -> floor -> 1 percent.
    result = _breakdown(
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("15.99"),
        price_per_kg=Decimal("24.50"),
        threshold=Decimal("14.00"),
        max_moisture=Decimal("20.00"),
    )
    assert result.deduction_percent == Decimal("1.00")
    assert result.deduction_kg == Decimal("1.00000")
    assert result.net_kg == Decimal("99.00000")
    assert result.amount == Decimal("2425.50")


@pytest.mark.parametrize(
    ("moisture", "deduction_percent", "deduction_kg", "net_kg", "amount"),
    [
        ("15.00", "1.00", "1.00000", "99.00000", "2425.50"),
        ("17.60", "3.00", "3.00000", "97.00000", "2376.50"),
        ("20.00", "6.00", "6.00000", "94.00000", "2303.00"),
    ],
)
def test_exact_moisture_boundaries(
    moisture, deduction_percent, deduction_kg, net_kg, amount
):
    result = _breakdown(
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal(moisture),
        price_per_kg=Decimal("24.50"),
        threshold=Decimal("14.00"),
        max_moisture=Decimal("20.00"),
    )
    assert result.deduction_percent == Decimal(deduction_percent)
    assert result.deduction_kg == Decimal(deduction_kg)
    assert result.net_kg == Decimal(net_kg)
    assert result.amount == Decimal(amount)
    assert result.deduction_kg + result.net_kg == Decimal("100.00000")


def test_moisture_above_maximum_is_rejected():
    delivery = _service()
    with pytest.raises(delivery.MoistureExceedsMaximum):
        delivery.calculate_breakdown(
            gross_weight_kg=Decimal("100.000"),
            moisture_percent=Decimal("20.01"),
            price_per_kg=Decimal("24.50"),
            threshold=Decimal("14.00"),
            max_moisture=Decimal("20.00"),
        )


def test_deduction_is_capped_at_ten_percent():
    # 30.00 - 5.00 = 25.00 -> capped at 10 percent.
    result = _breakdown(
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("30.00"),
        price_per_kg=Decimal("1.00"),
        threshold=Decimal("5.00"),
        max_moisture=Decimal("100.00"),
    )
    assert result.deduction_percent == Decimal("10.00")
    assert result.deduction_kg == Decimal("10.00000")
    assert result.net_kg == Decimal("90.00000")


@pytest.mark.parametrize(
    ("weight", "moisture"),
    [
        ("0.000", "14.00"),
        ("-1.000", "14.00"),
        ("100.000", "0.00"),
        ("100.000", "-0.01"),
    ],
)
def test_nonpositive_ordinary_inputs_are_rejected(weight, moisture):
    with pytest.raises(ValidationError):
        _breakdown(
            gross_weight_kg=Decimal(weight),
            moisture_percent=Decimal(moisture),
            price_per_kg=Decimal("24.50"),
            threshold=Decimal("14.00"),
            max_moisture=Decimal("20.00"),
        )


@pytest.mark.parametrize(
    ("weight", "moisture"),
    [("100.0001", "14.00"), ("100.000", "14.001")],
)
def test_overprecise_inputs_are_rejected(weight, moisture):
    with pytest.raises(ValidationError):
        _breakdown(
            gross_weight_kg=Decimal(weight),
            moisture_percent=Decimal(moisture),
            price_per_kg=Decimal("24.50"),
            threshold=Decimal("14.00"),
            max_moisture=Decimal("20.00"),
        )


def test_monetary_rounding_is_half_up():
    # 2.50000 kg * 1.01 = 2.5250 -> HALF_UP -> 2.53 (HALF_EVEN would give 2.52).
    result = _breakdown(
        gross_weight_kg=Decimal("2.500"),
        moisture_percent=Decimal("14.00"),
        price_per_kg=Decimal("1.01"),
        threshold=Decimal("14.00"),
        max_moisture=Decimal("20.00"),
    )
    assert result.amount == Decimal("2.53")


def test_fractional_arithmetic_keeps_decimal_and_documented_scales():
    result = _breakdown(
        gross_weight_kg=Decimal("100.125"),
        moisture_percent=Decimal("17.60"),
        price_per_kg=Decimal("24.50"),
        threshold=Decimal("14.00"),
        max_moisture=Decimal("20.00"),
    )
    assert result.deduction_percent == Decimal("3.00")
    assert result.deduction_kg == Decimal("3.00375")
    assert result.net_kg == Decimal("97.12125")
    assert result.amount == Decimal("2379.47")
    assert result.deduction_kg + result.net_kg == Decimal("100.12500")
    for field, places in (
        (result.deduction_percent, 2),
        (result.deduction_kg, 5),
        (result.net_kg, 5),
        (result.amount, 2),
    ):
        assert isinstance(field, Decimal)
        assert field.as_tuple().exponent == -places


@pytest.mark.parametrize("moisture", ["14.00", "15.99", "19.99"])
def test_gross_equals_deduction_plus_net(moisture):
    result = _breakdown(
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal(moisture),
        price_per_kg=Decimal("24.50"),
        threshold=Decimal("14.00"),
        max_moisture=Decimal("20.00"),
    )
    assert result.deduction_kg + result.net_kg == Decimal("100.000")
