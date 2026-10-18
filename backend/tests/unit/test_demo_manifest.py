"""Guard rails for the deterministic demo/manifest data (no database access)."""

from dataclasses import FrozenInstanceError

import pytest

from procurement import scenarios as sc
from procurement.clock import week_bounds
from procurement.management.commands import seed_data as sd
from procurement.models import indian_mobile_validator

REQUIRED_CATEGORIES = {
    "multiple-weeks",
    "moisture-boundaries",
    "missing-rate",
    "backdated-price",
    "large-advance",
    "finalised-and-corrections",
}


def test_all_required_scenario_categories_present():
    assert REQUIRED_CATEGORIES <= {scenario.key for scenario in sc.SCENARIOS}


def test_scenario_and_record_keys_are_unique():
    keys = [scenario.key for scenario in sc.SCENARIOS]
    for scenario in sc.SCENARIOS:
        keys += [d.key for d in scenario.deliveries]
        keys += [a.key for a in scenario.advances]
        keys += [c.key for c in scenario.corrections]
    assert len(keys) == len(set(keys))


def test_same_day_advances_are_explicitly_supported():
    pairs = [
        (advance.farmer_key, advance.given_on)
        for scenario in sc.SCENARIOS
        for advance in scenario.advances
    ]
    assert len(pairs) != len(set(pairs)), "expected a duplicate (farmer, date)"
    assert "deduplication key" in sc.ADVANCE_DEDUPLICATION_NOTE.lower()


def test_scenarios_are_immutable():
    with pytest.raises(FrozenInstanceError):
        sc.SCENARIOS[0].key = "mutated"


def test_multiple_weeks_spans_three_weeks():
    scenario = next(s for s in sc.SCENARIOS if s.key == "multiple-weeks")
    weeks = {week_bounds(d.delivered_on) for d in scenario.deliveries}
    assert len(weeks) == 3


def test_seed_farmers_use_format_valid_example_phones():
    for farmer in sd.DEMO_FARMERS:
        indian_mobile_validator(farmer.phone)


def test_seed_prices_reference_existing_grades_and_are_effective_dated():
    crops = {crop.key: crop for crop in sd.DEMO_CROPS}
    seen: set[tuple[str, str, object]] = set()
    for price in sd.DEMO_PRICES:
        assert price.crop_key in crops
        assert price.grade_code in crops[price.crop_key].grades
        key = (price.crop_key, price.grade_code, price.effective_from)
        assert key not in seen, "duplicate (grade, effective_from)"
        seen.add(key)
        assert price.price_per_kg > 0
