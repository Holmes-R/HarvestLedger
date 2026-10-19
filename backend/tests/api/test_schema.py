"""M3: OpenAPI schema, documentation endpoints and the documented contract.

These tests pin the *documentation* contract, not the runtime behaviour: every
operation is grouped and labelled, the shared error envelope and named enums are
present, and the endpoints whose shape is easy to get wrong (delivery write
contract, ledger page, payout generation's two success outcomes, payout
transitions without a body, and the optional reviewer-clock headers) describe
exactly what the API returns.
"""

import pytest
from django.urls import reverse
from drf_spectacular.validation import validate_schema

pytestmark = pytest.mark.m3


@pytest.fixture
def schema(api_client):
    response = api_client.get(reverse("schema"), HTTP_ACCEPT="application/json")
    assert response.status_code == 200
    return response.json()


def _op(schema, path, method):
    return schema["paths"][path][method]


def _ref(op, status, part):
    return op["responses"][status]["content"]["application/json"]["schema"]["$ref"]


def _operations(schema):
    for path, methods in schema["paths"].items():
        for method, op in methods.items():
            yield method, path, op


@pytest.mark.django_db
def test_openapi_schema_is_served(api_client):
    response = api_client.get(reverse("schema"), HTTP_ACCEPT="application/json")
    assert response.status_code == 200
    assert "openapi" in response.json()


@pytest.mark.django_db
def test_swagger_ui_is_served(api_client):
    response = api_client.get(reverse("docs"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_schema_is_valid_openapi(schema):
    validate_schema(schema)


@pytest.mark.django_db
def test_every_operation_is_grouped_and_labelled(schema):
    for method, path, op in _operations(schema):
        assert op.get("tags"), (method, path)
        assert op.get("summary"), (method, path)


@pytest.mark.django_db
def test_internal_view_docstrings_never_leak(schema):
    for method, path, op in _operations(schema):
        description = op.get("description") or ""
        assert "Adds whitelisted" not in description, (method, path)


@pytest.mark.django_db
def test_all_endpoints_are_documented(schema):
    expected = {
        "/api/v1/health/": {"get"},
        "/api/v1/farmers/": {"get", "post"},
        "/api/v1/farmers/{id}/": {"get", "patch"},
        "/api/v1/farmers/{id}/ledger/": {"get"},
        "/api/v1/farmers/{id}/advance-reconciliation/": {"get"},
        "/api/v1/crops/": {"get", "post"},
        "/api/v1/crops/{id}/": {"get", "patch"},
        "/api/v1/grades/": {"get"},
        "/api/v1/price-lists/": {"get", "post"},
        "/api/v1/deliveries/preview/": {"post"},
        "/api/v1/deliveries/": {"get", "post"},
        "/api/v1/deliveries/{id}/": {"get", "patch"},
        "/api/v1/deliveries/{id}/corrections/": {"post"},
        "/api/v1/advances/": {"get", "post"},
        "/api/v1/advances/{id}/": {"get"},
        "/api/v1/corrections/": {"get", "post"},
        "/api/v1/corrections/{id}/": {"get"},
        "/api/v1/payouts/generate/": {"post"},
        "/api/v1/payouts/": {"get"},
        "/api/v1/payouts/{id}/": {"get"},
        "/api/v1/payouts/{id}/finalise/": {"post"},
        "/api/v1/payouts/{id}/mark-paid/": {"post"},
    }
    documented = {path: set(methods) for path, methods in schema["paths"].items()}
    assert documented == expected


@pytest.mark.django_db
def test_error_envelope_is_documented(schema):
    schemas = schema["components"]["schemas"]
    assert schemas["ErrorEnvelope"]["properties"]["error"]["$ref"].endswith("ErrorBody")
    assert {"code", "message", "details", "request_id"} <= set(
        schemas["ErrorBody"]["properties"]
    )
    op = _op(schema, "/api/v1/deliveries/preview/", "post")
    for status in ("400", "403", "404", "409", "422", "500"):
        assert _ref(op, status, "response").endswith("ErrorEnvelope")


@pytest.mark.django_db
def test_shared_enums_are_named_components(schema):
    schemas = schema["components"]["schemas"]
    assert schemas["DeliveryKindEnum"]["enum"] == [
        "PROCUREMENT",
        "CREDIT_NOTE",
        "DEBIT_NOTE",
    ]
    assert schemas["GradeNoteKindEnum"]["enum"] == ["CREDIT_NOTE", "DEBIT_NOTE"]
    assert schemas["PayoutStatusEnum"]["enum"] == ["DRAFT", "FINALISED", "PAID"]
    assert schemas["LedgerEventTypeEnum"]["enum"] == [
        "DELIVERY",
        "CORRECTION",
        "ADVANCE",
        "PAYOUT",
    ]


@pytest.mark.django_db
def test_delivery_write_contract_is_documented(schema):
    op = _op(schema, "/api/v1/deliveries/", "post")
    assert op["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "DeliveryWriteRequest"
    )
    assert _ref(op, "201", "response").endswith("DeliveryRead")


@pytest.mark.django_db
def test_preview_documents_calculated_business_date(schema):
    preview = schema["components"]["schemas"]["DeliveryPreview"]["properties"]
    assert "business_date" in preview
    assert "applied_price" in preview
    assert "net_kg" in preview
    op = _op(schema, "/api/v1/deliveries/preview/", "post")
    assert _ref(op, "200", "response").endswith("DeliveryPreview")


@pytest.mark.django_db
def test_reviewer_clock_headers_are_documented(schema):
    op = _op(schema, "/api/v1/deliveries/preview/", "post")
    headers = {
        param["name"] for param in op.get("parameters", []) if param["in"] == "header"
    }
    assert {"X-Test-Clock", "X-Review-Key"} <= headers


@pytest.mark.django_db
def test_payout_generation_documents_both_success_outcomes(schema):
    op = _op(schema, "/api/v1/payouts/generate/", "post")
    assert op["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "PayoutGenerateRequest"
    )
    assert _ref(op, "201", "response").endswith("PayoutGeneration")
    assert _ref(op, "200", "response").endswith("PayoutGeneration")
    empty = op["responses"]["200"]["content"]["application/json"]["examples"]
    values = [example["value"] for example in empty.values()]
    assert {"payout": None, "reason": "NO_ELIGIBLE_DELIVERIES"} in values


@pytest.mark.django_db
def test_payout_transitions_take_no_body(schema):
    for path in (
        "/api/v1/payouts/{id}/finalise/",
        "/api/v1/payouts/{id}/mark-paid/",
    ):
        op = _op(schema, path, "post")
        assert "requestBody" not in op
        assert _ref(op, "200", "response").endswith("Payout")


@pytest.mark.django_db
def test_ledger_page_contract_is_documented(schema):
    op = _op(schema, "/api/v1/farmers/{id}/ledger/", "get")
    assert _ref(op, "200", "response").endswith("LedgerPage")
    names = {param["name"] for param in op.get("parameters", [])}
    assert {"event_type", "from", "to", "ordering", "id"} <= names
    page = schema["components"]["schemas"]["LedgerPage"]
    assert {"count", "next", "previous", "summary", "results"} <= set(
        page["properties"]
    )


@pytest.mark.django_db
def test_list_endpoints_document_ordering(schema):
    for path in (
        "/api/v1/farmers/",
        "/api/v1/crops/",
        "/api/v1/grades/",
        "/api/v1/price-lists/",
        "/api/v1/deliveries/",
        "/api/v1/advances/",
        "/api/v1/corrections/",
        "/api/v1/payouts/",
    ):
        op = _op(schema, path, "get")
        ordering = [
            param for param in op.get("parameters", []) if param["name"] == "ordering"
        ]
        assert ordering, path
        assert "tie-breaker" in ordering[0]["description"]
