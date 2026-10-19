"""List pagination shared by the M3 read endpoints.

Every growing list -- including the farmer ledger's event history -- is paginated
with a bounded page size, so a client can never pull an unbounded collection or
an unbounded nested event list.
"""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Page-number pagination: 20 per page, client may request up to 100.

    A requested ``page_size`` is clamped to ``max_page_size``; a non-positive or
    unparseable value falls back to the default, so the response stays bounded.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
