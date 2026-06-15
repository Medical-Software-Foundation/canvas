![Canvas Bridge Integration](https://images.prismic.io/canvas-website/Z2SdppbqstJ98tCr_bridge_logo_200px.png?auto=format,compress)

# Bridge Integration for Telehealth Clinics

## Problem it solves

Clinics running on both Canvas and Bridge would otherwise re-enter each patient in Bridge by hand and toggle between two systems to find the same person's record. This plugin keeps the patient list in sync automatically and adds a banner link from the Canvas chart straight to the matching Bridge record, so staff stop double-entering patients and stop hunting across tools.

## How to install

```
canvas install bridge
```

Requires the Bridge connection secrets to be set before it can sync (see Configuration options).

## Configuration options

Set these as plugin secrets after install:

- `BRIDGE_SECRET_API_KEY` - API key for the Bridge account, sent on every request.
- `BRIDGE_API_BASE_URL` - base URL for the Bridge API. Falls back to the Bridge sandbox when unset.
- `BRIDGE_UI_BASE_URL` - base URL used to build the patient link shown in the Canvas banner. Falls back to the Bridge sandbox when unset.
- `CANVAS_BASE_URL` - the instance URL, stored on the Bridge patient record as metadata.

### Canvas + Bridge

-   The Canvas + Bridge integration extension automatically syncs your patients from Canvas to Bridge whenever a patient is created or updated.
-   From the UI, you can easily navigate from your patient in Canvas to your patient's record in Bridge.

### Implementation requirements

-   All you need is a Bridge account and an associated API key.
-   [Contact Bridge](https://www.usebridge.com/contact) to set one up.

### About Bridge

Bridge is a modern provider enablement platform that helps providers seamlessly expand access to patients who need care through a plug-and-play insurance platform.

1. **Shared Admin & Tech Resources Backed by 20+ Years of Experience**

    Streamline billing, compliance, credentialing, and telehealth workflows with guidance from an expert leadership team, allowing providers to focus on patient care.

2. **Contracting & Nationwide Coverage**

    Gain collective bargaining power with health plans and leverage contracts designed for diverse specialties, enabling clinics to accept insurance from members across all 50 states.

3. **Faster Go-Live & Scalable Growth**

    Reduce overhead costs and administrative burdens, enabling clinics to ramp up services more quickly and expand patient access with end-to-end support.
