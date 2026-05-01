"""Per-patient membership record.

One row per patient. Replaces the ``membership:<patient_id>`` cache entry.
"""
from django.db.models import (
    DateField,
    DateTimeField,
    IntegerField,
    TextField,
    UniqueConstraint,
)

from canvas_sdk.v1.data.base import CustomModel


class Membership(CustomModel):
    """Membership state for a single patient."""

    patient_id = TextField(db_index=True)

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

    class Meta:
        constraints = [
            UniqueConstraint(fields=["patient_id"], name="uq_membership_patient"),
        ]
