"""Domain models for produce procurement and payouts.

Numeric precision follows :mod:`procurement.precision`: gross kg 3 dp, moisture
2 dp, derived kg 5 dp, price/money 2 dp, monetary maths with ``Decimal`` and
``ROUND_HALF_UP``. ``DecimalField`` rejects excess input precision through
``full_clean()`` (ModelForms/admin), but ``save()`` does **not** call
``full_clean()``; see that module for the full M1/M2/M3 enforcement contract.
"""

from typing import ClassVar

from django.db import models
from django.db.models import F, Q


class DeliveryKind(models.TextChoices):
    PROCUREMENT = "PROCUREMENT", "Procurement"
    CREDIT_NOTE = "CREDIT_NOTE", "Credit note"
    DEBIT_NOTE = "DEBIT_NOTE", "Debit note"


class PayoutStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    FINALISED = "FINALISED", "Finalised"
    PAID = "PAID", "Paid"


GRADE_NOTE_KINDS = [DeliveryKind.CREDIT_NOTE, DeliveryKind.DEBIT_NOTE]


class Farmer(models.Model):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    village = models.CharField(max_length=120)
    bank_reference = models.CharField(max_length=255, blank=True, default="")
    outstanding_advance = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )  # money: 2 dp, 0.00 .. 999,999,999,999.99
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=Q(outstanding_advance__gte=0),
                name="farmer_outstanding_nonnegative",
            ),
        ]

    def __str__(self):
        return self.name


class Crop(models.Model):
    name = models.CharField(max_length=100, unique=True)
    moisture_threshold = models.DecimalField(
        max_digits=5, decimal_places=2
    )  # moisture: 2 dp, bounded 0..100 by crop_moisture_bounds_valid
    max_moisture = models.DecimalField(
        max_digits=5, decimal_places=2
    )  # moisture: 2 dp, bounded 0..100 by crop_moisture_bounds_valid
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=(
                    Q(moisture_threshold__gte=0)
                    & Q(moisture_threshold__lte=F("max_moisture"))
                    & Q(max_moisture__lte=100)
                ),
                name="crop_moisture_bounds_valid",
            ),
        ]

    def __str__(self):
        return self.name


class CropGrade(models.Model):
    crop = models.ForeignKey(
        Crop, on_delete=models.CASCADE, related_name="grades", db_index=False
    )
    code = models.CharField(max_length=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["crop", "code"],
                name="cropgrade_unique_crop_code",
            ),
        ]

    def __str__(self):
        return f"{self.crop.name} {self.code}"


class PriceListEntry(models.Model):
    crop_grade = models.ForeignKey(
        CropGrade,
        on_delete=models.PROTECT,
        related_name="price_entries",
        db_index=False,
    )
    price_per_kg = models.DecimalField(
        max_digits=12, decimal_places=2
    )  # rate: 2 dp, 0.01 .. 9,999,999,999.99
    effective_from = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=Q(price_per_kg__gt=0),
                name="pricelistentry_price_positive",
            ),
            models.UniqueConstraint(
                fields=["crop_grade", "effective_from"],
                name="pricelist_grade_eff_unique",
            ),
        ]

    def __str__(self):
        return f"{self.crop_grade} @ {self.price_per_kg} from {self.effective_from}"


class Advance(models.Model):
    farmer = models.ForeignKey(
        Farmer, on_delete=models.PROTECT, related_name="advances"
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2
    )  # money: 2 dp, 0.01 .. 999,999,999,999.99
    given_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="advance_amount_positive",
            ),
        ]

    def __str__(self):
        return f"{self.farmer} advance {self.amount}"


class Payout(models.Model):
    farmer = models.ForeignKey(
        Farmer, on_delete=models.PROTECT, related_name="payouts", db_index=False
    )
    week_start = models.DateField()  # Monday, IST business date
    week_end = models.DateField()  # Sunday (inclusive), IST business date
    status = models.CharField(
        max_length=10, choices=PayoutStatus.choices, default=PayoutStatus.DRAFT
    )
    gross_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )  # money: 2 dp
    advance_deduction = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )  # money: 2 dp
    net_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )  # money: 2 dp
    created_at = models.DateTimeField(auto_now_add=True)
    finalised_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        PayoutStatus.DRAFT,
                        PayoutStatus.FINALISED,
                        PayoutStatus.PAID,
                    ]
                ),
                name="payout_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(week_end__gte=F("week_start")),
                name="payout_week_valid",
            ),
            models.UniqueConstraint(
                fields=["farmer", "week_start"],
                condition=Q(status=PayoutStatus.DRAFT),
                name="payout_one_draft_farmer_week",
            ),
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["farmer", "week_start"], name="payout_farmer_week"),
            models.Index(fields=["status"], name="payout_status"),
        ]

    def __str__(self):
        return f"{self.farmer} week {self.week_start} ({self.status})"


class Delivery(models.Model):
    farmer = models.ForeignKey(
        Farmer, on_delete=models.PROTECT, related_name="deliveries", db_index=False
    )
    kind = models.CharField(
        max_length=16,
        choices=DeliveryKind.choices,
        default=DeliveryKind.PROCUREMENT,
    )
    crop_grade = models.ForeignKey(
        CropGrade,
        on_delete=models.PROTECT,
        related_name="deliveries",
        null=True,
        blank=True,
    )
    delivered_on = models.DateField(null=True, blank=True)  # IST business date
    accounting_date = models.DateField(
        null=True, blank=True
    )  # IST business date; == delivered_on for PROCUREMENT (see constraint)

    gross_weight_kg = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )  # measured: 3 dp, 0.001 .. 999,999,999.999 kg
    moisture_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )  # moisture: 2 dp, 0.00 .. 100.00 by rule
    threshold_used = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )  # moisture: 2 dp, frozen from Crop.moisture_threshold at record time
    deduction_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0
    )  # percent: 2 dp, 0.00 .. 10.00 in practice (engine caps at 10)
    deduction_kg = models.DecimalField(
        max_digits=15, decimal_places=5, default=0
    )  # derived: 5 dp
    net_kg = models.DecimalField(
        max_digits=15, decimal_places=5, default=0
    )  # derived: 5 dp
    applied_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )  # rate: 2 dp, frozen from PriceListEntry.price_per_kg
    price_list_entry = models.ForeignKey(
        PriceListEntry,
        on_delete=models.PROTECT,
        related_name="deliveries",
        null=True,
        blank=True,
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )  # money: 2 dp
    calculation_version = models.PositiveSmallIntegerField(default=1)

    original_delivery = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="corrections",
        null=True,
        blank=True,
    )
    correction_magnitude = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )  # money: 2 dp, positive magnitude; sign carried by kind
    reason = models.CharField(max_length=255, blank=True, default="")

    payout = models.ForeignKey(
        Payout,
        on_delete=models.PROTECT,
        related_name="deliveries",
        null=True,
        blank=True,
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=(
                    ~Q(kind=DeliveryKind.PROCUREMENT)
                    | (
                        Q(gross_weight_kg__gt=0)
                        & Q(moisture_percent__gt=0)
                        & Q(crop_grade__isnull=False)
                        & Q(original_delivery__isnull=True)
                    )
                ),
                name="delivery_procurement_positive",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(kind__in=GRADE_NOTE_KINDS)
                    | (
                        Q(original_delivery__isnull=False)
                        & Q(correction_magnitude__gt=0)
                        & ~Q(reason="")
                        & Q(gross_weight_kg__isnull=True)
                        & Q(moisture_percent__isnull=True)
                    )
                ),
                name="delivery_note_requires_fields",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(kind=DeliveryKind.PROCUREMENT)
                    | (
                        Q(delivered_on__isnull=False)
                        & Q(accounting_date=F("delivered_on"))
                    )
                ),
                name="delivery_accounting_matches_delivered",
            ),
        ]
        indexes: ClassVar[list] = [
            models.Index(
                fields=["farmer", "accounting_date"],
                name="delivery_farmer_accounting",
            ),
        ]

    def __str__(self):
        return f"{self.farmer} {self.kind} {self.amount}"
