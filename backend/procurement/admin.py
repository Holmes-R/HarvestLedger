"""Admin registration for the procurement domain.

IMPORTANT: These admin restrictions are a guardrail, not the business rules.
They do NOT replace service-layer logic. Financial changes (record deliveres,
post advances, generate/finalise payouts, apply corrections) must go through the
service functions introduced in M2 so that validation, effective-dated pricing,
moisture maths, advance recovery and immutability are enforced consistently.

Until those service-backed workflows exist, financial records are exposed
view-only here so the admin cannot bypass them with uncontrolled edits.
"""

from django.contrib import admin

from .models import Advance, Crop, CropGrade, Delivery, Farmer, Payout, PriceListEntry


class FinancialReadOnlyAdmin(admin.ModelAdmin):
    """View-only admin for financial records.

    No add/change/delete via the admin: these mutations belong to the
    service layer. Viewing the changelist and detail pages stays available.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Farmer)
class FarmerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "village", "outstanding_advance")
    search_fields = ("name", "phone", "village")
    readonly_fields = ("outstanding_advance", "created_at")

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields


@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = ("name", "moisture_threshold", "max_moisture")
    search_fields = ("name",)
    readonly_fields = ("created_at",)


@admin.register(CropGrade)
class CropGradeAdmin(admin.ModelAdmin):
    list_display = ("crop", "code")
    list_filter = ("crop",)
    search_fields = ("crop__name", "code")
    readonly_fields = ("created_at",)


@admin.register(PriceListEntry)
class PriceListEntryAdmin(admin.ModelAdmin):
    """Append-only price history: new entries may be added, existing ones are
    immutable and cannot be deleted."""

    list_display = ("crop_grade", "price_per_kg", "effective_from")
    list_filter = ("crop_grade__crop",)
    search_fields = ("crop_grade__crop__name", "crop_grade__code")
    ordering = ("crop_grade", "-effective_from")
    readonly_fields = ("created_at",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Advance)
class AdvanceAdmin(FinancialReadOnlyAdmin):
    list_display = ("farmer", "amount", "given_on")
    list_filter = ("given_on",)
    search_fields = ("farmer__name",)


@admin.register(Delivery)
class DeliveryAdmin(FinancialReadOnlyAdmin):
    list_display = (
        "farmer",
        "kind",
        "crop_grade",
        "accounting_date",
        "gross_weight_kg",
        "net_kg",
        "amount",
    )
    list_filter = ("kind", "crop_grade__crop")
    search_fields = ("farmer__name",)


@admin.register(Payout)
class PayoutAdmin(FinancialReadOnlyAdmin):
    list_display = (
        "farmer",
        "week_start",
        "week_end",
        "status",
        "gross_amount",
        "advance_deduction",
        "net_amount",
    )
    list_filter = ("status",)
    search_fields = ("farmer__name",)
