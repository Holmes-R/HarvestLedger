"""URL routes for the M3 API, mounted under ``/api/v1/``."""

from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("farmers/", views.FarmerListCreate.as_view(), name="farmer-list"),
    path(
        "farmers/<int:pk>/",
        views.FarmerDetailView.as_view(),
        name="farmer-detail",
    ),
    path(
        "farmers/<int:pk>/ledger/",
        views.FarmerLedgerView.as_view(),
        name="farmer-ledger",
    ),
    path("crops/", views.CropListCreate.as_view(), name="crop-list"),
    path(
        "crops/<int:pk>/",
        views.CropDetailView.as_view(),
        name="crop-detail",
    ),
    path("grades/", views.CropGradeList.as_view(), name="grade-list"),
    path("price-lists/", views.PriceListCreate.as_view(), name="price-list"),
    path(
        "deliveries/preview/",
        views.DeliveryPreviewView.as_view(),
        name="delivery-preview",
    ),
    path("deliveries/", views.DeliveryListCreate.as_view(), name="delivery-list"),
    path(
        "deliveries/<int:pk>/",
        views.DeliveryDetailView.as_view(),
        name="delivery-detail",
    ),
    path(
        "deliveries/<int:pk>/corrections/",
        views.DeliveryCorrectionsView.as_view(),
        name="delivery-corrections",
    ),
    path("advances/", views.AdvanceListCreate.as_view(), name="advance-list"),
    path(
        "advances/<int:pk>/",
        views.AdvanceDetail.as_view(),
        name="advance-detail",
    ),
    path(
        "farmers/<int:pk>/advance-reconciliation/",
        views.AdvanceReconciliationView.as_view(),
        name="advance-reconciliation",
    ),
    path(
        "corrections/",
        views.CorrectionListCreate.as_view(),
        name="correction-list",
    ),
    path(
        "corrections/<int:pk>/",
        views.CorrectionDetail.as_view(),
        name="correction-detail",
    ),
    path(
        "payouts/generate/",
        views.PayoutGenerateView.as_view(),
        name="payout-generate",
    ),
    path("payouts/", views.PayoutList.as_view(), name="payout-list"),
    path("payouts/<int:pk>/", views.PayoutDetail.as_view(), name="payout-detail"),
    path(
        "payouts/<int:pk>/finalise/",
        views.PayoutFinaliseView.as_view(),
        name="payout-finalise",
    ),
    path(
        "payouts/<int:pk>/mark-paid/",
        views.PayoutMarkPaidView.as_view(),
        name="payout-mark-paid",
    ),
]
