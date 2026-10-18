"""Domain (business-rule) errors raised by the M2 services.

One consistent structure: every domain error derives from :class:`ServiceError`
and carries a stable :attr:`~ServiceError.code` for programmatic handling (the
future API maps codes to responses). Field/input validation keeps Django's
``ValidationError`` with an explicit ``code`` -- see the table in
``procurement/services/README.md``.

These are library exceptions, not HTTP errors. They are re-exported from the
service modules so existing tests import them from where they use them (for
example ``procurement.services.delivery.MoistureExceedsMaximum``).
"""


class ServiceError(Exception):
    """Base class for all service-layer domain errors.

    Subclasses set a stable ``code`` and a ``default_message``. Instances expose
    ``.code`` and ``.message`` and stringify to the message.
    """

    code = "service_error"
    default_message = "A business-rule violation occurred."

    def __init__(self, message: str | None = None, *, code: str | None = None):
        self.code = code or type(self).code
        self.message = message or type(self).default_message
        super().__init__(self.message)


class PriceNotFound(ServiceError):
    """No price entry is effective on or before the requested date."""

    code = "price_not_found"
    default_message = "No effective price was found for the requested date."


class GradeNotAllowed(ServiceError):
    """The grade does not exist for the requested crop ("disallowed grade")."""

    code = "grade_not_allowed"
    default_message = "The grade is not allowed for the requested crop."


class AdvanceReconciliationError(ServiceError):
    """Recorded advances and recoveries do not match the stored balance."""

    code = "advance_reconciliation_failed"
    default_message = (
        "Recorded advances and recoveries do not match the stored outstanding "
        "balance."
    )


class PriceAlreadyExists(ServiceError):
    """A price entry already exists for this grade and effective date."""

    code = "price_already_exists"
    default_message = (
        "A price entry already exists for this grade and effective date; "
        "price history is append-only."
    )


class MoistureExceedsMaximum(ServiceError):
    """Delivery moisture is above the crop's maximum accepted moisture."""

    code = "moisture_exceeds_maximum"
    default_message = "Delivery moisture exceeds the crop's maximum."


class PayoutStateError(ServiceError):
    """A payout operation was attempted from an invalid state."""

    code = "payout_state_error"
    default_message = "The payout is not in a state that allows this operation."
