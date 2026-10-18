"""Row-locking helpers.

The only place ``select_for_update()`` is called, so the acquisition order stays
consistent: farmer -> payout -> deliveries (ordered by primary key). Callers must
already be inside ``transaction.atomic()``; PostgreSQL row locks are the
concurrency guarantee (never a process-local lock).
"""

from procurement.models import Delivery, Farmer, Payout


def lock_farmer(farmer_id: int) -> Farmer:
    """Lock and return the farmer row."""
    return Farmer.objects.select_for_update().get(pk=farmer_id)


def lock_payout(payout_id: int) -> Payout:
    """Lock and return the payout row."""
    return Payout.objects.select_for_update().get(pk=payout_id)


def lock_deliveries(queryset) -> list[Delivery]:
    """Lock and return ``queryset`` as a list ordered by primary key."""
    return list(queryset.select_for_update().order_by("pk"))
