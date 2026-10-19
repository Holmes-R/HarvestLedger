"""API serializers.

Serializers only validate **request shape** (types, required fields, decimal
precision and field capacity) and render responses. Domain rules stay in
:mod:`procurement.services`. Every decimal is rendered as a string at the model
field's documented scale (``COERCE_DECIMAL_TO_STRING``).

Reference fields resolve a primary key to a stored object and, when it is
absent, raise the domain not-found error (404) instead of DRF's generic
``does_not_exist`` (400) -- a request-level lookup, not a business rule.
"""

from django.db import transaction
from django.db.models.deletion import ProtectedError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from procurement.api.errors import GradeInUse
from procurement.clock import get_clock
from procurement.models import (
    GRADE_NOTE_KINDS,
    Advance,
    Crop,
    CropGrade,
    Delivery,
    Farmer,
    Payout,
    PriceListEntry,
)
from procurement.services.advances import post_advance
from procurement.services.corrections import record_correction
from procurement.services.delivery import edit_delivery, record_delivery
from procurement.services.errors import (
    CropGradeNotFound,
    CropNotFound,
    FarmerNotFound,
)
from procurement.services.pricing import create_price_entry


def model_decimal(model, field_name, **kwargs):
    """A ``DecimalField`` bound to ``model``'s field metadata.

    Reads ``max_digits``/``decimal_places`` from the model so request validation
    rejects over-precise or over-capacity input before it reaches a service, and
    responses use the same scale. Rendered as a string.
    """
    field = model._meta.get_field(field_name)
    kwargs.setdefault("max_digits", field.max_digits)
    kwargs.setdefault("decimal_places", field.decimal_places)
    kwargs.setdefault("coerce_to_string", True)
    return serializers.DecimalField(**kwargs)


def _contains_code(exc, wanted):
    """Whether a DRF ``ValidationError`` carries ``wanted`` among its codes."""

    def flatten(value):
        if isinstance(value, dict):
            value = list(value.values())
        if isinstance(value, (list, tuple)):
            for item in value:
                yield from flatten(item)
        else:
            yield value

    return wanted in set(flatten(exc.get_codes()))


class ProtectedFieldMixin:
    """Reject writes to server-computed fields and to unsupported fields.

    The write contract is explicit: a client must not set a computed field
    (``amount``, ``net_kg``, ``outstanding_advance``, ...) or any field the
    endpoint does not accept. Such attempts return ``400`` with code
    ``protected_field`` / ``unsupported_field`` -- they are refused, never
    silently dropped by ``read_only``.
    """

    #: Field names computed by the server that a write must not supply.
    protected_fields = ()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        data = self.initial_data
        if hasattr(data, "keys"):
            writable = {
                name
                for name, field in self.fields.items()
                if not field.read_only
            }
            for key in data:
                if key in self.protected_fields:
                    raise serializers.ValidationError(
                        {
                            key: [
                                ErrorDetail(
                                    f"{key} is computed by the server and cannot "
                                    "be set.",
                                    code="protected_field",
                                )
                            ]
                        }
                    )
                if key not in writable:
                    raise serializers.ValidationError(
                        {
                            key: [
                                ErrorDetail(
                                    f"{key} is not a supported field for this "
                                    "endpoint.",
                                    code="unsupported_field",
                                )
                            ]
                        }
                    )
        return attrs


class ReferenceField(serializers.PrimaryKeyRelatedField):
    """Primary-key reference that reports an absent row as a domain 404."""

    not_found_error = None
    not_found_label = "object"

    def to_internal_value(self, data):
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError as exc:
            if self.not_found_error is not None and _contains_code(
                exc, "does_not_exist"
            ):
                raise self.not_found_error(
                    f"{self.not_found_label} {data} was not found."
                ) from exc
            raise


class FarmerReferenceField(ReferenceField):
    not_found_error = FarmerNotFound
    not_found_label = "Farmer"


class CropReferenceField(ReferenceField):
    not_found_error = CropNotFound
    not_found_label = "Crop"


class CropGradeReferenceField(ReferenceField):
    not_found_error = CropGradeNotFound
    not_found_label = "Crop grade"


# --- Reference data ---------------------------------------------------------


class CropGradeRefSerializer(serializers.ModelSerializer):
    """An allowed grade rendered on a crop response."""

    class Meta:
        model = CropGrade
        fields = ("id", "code")
        read_only_fields = fields


class CropSerializer(serializers.ModelSerializer):
    moisture_threshold = model_decimal(Crop, "moisture_threshold", read_only=True)
    max_moisture = model_decimal(Crop, "max_moisture", read_only=True)
    allowed_grades = serializers.SerializerMethodField()

    class Meta:
        model = Crop
        fields = (
            "id",
            "name",
            "moisture_threshold",
            "max_moisture",
            "allowed_grades",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(CropGradeRefSerializer(many=True))
    def get_allowed_grades(self, crop):
        return CropGradeRefSerializer(
            crop.grades.order_by("code"), many=True
        ).data


class CropGradeSerializer(serializers.ModelSerializer):
    crop_name = serializers.CharField(source="crop.name", read_only=True)

    class Meta:
        model = CropGrade
        fields = ("id", "crop", "crop_name", "code", "created_at")
        read_only_fields = fields


def _clean_grade_codes(codes):
    """Return grade codes stripped, validated and de-duplicated in order."""
    cleaned = []
    for raw in codes:
        code = raw.strip()
        if not code:
            raise serializers.ValidationError(
                {
                    "allowed_grades": [
                        ErrorDetail(
                            "Grade codes must be non-blank.", code="invalid"
                        )
                    ]
                }
            )
        if code not in cleaned:
            cleaned.append(code)
    return cleaned


def _grade_in_use(crop, code):
    return GradeInUse(
        f"Grade '{code}' for crop '{crop.name}' is referenced by existing "
        "price or delivery records and cannot be removed."
    )


def _reconcile_grades(crop, codes):
    """Replace the crop's allowed grade set, protecting used grades.

    Adds missing codes and removes codes no longer listed -- but a grade with
    any price entry or delivery is **historical** and is never destructively
    removed (``409 grade_in_use``). Runs in the caller's transaction so a
    rejected removal rolls the whole change back.
    """
    existing = {grade.code: grade for grade in crop.grades.all()}
    desired = set(codes)
    for code in codes:
        if code not in existing:
            CropGrade.objects.create(crop=crop, code=code)
    for code, grade in existing.items():
        if code in desired:
            continue
        if grade.price_entries.exists() or grade.deliveries.exists():
            raise _grade_in_use(crop, code)
        try:
            grade.delete()
        except ProtectedError as exc:
            raise _grade_in_use(crop, code) from exc


class CropWriteSerializer(ProtectedFieldMixin, serializers.Serializer):
    """Create or configure a crop and its allowed grades.

    Grows the reference data: ``allowed_grades`` is the crop's grade set, given
    as short codes. On update it replaces the set, refusing to remove a grade
    that has historical price or delivery usage. Moisture is validated against
    the stored invariant ``0 <= moisture_threshold <= max_moisture <= 100``.
    """

    name = serializers.CharField(
        max_length=Crop._meta.get_field("name").max_length
    )
    moisture_threshold = model_decimal(Crop, "moisture_threshold")
    max_moisture = model_decimal(Crop, "max_moisture")
    allowed_grades = serializers.ListField(
        child=serializers.CharField(
            max_length=CropGrade._meta.get_field("code").max_length
        ),
        required=False,
    )
    protected_fields = ("id", "created_at", "grades")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = self.instance
        threshold = attrs.get(
            "moisture_threshold",
            getattr(instance, "moisture_threshold", None),
        )
        maximum = attrs.get(
            "max_moisture", getattr(instance, "max_moisture", None)
        )
        if threshold is not None and maximum is not None and not (
            0 <= threshold <= maximum <= 100
        ):
            raise serializers.ValidationError(
                {
                    "max_moisture": [
                        ErrorDetail(
                            "Moisture configuration must satisfy "
                            "0 <= moisture_threshold <= max_moisture <= 100.",
                            code="invalid_moisture_bounds",
                        )
                    ]
                }
            )
        name = attrs.get("name")
        if name is not None:
            clash = Crop.objects.filter(name=name)
            if instance is not None:
                clash = clash.exclude(pk=instance.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    {
                        "name": [
                            ErrorDetail(
                                "A crop with this name already exists.",
                                code="duplicate_crop",
                            )
                        ]
                    }
                )
        if "allowed_grades" in attrs:
            attrs["allowed_grades"] = _clean_grade_codes(attrs["allowed_grades"])
        return attrs

    def create(self, validated_data):
        codes = validated_data.pop("allowed_grades", None) or []
        with transaction.atomic():
            crop = Crop(**validated_data)
            crop.full_clean(validate_unique=False)
            crop.save()
            _reconcile_grades(crop, codes)
        return crop

    def update(self, instance, validated_data):
        codes = validated_data.pop("allowed_grades", None)
        with transaction.atomic():
            for field, value in validated_data.items():
                setattr(instance, field, value)
            instance.full_clean(validate_unique=False)
            instance.save()
            if codes is not None:
                _reconcile_grades(instance, codes)
        return instance


class FarmerSerializer(ProtectedFieldMixin, serializers.ModelSerializer):
    outstanding_advance = model_decimal(
        Farmer, "outstanding_advance", read_only=True
    )
    bank_reference = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    protected_fields = ("id", "outstanding_advance", "created_at")

    class Meta:
        model = Farmer
        fields = (
            "id",
            "name",
            "phone",
            "village",
            "bank_reference",
            "outstanding_advance",
            "created_at",
        )
        read_only_fields = ("id", "outstanding_advance", "created_at")

    def create(self, validated_data):
        # Reference data: no calculation, but run full model validation
        # (Indian-mobile validator + check constraints) before saving.
        farmer = Farmer(**validated_data)
        farmer.full_clean()
        farmer.save()
        return farmer

    def update(self, instance, validated_data):
        # Identity and the server-owned outstanding balance are read-only, so
        # they can never arrive here; re-validate the merged record before save.
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.full_clean()
        instance.save()
        return instance


class PriceListEntrySerializer(serializers.ModelSerializer):
    crop_grade_code = serializers.CharField(source="crop_grade.code", read_only=True)
    crop = serializers.IntegerField(source="crop_grade.crop_id", read_only=True)
    crop_name = serializers.CharField(source="crop_grade.crop.name", read_only=True)
    price_per_kg = model_decimal(PriceListEntry, "price_per_kg", read_only=True)

    class Meta:
        model = PriceListEntry
        fields = (
            "id",
            "crop_grade",
            "crop_grade_code",
            "crop",
            "crop_name",
            "price_per_kg",
            "effective_from",
            "created_at",
        )
        read_only_fields = fields


class GradeOrCodeField(serializers.Field):
    """Accept a crop-grade primary key or a grade code.

    A numeric value is treated as a primary key (absent -> ``CropGradeNotFound``,
    404); a non-numeric string is treated as a grade code and passed through for
    the service to validate against the crop (``GradeNotAllowed``, 422).
    """

    def to_internal_value(self, data):
        if isinstance(data, bool) or data is None:
            raise serializers.ValidationError(
                "grade must be a grade id or code.", code="invalid"
            )
        if isinstance(data, int) or (isinstance(data, str) and data.strip().isdigit()):
            grade = CropGrade.objects.filter(pk=int(data)).first()
            if grade is None:
                raise CropGradeNotFound(f"Crop grade {data} was not found.")
            return grade
        if isinstance(data, str) and data.strip():
            return data.strip()
        raise serializers.ValidationError(
            "grade must be a grade id or code.", code="invalid"
        )

    def to_representation(self, value):
        return getattr(value, "code", value)


class PriceEntryCreateSerializer(ProtectedFieldMixin, serializers.Serializer):
    crop = CropReferenceField(queryset=Crop.objects.all())
    grade = GradeOrCodeField()
    price_per_kg = model_decimal(PriceListEntry, "price_per_kg")
    effective_from = serializers.DateField()
    protected_fields = (
        "id",
        "crop_grade",
        "crop_grade_code",
        "crop_name",
        "created_at",
    )

    def create(self, validated_data):
        return create_price_entry(
            crop=validated_data["crop"],
            grade=validated_data["grade"],
            price_per_kg=validated_data["price_per_kg"],
            effective_from=validated_data["effective_from"],
        )


# Read-only decimal field specs (scale must match the source columns).
_MONEY = {"max_digits": 14, "decimal_places": 2, "coerce_to_string": True}
_GROSS = {"max_digits": 12, "decimal_places": 3, "coerce_to_string": True}
_DERIVED = {"max_digits": 15, "decimal_places": 5, "coerce_to_string": True}
_RATE = {"max_digits": 12, "decimal_places": 2, "coerce_to_string": True}
_MOISTURE = {"max_digits": 5, "decimal_places": 2, "coerce_to_string": True}


# --- Deliveries -------------------------------------------------------------


class DeliveryReadSerializer(serializers.ModelSerializer):
    gross_weight_kg = model_decimal(Delivery, "gross_weight_kg", read_only=True)
    moisture_percent = model_decimal(Delivery, "moisture_percent", read_only=True)
    threshold_used = model_decimal(Delivery, "threshold_used", read_only=True)
    deduction_percent = model_decimal(Delivery, "deduction_percent", read_only=True)
    deduction_kg = model_decimal(Delivery, "deduction_kg", read_only=True)
    net_kg = model_decimal(Delivery, "net_kg", read_only=True)
    applied_price = model_decimal(Delivery, "applied_price", read_only=True)
    amount = model_decimal(Delivery, "amount", read_only=True)
    correction_magnitude = model_decimal(
        Delivery, "correction_magnitude", read_only=True
    )

    class Meta:
        model = Delivery
        fields = (
            "id",
            "farmer",
            "kind",
            "crop_grade",
            "delivered_on",
            "accounting_date",
            "gross_weight_kg",
            "moisture_percent",
            "threshold_used",
            "deduction_percent",
            "deduction_kg",
            "net_kg",
            "applied_price",
            "price_list_entry",
            "amount",
            "calculation_version",
            "original_delivery",
            "correction_magnitude",
            "reason",
            "payout",
            "recorded_at",
        )
        read_only_fields = fields


class DeliveryPreviewSerializer(serializers.Serializer):
    """Renders the non-persisted ``DeliveryPreview`` result."""

    farmer_id = serializers.IntegerField(read_only=True)
    crop_grade = serializers.IntegerField(source="crop_grade.pk", read_only=True)
    delivered_on = serializers.DateField(read_only=True)
    accounting_date = serializers.DateField(read_only=True)
    #: Effective business date for the request's clock. Normally the real IST
    #: date; reflects the reviewer override when one is authorised, so a demo can
    #: see exactly which business date the calculation was made against.
    business_date = serializers.SerializerMethodField()
    gross_weight_kg = serializers.DecimalField(read_only=True, **_GROSS)
    moisture_percent = serializers.DecimalField(read_only=True, **_MOISTURE)
    threshold_used = serializers.DecimalField(read_only=True, **_MOISTURE)
    applied_price = serializers.DecimalField(read_only=True, **_RATE)
    price_list_entry = serializers.IntegerField(
        source="price_list_entry.pk", read_only=True
    )
    deduction_percent = serializers.DecimalField(read_only=True, **_MOISTURE)
    deduction_kg = serializers.DecimalField(read_only=True, **_DERIVED)
    net_kg = serializers.DecimalField(read_only=True, **_DERIVED)
    amount = serializers.DecimalField(read_only=True, **_MONEY)

    @extend_schema_field(serializers.DateField)
    def get_business_date(self, obj):
        return get_clock().today()


# Server-computed delivery fields a write must never supply. ``crop_grade``,
# ``delivered_on``, ``gross_weight_kg`` and ``moisture_percent`` are the only
# writable inputs; everything else is derived from the stored snapshot.
_DELIVERY_PROTECTED = (
    "id",
    "kind",
    "accounting_date",
    "threshold_used",
    "deduction_percent",
    "deduction_kg",
    "net_kg",
    "applied_price",
    "price_list_entry",
    "amount",
    "calculation_version",
    "original_delivery",
    "correction_magnitude",
    "reason",
    "payout",
    "recorded_at",
)


class DeliveryWriteSerializer(ProtectedFieldMixin, serializers.Serializer):
    """Validates a delivery request and calls the recording service."""

    farmer = FarmerReferenceField(queryset=Farmer.objects.all())
    crop_grade = CropGradeReferenceField(queryset=CropGrade.objects.all())
    delivered_on = serializers.DateField()
    gross_weight_kg = model_decimal(Delivery, "gross_weight_kg")
    moisture_percent = model_decimal(Delivery, "moisture_percent")
    protected_fields = _DELIVERY_PROTECTED

    def create(self, validated_data):
        return record_delivery(**validated_data)


class DeliveryEditSerializer(ProtectedFieldMixin, serializers.Serializer):
    """Validates a partial delivery edit and calls the edit service."""

    delivered_on = serializers.DateField(required=False)
    crop_grade = CropGradeReferenceField(
        queryset=CropGrade.objects.all(), required=False
    )
    gross_weight_kg = model_decimal(
        Delivery, "gross_weight_kg", required=False
    )
    moisture_percent = model_decimal(
        Delivery, "moisture_percent", required=False
    )
    protected_fields = _DELIVERY_PROTECTED

    def update(self, instance, validated_data):
        return edit_delivery(instance, **validated_data)


# --- Ledger (read-only projection of FarmerLedger) --------------------------


class LedgerDeliverySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    kind = serializers.CharField(read_only=True)
    crop_grade = serializers.IntegerField(source="crop_grade_id", read_only=True)
    delivered_on = serializers.DateField(read_only=True)
    accounting_date = serializers.DateField(read_only=True)
    gross_weight_kg = serializers.DecimalField(
        read_only=True, allow_null=True, **_GROSS
    )
    moisture_percent = serializers.DecimalField(
        read_only=True, allow_null=True, **_MOISTURE
    )
    net_kg = serializers.DecimalField(read_only=True, allow_null=True, **_DERIVED)
    applied_price = serializers.DecimalField(
        read_only=True, allow_null=True, **_RATE
    )
    amount = serializers.DecimalField(read_only=True, allow_null=True, **_MONEY)
    payout = serializers.IntegerField(
        source="payout_id", read_only=True, allow_null=True
    )
    original_delivery = serializers.IntegerField(
        source="original_delivery_id", read_only=True, allow_null=True
    )
    correction_magnitude = serializers.DecimalField(
        read_only=True, allow_null=True, **_MONEY
    )
    reason = serializers.CharField(read_only=True)
    is_correction = serializers.BooleanField(read_only=True)
    is_assigned = serializers.BooleanField(read_only=True)
    signed_amount = serializers.DecimalField(read_only=True, **_MONEY)


class LedgerAdvanceSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    amount = serializers.DecimalField(read_only=True, **_MONEY)
    given_on = serializers.DateField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class LedgerPayoutSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    week_start = serializers.DateField(read_only=True)
    week_end = serializers.DateField(read_only=True)
    status = serializers.CharField(read_only=True)
    gross_amount = serializers.DecimalField(read_only=True, **_MONEY)
    advance_deduction = serializers.DecimalField(read_only=True, **_MONEY)
    net_amount = serializers.DecimalField(read_only=True, **_MONEY)
    finalised_at = serializers.DateTimeField(read_only=True, allow_null=True)
    paid_at = serializers.DateTimeField(read_only=True, allow_null=True)
    delivery_ids = serializers.ListField(
        child=serializers.IntegerField(), read_only=True
    )
    member_total = serializers.DecimalField(read_only=True, **_MONEY)
    is_draft = serializers.BooleanField(read_only=True)
    is_settled = serializers.BooleanField(read_only=True)
    gross_matches_members = serializers.BooleanField(read_only=True)
    net_equals_gross_minus_deduction = serializers.BooleanField(read_only=True)


class ReconciliationSerializer(serializers.Serializer):
    farmer_id = serializers.IntegerField(read_only=True)
    total_advances = serializers.DecimalField(read_only=True, **_MONEY)
    total_recovered = serializers.DecimalField(read_only=True, **_MONEY)
    expected_outstanding = serializers.DecimalField(read_only=True, **_MONEY)
    stored_outstanding = serializers.DecimalField(read_only=True, **_MONEY)
    difference = serializers.DecimalField(read_only=True, **_MONEY)
    is_reconciled = serializers.BooleanField(read_only=True)


class LedgerSummarySerializer(serializers.Serializer):
    """Account-level ledger facts: identity, balance, totals and reconciliation.

    These describe the **whole** account and never depend on any history window
    or page, so a bounded/paged view never distorts the balance.
    """

    farmer_id = serializers.IntegerField()
    name = serializers.CharField()
    phone = serializers.CharField()
    outstanding_advance = serializers.DecimalField(**_MONEY)
    reconciliation = ReconciliationSerializer()
    total_advances = serializers.DecimalField(**_MONEY)
    settled_earnings = serializers.DecimalField(**_MONEY)
    total_recovered = serializers.DecimalField(**_MONEY)
    draft_projection = serializers.DecimalField(**_MONEY)
    unassigned_earnings = serializers.DecimalField(**_MONEY)
    total_recorded_amount = serializers.DecimalField(**_MONEY)
    earnings_identity_holds = serializers.BooleanField()
    is_reconciled = serializers.BooleanField()
    history_from = serializers.DateField(allow_null=True)
    history_to = serializers.DateField(allow_null=True)


#: The kinds of event that make up a farmer ledger timeline.
LEDGER_EVENT_TYPES = ("DELIVERY", "CORRECTION", "ADVANCE", "PAYOUT")


class LedgerEventSerializer(serializers.Serializer):
    """One row of the ledger event timeline.

    ``event_type`` discriminates the payload: a delivery/correction carries
    ``delivery``, an advance ``advance`` and a payout ``payout``; the other two
    are ``null``. ``amount`` is the signed money movement the event contributes
    (a debit note is negative) and ``date`` is its business date.
    """

    event_type = serializers.ChoiceField(choices=LEDGER_EVENT_TYPES)
    id = serializers.IntegerField()
    date = serializers.DateField()
    amount = serializers.DecimalField(**_MONEY)
    delivery = LedgerDeliverySerializer(allow_null=True)
    advance = LedgerAdvanceSerializer(allow_null=True)
    payout = LedgerPayoutSerializer(allow_null=True)


class LedgerPageSerializer(serializers.Serializer):
    """A bounded page of ledger events plus the account summary."""

    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    summary = LedgerSummarySerializer()
    results = LedgerEventSerializer(many=True)


# --- Advances ---------------------------------------------------------------


class AdvanceSerializer(serializers.ModelSerializer):
    amount = model_decimal(Advance, "amount", read_only=True)

    class Meta:
        model = Advance
        fields = ("id", "farmer", "amount", "given_on", "created_at")
        read_only_fields = fields


class AdvanceCreateSerializer(ProtectedFieldMixin, serializers.Serializer):
    farmer = FarmerReferenceField(queryset=Farmer.objects.all())
    amount = model_decimal(Advance, "amount")
    given_on = serializers.DateField()
    protected_fields = (
        "id",
        "created_at",
        "outstanding_advance",
        "balance",
    )

    def create(self, validated_data):
        return post_advance(
            validated_data["farmer"],
            validated_data["amount"],
            validated_data["given_on"],
        )


class AdvanceReconciliationSerializer(serializers.Serializer):
    """Renders the read-only ``AdvanceReconciliation`` result."""

    farmer_id = serializers.IntegerField(read_only=True)
    total_advances = serializers.DecimalField(read_only=True, **_MONEY)
    total_recovered = serializers.DecimalField(read_only=True, **_MONEY)
    expected_outstanding = serializers.DecimalField(read_only=True, **_MONEY)
    stored_outstanding = serializers.DecimalField(read_only=True, **_MONEY)
    difference = serializers.DecimalField(read_only=True, **_MONEY)
    is_reconciled = serializers.BooleanField(read_only=True)


# --- Corrections (credit / debit notes) -------------------------------------


class CorrectionReadSerializer(serializers.ModelSerializer):
    correction_magnitude = model_decimal(
        Delivery, "correction_magnitude", read_only=True
    )
    amount = model_decimal(Delivery, "amount", read_only=True)

    class Meta:
        model = Delivery
        fields = (
            "id",
            "farmer",
            "kind",
            "original_delivery",
            "correction_magnitude",
            "reason",
            "accounting_date",
            "amount",
            "payout",
            "recorded_at",
        )
        read_only_fields = fields


class CorrectionCreateSerializer(ProtectedFieldMixin, serializers.Serializer):
    original_delivery = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=GRADE_NOTE_KINDS)
    magnitude = model_decimal(Delivery, "correction_magnitude")
    reason = serializers.CharField()
    protected_fields = (
        "id",
        "farmer",
        "correction_magnitude",
        "accounting_date",
        "amount",
        "payout",
        "recorded_at",
    )

    def create(self, validated_data):
        return record_correction(
            Delivery(pk=validated_data["original_delivery"]),
            validated_data["kind"],
            validated_data["magnitude"],
            validated_data["reason"],
        )


class DeliveryCorrectionCreateSerializer(ProtectedFieldMixin, serializers.Serializer):
    """Correction against the delivery named in the URL.

    The original is taken from the path, so ownership and state are resolved and
    validated by the service from persisted data. A client-supplied
    ``original_delivery``, ``farmer`` or any computed field (``amount``,
    ``correction_magnitude``, ``accounting_date``, ``payout``) is refused rather
    than trusted.
    """

    kind = serializers.ChoiceField(choices=GRADE_NOTE_KINDS)
    magnitude = model_decimal(Delivery, "correction_magnitude")
    reason = serializers.CharField()
    protected_fields = (
        "id",
        "farmer",
        "original_delivery",
        "correction_magnitude",
        "accounting_date",
        "amount",
        "payout",
        "recorded_at",
    )


# --- Payouts ----------------------------------------------------------------


class PayoutSerializer(serializers.ModelSerializer):
    """A payout statement: server-computed totals, status and frozen members.

    The totals, status and timestamps are stored, never client-derived, and the
    ``deliveries`` list renders the exact member snapshots currently attached by
    the service (procurement deliveries and credit/debit notes alike).
    """

    farmer_name = serializers.CharField(source="farmer.name", read_only=True)
    gross_amount = model_decimal(Payout, "gross_amount", read_only=True)
    advance_deduction = model_decimal(Payout, "advance_deduction", read_only=True)
    net_amount = model_decimal(Payout, "net_amount", read_only=True)
    deliveries = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = (
            "id",
            "farmer",
            "farmer_name",
            "week_start",
            "week_end",
            "status",
            "gross_amount",
            "advance_deduction",
            "net_amount",
            "deliveries",
            "created_at",
            "finalised_at",
            "paid_at",
        )
        read_only_fields = fields

    @extend_schema_field(DeliveryReadSerializer(many=True))
    def get_deliveries(self, payout):
        members = sorted(
            payout.deliveries.all(),
            key=lambda member: (member.accounting_date, member.pk),
        )
        return DeliveryReadSerializer(members, many=True).data


class PayoutGenerationSerializer(serializers.Serializer):
    """The outcome of a generation request.

    ``payout`` is the created or extended DRAFT statement, or ``null`` when the
    week has no eligible deliveries; ``reason`` then explains the absence.
    """

    payout = PayoutSerializer(read_only=True, allow_null=True)
    reason = serializers.CharField(read_only=True, allow_null=True)


class PayoutGenerateSerializer(ProtectedFieldMixin, serializers.Serializer):
    """Validates a generation request; the view calls the service.

    ``build_weekly_payout`` may legitimately return ``None`` (an empty week) and
    DRF's ``save()`` forbids that, so generation is issued by the view rather
    than through ``create()``.
    """

    farmer = FarmerReferenceField(queryset=Farmer.objects.all())
    week_start = serializers.DateField()
    protected_fields = (
        "id",
        "farmer_name",
        "week_end",
        "status",
        "gross_amount",
        "advance_deduction",
        "net_amount",
        "deliveries",
        "created_at",
        "finalised_at",
        "paid_at",
    )
