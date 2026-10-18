"""List pagination shared by the M3 read endpoints."""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Page-number pagination: 50 per page, client may request up to 100."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100
