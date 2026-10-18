"""Business-rule services (M2).

Financial logic lives here, never in views, serializers or model signals.

Concurrency contract
--------------------
Every financial write runs inside ``transaction.atomic()`` and takes PostgreSQL
row locks with ``select_for_update()`` in a single consistent order:

1. the ``Farmer`` row,
2. the ``Payout`` row (when one is involved),
3. the ``Delivery`` rows ordered by primary key.

Locking is always done through :mod:`procurement.services.locking`, so the order
cannot drift between callers. The guarantee is the database row lock -- never a
process-local ``threading``/``asyncio`` lock.

Structure
---------
* :mod:`procurement.services.money` and the pure helpers in
  :mod:`procurement.services.delivery` hold calculation logic and touch no
  database.
* :mod:`procurement.services.pricing`, :mod:`procurement.services.delivery`,
  :mod:`procurement.services.advances`, :mod:`procurement.services.payouts` and
  :mod:`procurement.services.corrections` orchestrate persistence and locking.
"""
