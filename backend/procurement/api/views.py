"""M3 API views.

Each view resolves request references, calls exactly one service function and
renders the result. No business calculation, transaction or row lock lives here.
Path/body reference lookups are request-level resolution, not domain rules.
"""

from django.db.models import Q
from django.http import JsonResponse
from django.utils.dateparse import parse_date
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
from procurement.services.delivery import preview_delivery
from procurement.services.errors import CropNotFound, FarmerNotFound
from procurement.services.ledger import build_farmer_ledger
from procurement.services.payouts import finalise_payout, mark_payout_paid

from .serializers import (
    AdvanceCreateSerializer,
    AdvanceReconciliationSerializer,
    AdvanceSerializer,
    CorrectionCreateSerializer,
    CorrectionReadSerializer,
    CropGradeSerializer,
    CropSerializer,
    CropWriteSerializer,
    DeliveryEditSerializer,
    DeliveryPreviewSerializer,
    DeliveryReadSerializer,
    DeliveryWriteSerializer,
    FarmerLedgerSerializer,
    FarmerSerializer,
    PayoutGenerateSerializer,
    PayoutSerializer,
    PriceEntryCreateSerializer,
    PriceListEntrySerializer,
)


def health(request):
    """Liveness probe; no database access, no sensitive detail."""
    return JsonResponse({"status": "ok"})


def _get_or_not_found(model, pk, error_cls, label):
    try:
        return model.objects.get(pk=pk)
    except (model.DoesNotExist, ValueError, TypeError) as exc:
        raise error_cls(f"{label} {pk} was not found.") from exc


def _int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DRFValidationError(
            {name: [{"code": "invalid", "message": "A valid integer is required."}]}
        ) from exc


def _date(value, name):
    parsed = parse_date(value)
    if parsed is None:
        raise DRFValidationError(
            {
                name: [
                    {
                        "code": "invalid",
                        "message": "A valid date (YYYY-MM-DD) is required.",
                    }
                ]
            }
        )
    return parsed


# --- Farmers ----------------------------------------------------------------


class FarmerListCreate(ListCreateAPIView):
    serializer_class = FarmerSerializer

    def get_queryset(self):
        queryset = Farmer.objects.all().order_by("id")
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(phone__icontains=search)
                | Q(village__icontains=search)
            )
        return queryset


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


class FarmerLedgerView(RetrieveAPIView):
    serializer_class = FarmerLedgerSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "from",
                type=str,
                description="ISO date; lower bound on accounting date (inclusive).",
            ),
            OpenApiParameter(
                "to",
                type=str,
                description="ISO date; upper bound on accounting date (inclusive).",
            ),
        ],
        responses=FarmerLedgerSerializer,
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_object(self):
        farmer = _get_or_not_found(
            Farmer, self.kwargs["pk"], FarmerNotFound, "Farmer"
        )
        params = self.request.query_params
        since = _date(params["from"], "from") if "from" in params else None
        until = _date(params["to"], "to") if "to" in params else None
        if since is not None and until is not None and since > until:
            raise DRFValidationError(
                {
                    "from": [
                        {
                            "code": "invalid",
                            "message": "'from' must not be after 'to'.",
                        }
                    ]
                }
            )
        return build_farmer_ledger(farmer, since=since, until=until)


# --- Crops and grades -------------------------------------------------------


class CropListCreate(ListCreateAPIView):
    serializer_class = CropSerializer

    def get_queryset(self):
        return Crop.objects.prefetch_related("grades").order_by("name")

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


class CropGradeList(ListAPIView):
    serializer_class = CropGradeSerializer

    def get_queryset(self):
        queryset = CropGrade.objects.select_related("crop").order_by("crop_id", "code")
        crop = self.request.query_params.get("crop")
        if crop:
            crop_id = _int(crop, "crop")
            _get_or_not_found(Crop, crop_id, CropNotFound, "Crop")
            queryset = queryset.filter(crop_id=crop_id)
        return queryset


# --- Prices -----------------------------------------------------------------


class PriceListCreate(ListCreateAPIView):
    serializer_class = PriceListEntrySerializer

    def get_queryset(self):
        queryset = PriceListEntry.objects.select_related("crop_grade__crop").order_by(
            "crop_grade_id", "-effective_from", "-pk"
        )
        crop_grade = self.request.query_params.get("crop_grade")
        crop = self.request.query_params.get("crop")
        if crop_grade:
            queryset = queryset.filter(crop_grade_id=_int(crop_grade, "crop_grade"))
        if crop:
            queryset = queryset.filter(crop_grade__crop_id=_int(crop, "crop"))
        return queryset

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


class DeliveryListCreate(ListCreateAPIView):
    serializer_class = DeliveryReadSerializer

    def get_queryset(self):
        queryset = Delivery.objects.select_related(
            "farmer", "crop_grade", "payout"
        ).order_by("-accounting_date", "-pk")
        params = self.request.query_params
        farmer = params.get("farmer")
        kind = params.get("kind")
        payout = params.get("payout")
        start = params.get("from")
        end = params.get("to")
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
        if start:
            queryset = queryset.filter(accounting_date__gte=_date(start, "from"))
        if end:
            queryset = queryset.filter(accounting_date__lte=_date(end, "to"))
        return queryset

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


class AdvanceListCreate(ListCreateAPIView):
    serializer_class = AdvanceSerializer

    def get_queryset(self):
        queryset = Advance.objects.select_related("farmer").order_by(
            "-given_on", "-pk"
        )
        farmer = self.request.query_params.get("farmer")
        if farmer:
            queryset = queryset.filter(farmer_id=_int(farmer, "farmer"))
        return queryset

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


class CorrectionListCreate(ListCreateAPIView):
    serializer_class = CorrectionReadSerializer

    def get_queryset(self):
        queryset = Delivery.objects.filter(kind__in=GRADE_NOTE_KINDS).select_related(
            "farmer", "original_delivery", "payout"
        ).order_by("-accounting_date", "-pk")
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
        return queryset

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
        return Payout.objects.get(pk=pk)
    except (Payout.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFound(f"Payout {pk} was not found.") from exc


class PayoutGenerateView(GenericAPIView):
    serializer_class = PayoutGenerateSerializer

    @extend_schema(request=PayoutGenerateSerializer, responses=PayoutSerializer)
    def post(self, request):
        serializer = PayoutGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payout = serializer.save()
        return Response(PayoutSerializer(payout).data, status=status.HTTP_201_CREATED)


class PayoutList(ListAPIView):
    serializer_class = PayoutSerializer

    def get_queryset(self):
        queryset = Payout.objects.select_related("farmer").order_by(
            "-week_start", "-pk"
        )
        params = self.request.query_params
        farmer = params.get("farmer")
        payout_status = params.get("status")
        start = params.get("from")
        end = params.get("to")
        if farmer:
            queryset = queryset.filter(farmer_id=_int(farmer, "farmer"))
        if payout_status:
            if payout_status not in PayoutStatus.values:
                raise DRFValidationError(
                    {"status": [{"code": "invalid", "message": "Unknown status."}]}
                )
            queryset = queryset.filter(status=payout_status)
        if start:
            queryset = queryset.filter(week_start__gte=_date(start, "from"))
        if end:
            queryset = queryset.filter(week_start__lte=_date(end, "to"))
        return queryset


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
