# Patient Portal Membership

Run patient memberships and recurring billing inside Canvas - sign-up, card updates, retries, and cancellation - all driven from the patient portal, with no separate billing tool to reconcile.

## The problem

Membership-based practices - direct primary care, concierge, weight management, behavioral health - need to charge a recurring fee that lives inside the patient's chart and portal, not in a separate tool staff reconcile by hand. Without that, practices run subscriptions in a third-party dashboard, manually flag membership status on each chart, chase declined cards over email, and handle signups and cancellations by phone.

## What it does

Collapses the whole membership workflow into Canvas and the patient portal:

- Patients self-serve enrollment, plan management, card updates, and cancellation from the portal
- Providers see membership status on the chart banner at the point of care
- Staff get a read-only directory of all members in the provider menu
- A daily billing job handles recurring charges, automatic retries on failure, auto-cancellation, and the staff off-boarding task - without anyone leaving Canvas

## Who it's for

Practices that bill patients on a recurring cadence and want that workflow inside Canvas:

- Direct primary care - monthly or annual fees in lieu of fee-for-service
- Concierge primary care - annual retainers with portal-driven enrollment
- Membership-based specialty practices - weight management, hormone replacement, behavioral health, longevity
- Cash-pay or hybrid practices running a paid membership tier alongside insurance

## Good to know

- Membership tiers, pricing, and discount codes are configurable.
- Failed charges retry automatically, with auto-cancellation and a staff task after repeated failures.
- The staff directory is read-only by design - patients manage their own memberships from the portal.
