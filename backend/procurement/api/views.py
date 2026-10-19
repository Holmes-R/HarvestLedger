"""M3 API views.

Each view resolves request references, calls exactly one service function and
renders the result. No business calculation, transaction or row lock lives here.
Path/body reference lookups are request-level resolution, not domain rules.
"""

from collections import OrderedDict

from django.db.models import Q
from django.http import JsonResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
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


def health(request):
    """Liveness probe; no database access, no sensitive detail."""
    return JsonResponse({"status": "ok"})


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
        return _get_or_not_found(
            Farmer, self.kwargs["pk"], FarmerNotFound, "Farmer"
        )

    @extend_schema(responses=FarmerSerializer)
    def get(self, request, pk):
        return Response(FarmerSerializer(self.get_object()).data)

    @extend_schema(request=FarmerSerializer, responses=FarmerSerializer)
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
        parameters=[
            OpenApiParameter(
                "from",
                type=str,
                description="ISO date; inclusive lower bound on the event date.",
            ),
            OpenApiParameter(
                "to",
                type=str,
                description="ISO date; inclusive upper bound on the event date.",
            ),
            OpenApiParameter(
                "event_type",
                type=str,
                description="DELIVERY, CORRECTION, ADVANCE or PAYOUT.",
            ),
            OpenApiParameter(
                "ordering",
                type=str,
                description=(
                    "One of: amount, date, event_type, id "
                    "(prefix '-' to reverse)."
                ),
            ),
        ],
        responses=LedgerPageSerializer,
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


class CropListCreate(OrderingMixin, ListCreateAPIView):
    serializer_class = CropSerializer
    ordering_fields = ("id", "name", "created_at")
    default_ordering = ("name", "id")

    def get_queryset(self):
        return self.apply_ordering(Crop.objects.prefetch_related("grades"))

    @extend_schema(request=CropWriteSerializer, responses=CropSerializer)
    def create(self, request, *args, **kwargs):
        serializer = CropWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        crop = serializer.save()
        return Response(CropSerializer(crop).data, status=status.HTTP_201_CREATED)


class CropDetailView(GenericAPIView):
    serializer_class = CropSerializer

    def get_object(self):
        return _get_or_not_found(Crop, self.kwargs["pk"], CropNotFound, "Crop")

    @extend_schema(responses=CropSerializer)
    def get(self, request, pk):
        return Response(CropSerializer(self.get_object()).data)

    @extend_schema(request=CropWriteSerializer, responses=CropSerializer)
    def patch(self, request, pk):
        crop = self.get_object()
        serializer = CropWriteSerializer(crop, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(CropSerializer(updated).data)


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

    @extend_schema(request=DeliveryWriteSerializer, responses=DeliveryPreviewSerializer)
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


class DeliveryListCreate(OrderingMixin, ListCreateAPIView):
    serializer_class = DeliveryReadSerializer
    ordering_fields = ("id", "accounting_date", "delivered_on", "amount")
    default_ordering = ("-accounting_date", "-id")

    def get_queryset(self):
        queryset = Delivery.objects.select_related(
            "farmer", "crop_grade", "payout"
        )
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

    @extend_schema(request=DeliveryWriteSerializer, responses=DeliveryReadSerializer)
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

    @extend_schema(responses=DeliveryReadSerializer)
    def get(self, request, pk):
        return Response(DeliveryReadSerializer(self._resolve(pk)).data)

    @extend_schema(request=DeliveryEditSerializer, responses=DeliveryReadSerializer)
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
        request=DeliveryCorrectionCreateSerializer,
        responses=CorrectionReadSerializer,
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

    @extend_schema(request=AdvanceCreateSerializer, responses=AdvanceSerializer)
    def create(self, request, *args, **kwargs):
        serializer = AdvanceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        advance = serializer.save()
        return Response(
            AdvanceSerializer(advance).data, status=status.HTTP_201_CREATED
        )


class AdvanceDetail(RetrieveAPIView):
    serializer_class = AdvanceSerializer

    def get_object(self):
        try:
            return Advance.objects.get(pk=self.kwargs["pk"])
        except (Advance.DoesNotExist, ValueError, TypeError) as exc:
            raise NotFound(f"Advance {self.kwargs['pk']} was not found.") from exc


class AdvanceReconciliationView(RetrieveAPIView):
    serializer_class = AdvanceReconciliationSerializer

    def get_object(self):
        farmer = _get_or_not_found(
            Farmer, self.kwargs["pk"], FarmerNotFound, "Farmer"
        )
        return reconcile_outstanding(farmer)


# --- Corrections (credit / debit notes) -------------------------------------


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

    @extend_schema(
        request=CorrectionCreateSerializer, responses=CorrectionReadSerializer
    )
    def create(self, request, *args, **kwargs):
        serializer = CorrectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correction = serializer.save()
        return Response(
            CorrectionReadSerializer(correction).data,
            status=status.HTTP_201_CREATED,
        )


class CorrectionDetail(RetrieveAPIView):
    serializer_class = CorrectionReadSerializer

    def get_object(self):
        try:
            return Delivery.objects.get(
                pk=self.kwargs["pk"], kind__in=GRADE_NOTE_KINDS
            )
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
        request=PayoutGenerateSerializer, responses=PayoutGenerationSerializer
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


class PayoutDetail(RetrieveAPIView):
    serializer_class = PayoutSerializer

    def get_object(self):
        return _resolve_payout(self.kwargs["pk"])


class PayoutFinaliseView(GenericAPIView):
    serializer_class = PayoutSerializer

    @extend_schema(request=None, responses=PayoutSerializer)
    def post(self, request, pk):
        payout = finalise_payout(_resolve_payout(pk))
        return Response(PayoutSerializer(payout).data)


class PayoutMarkPaidView(GenericAPIView):
    serializer_class = PayoutSerializer

    @extend_schema(request=None, responses=PayoutSerializer)
    def post(self, request, pk):
        payout = mark_payout_paid(_resolve_payout(pk))
        return Response(PayoutSerializer(payout).data)
