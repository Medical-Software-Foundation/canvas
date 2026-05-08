"""Per-patient membership record.

One row per patient. Replaces the ``membership:<patient_id>`` cache entry.
"""
from django.db.models import (
    DO_NOTHING,
    DateField,
    DateTimeField,
    IntegerField,
    OneToOneField,
    TextField,
)

from canvas_sdk.v1.data.base import CustomModel
from portal_membership.models.proxy import PatientProxy


class Membership(CustomModel):
    """Membership state for a single patient."""

    patient = OneToOneField(
        PatientProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__membership",
    )

    # Plan / status
    plan = TextField()
    plan_name = TextField()
    status = TextField()  # "active" | "cancelled"

    # Stripe
    stripe_customer_id = TextField()
    payment_method_id = TextField(default="")

    # Billing
    amount_cents = IntegerField()
    currency = TextField(default="usd")
    cadence = TextField(default="monthly")  # daily | weekly | monthly | quarterly | annually
    billing_day = IntegerField()
    next_billing_date = DateField()
    retry_date = DateField(null=True, blank=True)
    consecutive_failures = IntegerField(default=0)

    # Discount (empty / zero when no active discount).
    # discount_cycles_remaining counts billing cycles, not months — the cycle
    # length is determined by the plan's cadence.
    discount_code = TextField(default="")
    discount_type = TextField(default="")
    discount_value = IntegerField(default=0)
    discount_cycles_remaining = IntegerField(default=0)

    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
