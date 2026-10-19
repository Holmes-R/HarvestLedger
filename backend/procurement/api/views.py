"""M3 API views.

Each view resolves request references, calls exactly one service function and
renders the result. No business calculation, transaction or row lock lives here.
Path/body reference lookups are request-level resolution, not domain rules.
"""

from collections import OrderedDict

from django.db.models import Q
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
)
from rest_framework.response import Response

from procurement.clock import week_bounds
from procurement.models import (
    GRADE_NOTE_KINDS,
    Advance,
    Crop,
    CropGrade,
    Delivery,
    DeliveryKind,
    Farmer,
    Payout,
    PayoutStatus,
    PriceListEntry,
)
from procurement.services.advances import reconcile_outstanding
from procurement.services.corrections import record_correction
from procurement.services.delivery import preview_delivery
from procurement.services.errors import CropNotFound, FarmerNotFound
from procurement.services.ledger import build_farmer_ledger
from procurement.services.payouts import (
    build_weekly_payout,
    finalise_payout,
    mark_payout_paid,
)

from .filters import (
    date_range,
    order_events,
    order_queryset,
)
from .filters import parse_date_param as _date
from .filters import parse_int as _int
from .schema import (
    CORRECTION_EXAMPLE,
    CORRECTION_KIND_PARAM,
    CROP_GRADE_PARAM,
    CROP_PARAM,
    DELIVERY_KIND_PARAM,
    DELIVERY_PREVIEW_EXAMPLE,
    ERROR_EXAMPLE,
    EVENT_TYPE_PARAM,
    FARMER_PARAM,
    FROM_PARAM,
    LEDGER_PAGE_EXAMPLE,
    ORIGINAL_PARAM,
    PAYOUT_FINALISED_EXAMPLE,
    PAYOUT_GENERATE_CREATED_EXAMPLE,
    PAYOUT_GENERATE_EMPTY_EXAMPLE,
    PAYOUT_PARAM,
    REVIEW_CLOCK_HEADERS,
    SEARCH_PARAM,
    STATUS_PARAM,
    TO_PARAM,
    WEEK_PARAM,
    HealthSerializer,
    documented,
    ordering_parameter,
)
from .serializers import (
    LEDGER_EVENT_TYPES,
    AdvanceCreateSerializer,
    AdvanceReconciliationSerializer,
    AdvanceSerializer,
    CorrectionCreateSerializer,
    CorrectionReadSerializer,
    CropGradeSerializer,
    CropSerializer,
    CropWriteSerializer,
    DeliveryCorrectionCreateSerializer,
    DeliveryEditSerializer,
    DeliveryPreviewSerializer,
    DeliveryReadSerializer,
    DeliveryWriteSerializer,
    FarmerSerializer,
    LedgerEventSerializer,
    LedgerPageSerializer,
    LedgerSummarySerializer,
    PayoutGenerateSerializer,
    PayoutGenerationSerializer,
    PayoutSerializer,
    PriceEntryCreateSerializer,
    PriceListEntrySerializer,
)

#: Report code returned by ``POST /payouts/generate/`` when the week has no
#: eligible deliveries. Empty weeks are a successful no-op, so a payout is never
#: invented and the stance is stated explicitly instead.
NO_ELIGIBLE_DELIVERIES = "NO_ELIGIBLE_DELIVERIES"

#: Event types exposed by the farmer ledger, and the fields a client may order it
#: by. Ordering always finishes with the fixed ``(event_type, id)`` tie-breakers.
LEDGER_ORDERING_FIELDS = ("date", "amount", "id", "event_type")
LEDGER_DEFAULT_ORDERING = ("-date",)


@extend_schema(
    tags=["System"],
    summary="Health check",
    description="Liveness probe. Performs no database access and exposes no "
    "sensitive detail.",
    responses={200: HealthSerializer},
)
@api_view(["GET"])
def health(request):
    """Liveness probe; no database access, no sensitive detail."""
    return Response({"status": "ok"})


def _get_or_not_found(model, pk, error_cls, label):
    try:
        return model.objects.get(pk=pk)
    except (model.DoesNotExist, ValueError, TypeError) as exc:
        raise error_cls(f"{label} {pk} was not found.") from exc


class OrderingMixin:
    """Adds whitelisted ``?ordering=`` support to a list view.

    Each view declares ``ordering_fields`` and a ``default_ordering`` (which must
    itself end in an id tie-breaker); an unknown field is a ``400``.
    """

    ordering_fields = ()
    default_ordering = ("-id",)

    def apply_ordering(self, queryset):
        return order_queryset(
            self.request.query_params.get("ordering"),
            queryset,
            self.ordering_fields,
            self.default_ordering,
        )


# --- Farmers ----------------------------------------------------------------


@extend_schema_view(
    get=extend_schema(
        tags=["Reference data"],
        summary="List farmers",
        description=(
            "Lists farmers, optionally narrowed by ``?search=`` (a "
            "case-insensitive substring over name, phone or village). Ordering is "
            "restricted to the whitelisted keys and always ends with an ``id`` "
            "tie-breaker so paging is stable."
        ),
        parameters=[
            SEARCH_PARAM,
            ordering_parameter(
                ("id", "name", "phone", "village", "created_at"), "'id'"
            ),
        ],
        responses=documented({200: FarmerSerializer(many=True)}),
    ),
    post=extend_schema(
        tags=["Reference data"],
        summary="Create a farmer",
        description="Registers a farmer. The server-owned "
        "``outstanding_advance`` balance is read-only.",
        request=FarmerSerializer,
        responses=documented({201: FarmerSerializer}),
    ),
)
class FarmerListCreate(OrderingMixin, ListCreateAPIView):
    serializer_class = FarmerSerializer
    ordering_fields = ("id", "name", "phone", "village", "created_at")
    default_ordering = ("id",)

    def get_queryset(self):
        queryset = Farmer.objects.all()
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(phone__icontains=search)
                | Q(village__icontains=search)
            )
        return self.apply_ordering(queryset)


class FarmerDetailView(GenericAPIView):
    serializer_class = FarmerSerializer

    def get_object(self):
        return _get_or_not_found(Farmer, self.kwargs["pk"], FarmerNotFound, "Farmer")

    @extend_schema(
        tags=["Reference data"],
        summary="Retrieve a farmer",
        responses=documented({200: FarmerSerializer}),
    )
    def get(self, request, pk):
        return Response(FarmerSerializer(self.get_object()).data)

    @extend_schema(
        tags=["Reference data"],
        summary="Update a farmer",
        description="Partial update. Identity and the server-owned "
        "``outstanding_advance`` balance cannot be changed.",
        request=FarmerSerializer,
        responses=documented({200: FarmerSerializer}),
    )
    def patch(self, request, pk):
        farmer = self.get_object()
        serializer = FarmerSerializer(farmer, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(FarmerSerializer(updated).data)


def _ledger_events(ledger, event_type=None):
    """Flatten the ledger snapshot into one typed, bounded event timeline.

    Deliveries and correction notes, advances and payouts are merged into a
    single list (each row tagged with ``event_type``) so the growing history is
    the paginated collection itself -- never an unbounded list nested inside a
    paginated wrapper. ``event_type`` optionally narrows the timeline to one kind.
    """
    events = []
    for delivery in ledger.deliveries:
        events.append(
            {
                "event_type": "CORRECTION" if delivery.is_correction else "DELIVERY",
                "id": delivery.id,
                "date": delivery.accounting_date,
                "amount": delivery.signed_amount,
                "delivery": delivery,
                "advance": None,
                "payout": None,
            }
        )
    for advance in ledger.advances:
        events.append(
            {
                "event_type": "ADVANCE",
                "id": advance.id,
                "date": advance.given_on,
                "amount": advance.amount,
                "delivery": None,
                "advance": advance,
                "payout": None,
            }
        )
    for payout in ledger.payouts:
        events.append(
            {
                "event_type": "PAYOUT",
                "id": payout.id,
                "date": payout.week_start,
                "amount": payout.net_amount,
                "delivery": None,
                "advance": None,
                "payout": payout,
            }
        )
    if event_type is not None:
        events = [event for event in events if event["event_type"] == event_type]
    return events


class FarmerLedgerView(GenericAPIView):
    """A bounded page of ledger events, plus the account-level summary.

    The event timeline is the paginated collection (default 20, max 100 events;
    ``from``/``to`` are inclusive bounds on each event's business date and
    ``event_type`` filters to DELIVERY/CORRECTION/ADVANCE/PAYOUT). The summary
    (balance, totals, reconciliation) always covers the full history, so a page
    never changes the account balance.
    """

    serializer_class = LedgerPageSerializer

    @extend_schema(
        tags=["Operations"],
        summary="Farmer ledger (bounded event timeline + summary)",
        description=(
            "A bounded page of ledger events plus the account-level summary. The "
            "event timeline is the paginated collection (default 20, max 100 "
            "events); each row is typed ``event_type`` DELIVERY/CORRECTION/"
            "ADVANCE/PAYOUT and carries the matching nested object, a signed "
            "``amount`` and its business ``date``. ``from``/``to`` are inclusive "
            "bounds on the event date and ``event_type`` narrows to one kind. "
            "``summary`` (balance, totals, reconciliation) always covers the "
            "**full** history, so paging or windowing never changes the balance."
        ),
        parameters=[
            FROM_PARAM,
            TO_PARAM,
            EVENT_TYPE_PARAM,
            ordering_parameter(("date", "amount", "id", "event_type"), "'-date'"),
        ],
        responses=documented({200: LedgerPageSerializer}),
        examples=[LEDGER_PAGE_EXAMPLE, ERROR_EXAMPLE],
    )
    def get(self, request, pk):
        farmer = _get_or_not_found(Farmer, pk, FarmerNotFound, "Farmer")
        params = request.query_params
        since, until = date_range(params)
        event_type = params.get("event_type")
        if event_type is not None and event_type not in LEDGER_EVENT_TYPES:
            raise DRFValidationError(
                {
                    "event_type": [
                        {"code": "invalid", "message": "Unknown ledger event type."}
                    ]
                }
            )

        ledger = build_farmer_ledger(farmer, since=since, until=until)
        events = order_events(
            params.get("ordering"),
            _ledger_events(ledger, event_type),
            LEDGER_ORDERING_FIELDS,
            LEDGER_DEFAULT_ORDERING,
        )

        page = self.paginate_queryset(events)
        results = LedgerEventSerializer(page, many=True).data
        return Response(
            OrderedDict(
                [
                    ("count", self.paginator.page.paginator.count),
                    ("next", self.paginator.get_next_link()),
                    ("previous", self.paginator.get_previous_link()),
                    ("summary", LedgerSummarySerializer(ledger).data),
                    ("results", results),
                ]
            )
        )


# --- Crops and grades -------------------------------------------------------


@extend_schema_view(
    get=extend_schema(
        tags=["Reference data"],
        summary="List crops",
        description=(
            "Lists crops with their allowed grade codes. Ordering is restricted "
            "to the whitelisted keys and ends with an ``id`` tie-breaker."
        ),
        parameters=[ordering_parameter(("id", "name", "created_at"), "'name', 'id'")],
        responses=documented({200: CropSerializer(many=True)}),
    ),
    post=extend_schema(
        tags=["Reference data"],
        summary="Create a crop",
        description="Creates a crop and, optionally, its allowed grade codes. "
        "Moisture must satisfy ``0 <= moisture_threshold <= max_moisture <= 100``.",
        request=CropWriteSerializer,
        responses=documented({201: CropSerializer}),
    ),
)
class CropListCreate(OrderingMixin, ListCreateAPIView):
    serializer_class = CropSerializer
    ordering_fields = ("id", "name", "created_at")
    default_ordering = ("name", "id")

    def get_queryset(self):
        return self.apply_ordering(Crop.objects.prefetch_related("grades"))

    def create(self, request, *args, **kwargs):
        serializer = CropWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        crop = serializer.save()
        return Response(CropSerializer(crop).data, status=status.HTTP_201_CREATED)


class CropDetailView(GenericAPIView):
    serializer_class = CropSerializer

    def get_object(self):
        return _get_or_not_found(Crop, self.kwargs["pk"], CropNotFound, "Crop")

    @extend_schema(
        tags=["Reference data"],
        summary="Retrieve a crop",
        responses=documented({200: CropSerializer}),
    )
    def get(self, request, pk):
        return Response(CropSerializer(self.get_object()).data)

    @extend_schema(
        tags=["Reference data"],
        summary="Update a crop",
        description="Partial update. ``allowed_grades`` replaces the crop's "
        "grade set; a grade with historical price or delivery usage is never "
        "removed (``409 grade_in_use``).",
        request=CropWriteSerializer,
        responses=documented({200: CropSerializer}),
    )
    def patch(self, request, pk):
        crop = self.get_object()
        serializer = CropWriteSerializer(crop, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(CropSerializer(updated).data)


@extend_schema_view(
    get=extend_schema(
        tags=["Reference data"],
        summary="List crop grades",
        description=(
            "Lists crop grades, optionally filtered by ``?crop=``. Ordering is "
            "restricted to the whitelisted keys and ends with an ``id`` tie-breaker."
        ),
        parameters=[
            CROP_PARAM,
            ordering_parameter(("id", "code", "crop_id"), "'crop_id', 'code', 'id'"),
        ],
        responses=documented({200: CropGradeSerializer(many=True)}),
    ),
)
class CropGradeList(OrderingMixin, ListAPIView):
    serializer_class = CropGradeSerializer
    ordering_fields = ("id", "code", "crop_id")
    default_ordering = ("crop_id", "code", "id")

    def get_queryset(self):
        queryset = CropGrade.objects.select_related("crop")
        crop = self.request.query_params.get("crop")
        if crop:
            crop_id = _int(crop, "crop")
            _get_or_not_found(Crop, crop_id, CropNotFound, "Crop")
            queryset = queryset.filter(crop_id=crop_id)
        return self.apply_ordering(queryset)


# --- Prices -----------------------------------------------------------------


@extend_schema_view(
    get=extend_schema(
        tags=["Reference data"],
        summary="List price entries",
        description=(
            "Lists effective-dated price entries, optionally filtered by "
            "``?crop=`` or ``?crop_grade=``. Ordering is restricted to the "
            "whitelisted keys and ends with an ``id`` tie-breaker."
        ),
        parameters=[
            CROP_PARAM,
            CROP_GRADE_PARAM,
            ordering_parameter(
                ("id", "effective_from", "price_per_kg", "crop_grade_id"),
                "'crop_grade_id', '-effective_from', '-id'",
            ),
        ],
        responses=documented({200: PriceListEntrySerializer(many=True)}),
    ),
    post=extend_schema(
        tags=["Reference data"],
        summary="Add a price entry",
        description=(
            "Appends an effective-dated price for a grade. Prices are "
            "append-only: there is no update or delete. An existing entry for "
            "the same grade and effective date returns ``409 price_already_exists``."
        ),
        request=PriceEntryCreateSerializer,
        responses=documented({201: PriceListEntrySerializer}),
    ),
)
class PriceListCreate(OrderingMixin, ListCreateAPIView):
    serializer_class = PriceListEntrySerializer
    ordering_fields = ("id", "effective_from", "price_per_kg", "crop_grade_id")
    default_ordering = ("crop_grade_id", "-effective_from", "-id")

    def get_queryset(self):
        queryset = PriceListEntry.objects.select_related("crop_grade__crop")
        crop_grade = self.request.query_params.get("crop_grade")
        crop = self.request.query_params.get("crop")
        if crop_grade:
            queryset = queryset.filter(crop_grade_id=_int(crop_grade, "crop_grade"))
        if crop:
            queryset = queryset.filter(crop_grade__crop_id=_int(crop, "crop"))
        return self.apply_ordering(queryset)

    def create(self, request, *args, **kwargs):
        serializer = PriceEntryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = serializer.save()
        return Response(
            PriceListEntrySerializer(entry).data, status=status.HTTP_201_CREATED
        )


# --- Deliveries -------------------------------------------------------------


class DeliveryPreviewView(GenericAPIView):
    serializer_class = DeliveryWriteSerializer

    @extend_schema(
        tags=["Operations"],
        summary="Preview a delivery calculation",
        description=(
            "Calculates the full breakdown (resolved price, moisture deduction, "
            "net weight, amount) and **writes nothing**. Shares its code with "
            "delivery recording, so a preview and the delivery it precedes agree. "
            "``business_date`` is the effective IST business date the calculation "
            "used and reflects an authorised reviewer-clock override if present."
        ),
        parameters=REVIEW_CLOCK_HEADERS,
        request=DeliveryWriteSerializer,
        responses=documented({200: DeliveryPreviewSerializer}),
        examples=[DELIVERY_PREVIEW_EXAMPLE, ERROR_EXAMPLE],
    )
    def post(self, request):
        serializer = DeliveryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        preview = preview_delivery(
            farmer=data["farmer"],
            crop_grade=data["crop_grade"],
            delivered_on=data["delivered_on"],
            gross_weight_kg=data["gross_weight_kg"],
            moisture_percent=data["moisture_percent"],
        )
        return Response(DeliveryPreviewSerializer(preview).data)


@extend_schema_view(
    get=extend_schema(
        tags=["Operations"],
        summary="List deliveries and correction notes",
        description=(
            "Lists deliveries and correction notes, optionally filtered by "
            "``?farmer=``, ``?kind=`` (PROCUREMENT/CREDIT_NOTE/DEBIT_NOTE), "
            "``?payout=`` and an inclusive ``?from=``/``?to=`` window on the "
            "accounting date. Ordering ends with an ``id`` tie-breaker."
        ),
        parameters=[
            FARMER_PARAM,
            DELIVERY_KIND_PARAM,
            PAYOUT_PARAM,
            FROM_PARAM,
            TO_PARAM,
            ordering_parameter(
                ("id", "accounting_date", "delivered_on", "amount"),
                "'-accounting_date', '-id'",
            ),
        ],
        responses=documented({200: DeliveryReadSerializer(many=True)}),
    ),
    post=extend_schema(
        tags=["Operations"],
        summary="Record a delivery",
        description=(
            "Records an immutable PROCUREMENT delivery with a frozen breakdown. "
            "The server resolves the price and recomputes every derived value; "
            "supplying a computed field returns ``400 protected_field``. A "
            "future ``delivered_on`` is rejected against the current business date."
        ),
        parameters=REVIEW_CLOCK_HEADERS,
        request=DeliveryWriteSerializer,
        responses=documented({201: DeliveryReadSerializer}),
    ),
)
class DeliveryListCreate(OrderingMixin, ListCreateAPIView):
    serializer_class = DeliveryReadSerializer
    ordering_fields = ("id", "accounting_date", "delivered_on", "amount")
    default_ordering = ("-accounting_date", "-id")

    def get_queryset(self):
        queryset = Delivery.objects.select_related("farmer", "crop_grade", "payout")
        params = self.request.query_params
        farmer = params.get("farmer")
        kind = params.get("kind")
        payout = params.get("payout")
        if farmer:
            queryset = queryset.filter(farmer_id=_int(farmer, "farmer"))
        if kind:
            if kind not in DeliveryKind.values:
                raise DRFValidationError(
                    {"kind": [{"code": "invalid", "message": "Unknown kind."}]}
                )
            queryset = queryset.filter(kind=kind)
        if payout:
            queryset = queryset.filter(payout_id=_int(payout, "payout"))
        since, until = date_range(params)
        if since is not None:
            queryset = queryset.filter(accounting_date__gte=since)
        if until is not None:
            queryset = queryset.filter(accounting_date__lte=until)
        return self.apply_ordering(queryset)

    def create(self, request, *args, **kwargs):
        serializer = DeliveryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = serializer.save()
        return Response(
            DeliveryReadSerializer(delivery).data, status=status.HTTP_201_CREATED
        )


class DeliveryDetailView(GenericAPIView):
    serializer_class = DeliveryReadSerializer

    def _resolve(self, pk):
        try:
            return Delivery.objects.get(pk=pk)
        except (Delivery.DoesNotExist, ValueError, TypeError) as exc:
            raise NotFound(f"Delivery {pk} was not found.") from exc

    @extend_schema(
        tags=["Operations"],
        summary="Retrieve a delivery",
        responses=documented({200: DeliveryReadSerializer}),
    )
    def get(self, request, pk):
        return Response(DeliveryReadSerializer(self._resolve(pk)).data)

    @extend_schema(
        tags=["Operations"],
        summary="Edit a delivery before its payout is finalised",
        description=(
            "Re-runs the calculation from the raw measurements inside the lock. "
            "Only ``delivered_on``, ``crop_grade``, ``gross_weight_kg`` and "
            "``moisture_percent`` are editable. A delivery in a finalised or paid "
            "payout is immutable (``409 payout_state_error``); a correction note "
            "is not editable (``409 not_editable``)."
        ),
        parameters=REVIEW_CLOCK_HEADERS,
        request=DeliveryEditSerializer,
        responses=documented({200: DeliveryReadSerializer}),
    )
    def patch(self, request, pk):
        delivery = self._resolve(pk)
        serializer = DeliveryEditSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.update(delivery, serializer.validated_data)
        return Response(DeliveryReadSerializer(updated).data)


# --- Advances ---------------------------------------------------------------


class DeliveryCorrectionsView(GenericAPIView):
    serializer_class = DeliveryCorrectionCreateSerializer

    @extend_schema(
        tags=["Operations"],
        summary="Correct a delivery (credit or debit note)",
        description=(
            "Records a correction against the delivery named in the path. The "
            "original is resolved from persisted data, so a client-supplied "
            "``original_delivery``, ``farmer`` or computed field is refused. The "
            "note is stamped with the IST business date on which it is recorded "
            "and joins a draft payout for that week, or needs a supplementary "
            "payout if the week is already settled."
        ),
        parameters=REVIEW_CLOCK_HEADERS,
        request=DeliveryCorrectionCreateSerializer,
        responses=documented({201: CorrectionReadSerializer}),
        examples=[CORRECTION_EXAMPLE, ERROR_EXAMPLE],
    )
    def post(self, request, pk):
        serializer = DeliveryCorrectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        correction = record_correction(
            Delivery(pk=pk), data["kind"], data["magnitude"], data["reason"]
        )
        return Response(
            CorrectionReadSerializer(correction).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    get=extend_schema(
        tags=["Operations"],
        summary="List advances",
        description=(
            "Lists advances, optionally filtered by ``?farmer=`` and an inclusive "
            "``?from=``/``?to=`` window on the given date. Ordering ends with an "
            "``id`` tie-breaker."
        ),
        parameters=[
            FARMER_PARAM,
            FROM_PARAM,
            TO_PARAM,
            ordering_parameter(
                ("id", "given_on", "amount", "created_at"), "'-given_on', '-id'"
            ),
        ],
        responses=documented({200: AdvanceSerializer(many=True)}),
    ),
    post=extend_schema(
        tags=["Operations"],
        summary="Post an advance",
        description=(
            "Records an advance against a farmer and increases their "
            "``outstanding_advance`` balance. The balance is server-owned: "
            "supplying it returns ``400 protected_field``. Two advances on the "
            "same day are allowed."
        ),
        request=AdvanceCreateSerializer,
        responses=documented({201: AdvanceSerializer}),
    ),
)
class AdvanceListCreate(OrderingMixin, ListCreateAPIView):
    serializer_class = AdvanceSerializer
    ordering_fields = ("id", "given_on", "amount", "created_at")
    default_ordering = ("-given_on", "-id")

    def get_queryset(self):
        queryset = Advance.objects.select_related("farmer")
        params = self.request.query_params
        farmer = params.get("farmer")
        if farmer:
            queryset = queryset.filter(farmer_id=_int(farmer, "farmer"))
        since, until = date_range(params)
        if since is not None:
            queryset = queryset.filter(given_on__gte=since)
        if until is not None:
            queryset = queryset.filter(given_on__lte=until)
        return self.apply_ordering(queryset)

    def create(self, request, *args, **kwargs):
        serializer = AdvanceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        advance = serializer.save()
        return Response(AdvanceSerializer(advance).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(
        tags=["Operations"],
        summary="Retrieve an advance",
        responses=documented({200: AdvanceSerializer}),
    ),
)
class AdvanceDetail(RetrieveAPIView):
    serializer_class = AdvanceSerializer

    def get_object(self):
        try:
            return Advance.objects.get(pk=self.kwargs["pk"])
        except (Advance.DoesNotExist, ValueError, TypeError) as exc:
            raise NotFound(f"Advance {self.kwargs['pk']} was not found.") from exc


@extend_schema_view(
    get=extend_schema(
        tags=["Operations"],
        summary="Advance reconciliation for a farmer",
        description="Read-only check that the stored ``outstanding_advance`` "
        "equals advances less recoveries; ``is_reconciled`` reports agreement.",
        responses=documented({200: AdvanceReconciliationSerializer}),
    ),
)
class AdvanceReconciliationView(RetrieveAPIView):
    serializer_class = AdvanceReconciliationSerializer

    def get_object(self):
        farmer = _get_or_not_found(Farmer, self.kwargs["pk"], FarmerNotFound, "Farmer")
        return reconcile_outstanding(farmer)


# --- Corrections (credit / debit notes) -------------------------------------


@extend_schema_view(
    get=extend_schema(
        tags=["Operations"],
        summary="List correction notes",
        description=(
            "Lists credit and debit notes, optionally filtered by ``?farmer=``, "
            "``?kind=`` (CREDIT_NOTE/DEBIT_NOTE), ``?original_delivery=`` and an "
            "inclusive ``?from=``/``?to=`` window on the accounting date. "
            "Ordering ends with an ``id`` tie-breaker."
        ),
        parameters=[
            FARMER_PARAM,
            CORRECTION_KIND_PARAM,
            ORIGINAL_PARAM,
            FROM_PARAM,
            TO_PARAM,
            ordering_parameter(
                ("id", "accounting_date", "delivered_on", "amount"),
                "'-accounting_date', '-id'",
            ),
        ],
        responses=documented({200: CorrectionReadSerializer(many=True)}),
    ),
    post=extend_schema(
        tags=["Operations"],
        summary="Record a correction note",
        description=(
            "Records a CREDIT_NOTE or DEBIT_NOTE against an existing delivery. "
            "The original must be settled (attached to a finalised/paid payout); "
            "otherwise ``409 original_not_settled``. The note is stamped with the "
            "current IST business date, so an authorised reviewer-clock override "
            "changes which week it targets."
        ),
        parameters=REVIEW_CLOCK_HEADERS,
        request=CorrectionCreateSerializer,
        responses=documented({201: CorrectionReadSerializer}),
    ),
)
class CorrectionListCreate(OrderingMixin, ListCreateAPIView):
    serializer_class = CorrectionReadSerializer
    ordering_fields = ("id", "accounting_date", "delivered_on", "amount")
    default_ordering = ("-accounting_date", "-id")

    def get_queryset(self):
        queryset = Delivery.objects.filter(kind__in=GRADE_NOTE_KINDS).select_related(
            "farmer", "original_delivery", "payout"
        )
        params = self.request.query_params
        farmer = params.get("farmer")
        kind = params.get("kind")
        original = params.get("original_delivery")
        if farmer:
            queryset = queryset.filter(farmer_id=_int(farmer, "farmer"))
        if kind:
            if kind not in GRADE_NOTE_KINDS:
                raise DRFValidationError(
                    {"kind": [{"code": "invalid", "message": "Unknown kind."}]}
                )
            queryset = queryset.filter(kind=kind)
        if original:
            queryset = queryset.filter(
                original_delivery_id=_int(original, "original_delivery")
            )
        since, until = date_range(params)
        if since is not None:
            queryset = queryset.filter(accounting_date__gte=since)
        if until is not None:
            queryset = queryset.filter(accounting_date__lte=until)
        return self.apply_ordering(queryset)

    def create(self, request, *args, **kwargs):
        serializer = CorrectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correction = serializer.save()
        return Response(
            CorrectionReadSerializer(correction).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    get=extend_schema(
        tags=["Operations"],
        summary="Retrieve a correction note",
        responses=documented({200: CorrectionReadSerializer}),
    ),
)
class CorrectionDetail(RetrieveAPIView):
    serializer_class = CorrectionReadSerializer

    def get_object(self):
        try:
            return Delivery.objects.get(pk=self.kwargs["pk"], kind__in=GRADE_NOTE_KINDS)
        except (Delivery.DoesNotExist, ValueError, TypeError) as exc:
            raise NotFound(f"Correction {self.kwargs['pk']} was not found.") from exc


# --- Payouts ----------------------------------------------------------------


def _resolve_payout(pk):
    try:
        return (
            Payout.objects.select_related("farmer")
            .prefetch_related("deliveries")
            .get(pk=pk)
        )
    except (Payout.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFound(f"Payout {pk} was not found.") from exc


class PayoutGenerateView(GenericAPIView):
    serializer_class = PayoutGenerateSerializer

    @extend_schema(
        tags=["Payouts"],
        summary="Generate a weekly payout draft",
        description=(
            "Builds or extends the DRAFT payout for the Monday-based week "
            "containing ``week_start``. Returns ``201`` with the statement, or "
            '``200`` with ``{"payout": null, "reason": '
            '"NO_ELIGIBLE_DELIVERIES"}`` when the week has no eligible '
            "deliveries -- a successful no-op, no payout is invented. "
            "Re-generating an existing draft is idempotent; a finalised/paid "
            "week returns ``409 payout_state_error``."
        ),
        request=PayoutGenerateSerializer,
        responses=documented(
            {201: PayoutGenerationSerializer, 200: PayoutGenerationSerializer}
        ),
        examples=[PAYOUT_GENERATE_CREATED_EXAMPLE, PAYOUT_GENERATE_EMPTY_EXAMPLE],
    )
    def post(self, request):
        serializer = PayoutGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payout = build_weekly_payout(data["farmer"], data["week_start"])
        if payout is None:
            return Response(
                {"payout": None, "reason": NO_ELIGIBLE_DELIVERIES},
                status=status.HTTP_200_OK,
            )
        return Response(
            {"payout": PayoutSerializer(payout).data, "reason": None},
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    get=extend_schema(
        tags=["Payouts"],
        summary="List payouts",
        description=(
            "Lists payout statements, optionally filtered by ``?farmer=``, "
            "``?status=`` (DRAFT/FINALISED/PAID), ``?week=`` (the Monday-based "
            "week containing the given date, matched to ``week_start``) and an "
            "inclusive ``?from=``/``?to=`` window on ``week_start``. Ordering ends "
            "with an ``id`` tie-breaker."
        ),
        parameters=[
            FARMER_PARAM,
            STATUS_PARAM,
            WEEK_PARAM,
            FROM_PARAM,
            TO_PARAM,
            ordering_parameter(
                ("id", "week_start", "status", "net_amount"),
                "'-week_start', '-id'",
            ),
        ],
        responses=documented({200: PayoutSerializer(many=True)}),
    ),
)
class PayoutList(OrderingMixin, ListAPIView):
    serializer_class = PayoutSerializer
    ordering_fields = ("id", "week_start", "status", "net_amount")
    default_ordering = ("-week_start", "-id")

    def get_queryset(self):
        queryset = Payout.objects.select_related("farmer").prefetch_related(
            "deliveries"
        )
        params = self.request.query_params
        farmer = params.get("farmer")
        payout_status = params.get("status")
        week = params.get("week")
        if farmer:
            queryset = queryset.filter(farmer_id=_int(farmer, "farmer"))
        if payout_status:
            if payout_status not in PayoutStatus.values:
                raise DRFValidationError(
                    {"status": [{"code": "invalid", "message": "Unknown status."}]}
                )
            queryset = queryset.filter(status=payout_status)
        if week:
            monday, _sunday = week_bounds(_date(week, "week"))
            queryset = queryset.filter(week_start=monday)
        since, until = date_range(params)
        if since is not None:
            queryset = queryset.filter(week_start__gte=since)
        if until is not None:
            queryset = queryset.filter(week_start__lte=until)
        return self.apply_ordering(queryset)


@extend_schema_view(
    get=extend_schema(
        tags=["Payouts"],
        summary="Retrieve a payout statement",
        responses=documented({200: PayoutSerializer}),
    ),
)
class PayoutDetail(RetrieveAPIView):
    serializer_class = PayoutSerializer

    def get_object(self):
        return _resolve_payout(self.kwargs["pk"])


class PayoutFinaliseView(GenericAPIView):
    serializer_class = PayoutSerializer

    @extend_schema(
        tags=["Payouts"],
        summary="Finalise a draft payout",
        description=(
            "Freezes the draft statement and applies advance recovery. One-way: "
            "only a DRAFT can be finalised; repeating it or finalising a paid "
            "statement returns ``409 payout_state_error``. A finalised statement "
            "is immutable and cannot be regenerated or edited."
        ),
        request=None,
        responses=documented({200: PayoutSerializer}),
        examples=[PAYOUT_FINALISED_EXAMPLE],
    )
    def post(self, request, pk):
        payout = finalise_payout(_resolve_payout(pk))
        return Response(PayoutSerializer(payout).data)


class PayoutMarkPaidView(GenericAPIView):
    serializer_class = PayoutSerializer

    @extend_schema(
        tags=["Payouts"],
        summary="Mark a finalised payout as paid",
        description=(
            "Records payment of a FINALISED payout. One-way: only a FINALISED "
            "payout can be marked paid; marking a draft or repeating the call "
            "returns ``409 payout_state_error``."
        ),
        request=None,
        responses=documented({200: PayoutSerializer}),
        examples=[PAYOUT_FINALISED_EXAMPLE],
    )
    def post(self, request, pk):
        payout = mark_payout_paid(_resolve_payout(pk))
        return Response(PayoutSerializer(payout).data)
