"""Current Providers / Suppliers List module."""

from __future__ import annotations

from html import escape as html_escape
from typing import Any

from logger import log

from guided_awv.modules.base import AWVType, BaseModule


class CurrentProvidersModule(BaseModule):
    """
    Current Providers / Suppliers List section.

    CMS-required element: document the patient's current healthcare providers,
    specialists, pharmacies, and DME suppliers. For initial AWV this is a
    complete capture; for subsequent AWV it is a review and update.
    """

    ORDER = 5
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-user-md"

    @property
    def TITLE(self) -> str:  # type: ignore[override]
        """Return title based on AWV type."""
        if self.awv_type == AWVType.INITIAL:
            return "Current Providers & Suppliers (Complete Capture)"
        return "Current Providers & Suppliers (Review & Update)"

    PROVIDER_CATEGORIES = [
        {
            "id": "pcp",
            "label": "Primary Care Provider",
            "placeholder": "Name, practice, phone",
        },
        {
            "id": "dme_suppliers",
            "label": "DME / Medical Equipment Suppliers",
            "placeholder": "List any DME suppliers (name, equipment, phone)",
            "multiline": True,
        },
        {
            "id": "home_health",
            "label": "Home Health / Visiting Nurse Services",
            "placeholder": "Agency name, services provided, phone",
        },
        {
            "id": "other_providers",
            "label": "Other Providers (PT, OT, behavioral health, etc.)",
            "placeholder": "List any other healthcare providers",
            "multiline": True,
        },
    ]

    # Candidate key variants for the JSON shape of patient.preferred_pharmacy.
    # The schema is not fully documented in the SDK, so we accept anything common.
    _NCPDP_KEYS = ("ncpdp_id", "ncpdpId", "ncpdp", "id", "pharmacy_id")
    _NAME_KEYS = (
        "organization_name", "organizationName", "name",
        "pharmacy_name", "pharmacyName", "store_name", "display",
    )
    _ADDRESS_KEYS = ("address_line_1", "addressLine1", "address", "street", "line1")
    _CITY_KEYS = ("city",)
    _STATE_KEYS = ("state", "state_code", "stateCode")
    _ZIP_KEYS = ("zip_code", "zipCode", "zip", "postal_code", "postalCode")
    _DEFAULT_KEYS = ("default", "is_default", "isDefault", "preferred")

    @classmethod
    def _first_present(cls, d: dict[str, Any], keys: tuple[str, ...]) -> str:
        for k in keys:
            v = d.get(k)
            if v not in (None, ""):
                return str(v)
        return ""

    @classmethod
    def _read_existing_pharmacies(cls, patient_id: str) -> list[dict[str, Any]]:
        """Read the patient's preferred pharmacies and normalize to a list of dicts.

        Canvas exposes preferred-pharmacy data in two places that may diverge:
        - `patient.preferred_pharmacy` (singular JSON) - returns only the
          patient's *default* pharmacy as a single dict in practice.
        - `patient.preferred_pharmacies` (plural) - if exposed by the SDK,
          this is the full list including non-default entries.

        Live UAT on 2026-05-10 confirmed the singular field misses non-default
        entries (a CVS Specialty pharmacy added via CreatePatientPreferredPharmacies
        showed up in the patient's profile UI but not in the singular field).
        We therefore try the plural attribute first and only fall back to the
        singular one when the plural isn't available on the model. Both shapes
        are tolerated.

        - Handles None, single-dict, and list-of-dicts shapes.
        - Tries multiple common key variants for each field.
        - If only an NCPDP id is present (no display name), resolves details via
          the Canvas pharmacy_http service so the UI can show a useful label.
        - Logs the raw key set so future schema surprises are easy to spot in
          the runner logs.
        """
        if not patient_id:
            return []
        try:
            from canvas_sdk.v1.data import Patient
            patient = Patient.objects.filter(id=patient_id).first()
            if not patient:
                return []
            raw = getattr(patient, "preferred_pharmacies", None)
            source = "preferred_pharmacies"
            if raw in (None, []):
                raw = getattr(patient, "preferred_pharmacy", None)
                source = "preferred_pharmacy"
            if raw is None:
                log.info(
                    f"CurrentProvidersModule: no preferred pharmacies on patient={patient_id}"
                )
                return []
            entries = raw if isinstance(raw, list) else [raw]
            log.info(
                f"CurrentProvidersModule: preferred-pharmacy raw shape for "
                f"patient={patient_id}: source={source}, type={type(raw).__name__}, "
                f"count={len(entries)}, "
                f"entry_keys={[list(e.keys()) if isinstance(e, dict) else type(e).__name__ for e in entries]}"
            )

            normalized: list[dict[str, Any]] = []
            for e in entries:
                if not isinstance(e, dict):
                    continue
                ncpdp = cls._first_present(e, cls._NCPDP_KEYS)
                name = cls._first_present(e, cls._NAME_KEYS)
                address = cls._first_present(e, cls._ADDRESS_KEYS)
                city = cls._first_present(e, cls._CITY_KEYS)
                state = cls._first_present(e, cls._STATE_KEYS)
                zip_code = cls._first_present(e, cls._ZIP_KEYS)
                default_flag = False
                for k in cls._DEFAULT_KEYS:
                    if k in e:
                        default_flag = bool(e.get(k))
                        break

                # If we have an NCPDP id but no name/address, fetch from the
                # pharmacy directory so the UI shows something useful.
                if ncpdp and not name:
                    try:
                        from canvas_sdk.utils.http import pharmacy_http
                        details = pharmacy_http.get_pharmacy_by_ncpdp_id(ncpdp) or {}
                        name = name or str(details.get("organization_name") or "")
                        address = address or str(details.get("address_line_1") or "")
                        city = city or str(details.get("city") or "")
                        state = state or str(details.get("state") or "")
                        zip_code = zip_code or str(details.get("zip_code") or "")
                    except Exception as exc:
                        log.warning(
                            f"CurrentProvidersModule: pharmacy lookup for ncpdp={ncpdp} "
                            f"failed: {exc}"
                        )

                normalized.append({
                    "ncpdp_id": ncpdp,
                    "organization_name": name,
                    "address_line_1": address,
                    "city": city,
                    "state": state,
                    "zip_code": zip_code,
                    "default": default_flag,
                })
            return normalized
        except Exception as exc:
            log.warning(
                f"CurrentProvidersModule: could not read preferred_pharmacy "
                f"for patient={patient_id}: {exc}"
            )
            return []

    def render_content_html(self) -> str:
        """Render provider fields form."""
        ctx = self.get_context()
        html = ""
        html += self._alert(ctx["instructions"], "info")

        # Render PCP first
        pcp = next(c for c in ctx["provider_categories"] if c["id"] == "pcp")
        html += self._text_input(pcp["id"], pcp["label"], placeholder=pcp.get("placeholder", ""), required=True)

        # Structured specialist rows
        html += self._subtitle("Specialists")
        html += '<div id="specialist-rows">'
        html += self._specialist_row(0)
        html += '</div>'
        html += (
            '<button type="button" class="awv-save-btn" id="add-specialist-btn" '
            'onclick="addSpecialistRow()" style="margin-top:6px;background:#546e7a;">'
            '+ Add Another Specialist</button>'
        )

        # Pharmacy section: existing preferred pharmacies + search-and-add
        html += self._render_pharmacy_section(ctx["existing_pharmacies"])

        # Remaining categories (dme, home health, other)
        for cat in ctx["provider_categories"]:
            if cat["id"] == "pcp":
                continue
            if cat.get("multiline"):
                html += self._textarea(cat["id"], cat["label"], placeholder=cat.get("placeholder", ""))
            else:
                html += self._text_input(cat["id"], cat["label"], placeholder=cat.get("placeholder", ""))

        return f'<div class="awv-module-content">{html}{self._save_button("saveCurrentProviders", "Save Providers")}</div>'

    @staticmethod
    def _render_pharmacy_section(existing: list[dict[str, Any]]) -> str:
        """Render the Pharmacy subsection: existing preferred pharmacies + search-and-add."""
        html = '<div class="awv-subtitle" style="font-size:13px; font-weight:700; color:#1a1a1a; margin:8px 0 6px 0; padding-bottom:4px; border-bottom:2px solid #e3f2fd;">Pharmacy</div>'

        # Existing preferred pharmacies (read from chart)
        if existing:
            html += '<div class="awv-label" style="font-size:11px;color:#666;margin-bottom:4px;">Current preferred pharmacies (from chart):</div>'
            html += '<div id="existing-pharmacies" style="margin-bottom:10px;">'
            for p in existing:
                badge = (
                    ' <span style="background:#1565c0;color:#fff;padding:1px 6px;border-radius:8px;font-size:10px;font-weight:600;margin-left:6px;">DEFAULT</span>'
                    if p.get("default")
                    else ""
                )
                addr_parts = [p.get("address_line_1", ""), p.get("city", ""), p.get("state", ""), p.get("zip_code", "")]
                addr = ", ".join([a for a in addr_parts if a])
                name = p.get("organization_name") or "(unnamed pharmacy)"
                # Escape values coming from the Canvas pharmacy directory and
                # patient chart JSON - they're not directly user-controlled but
                # they're not part of our trust boundary either.
                safe_name = html_escape(str(name))
                safe_addr = html_escape(str(addr))
                html += (
                    f'<div style="padding:6px 10px;background:#f5f5f5;border-radius:4px;margin-bottom:4px;font-size:12px;">'
                    f'<strong>{safe_name}</strong>{badge}'
                    f'<div style="color:#666;font-size:11px;">{safe_addr}</div>'
                    f'</div>'
                )
            html += '</div>'
        else:
            html += '<div class="awv-info-row" style="color:#666;font-size:12px;margin-bottom:8px;">No preferred pharmacies on file.</div>'

        # Search input + autocomplete results dropdown
        html += '<label class="awv-label" for="pharmacy-search">Search to add an additional pharmacy:</label>'
        html += (
            '<div style="position:relative;">'
            '<input type="text" id="pharmacy-search" class="awv-input" '
            'placeholder="Type pharmacy name, city, or NCPDP ID..." '
            'oninput="searchPharmacies(this.value)" '
            'autocomplete="off">'
            '<div id="pharmacy-search-results" style="display:none;position:absolute;top:100%;left:0;right:0;'
            'background:#fff;border:1px solid #ccc;border-radius:4px;max-height:240px;overflow-y:auto;z-index:10;'
            'box-shadow:0 2px 8px rgba(0,0,0,0.1);"></div>'
            '</div>'
        )

        # Pending additions (cleared after save)
        html += (
            '<div class="awv-label" style="font-size:11px;color:#666;margin-top:10px;margin-bottom:4px;">'
            'Pending additions (will be saved when you click Save Providers):</div>'
            '<div id="pharmacy-pending" data-pending-pharmacies="[]" '
            'style="min-height:24px;padding:6px 10px;background:#fffde7;border:1px dashed #ffe082;border-radius:4px;font-size:12px;color:#999;">'
            '(none)</div>'
        )

        return html

    SPECIALTIES = [
        "Allergy & Immunology",
        "Cardiology",
        "Dermatology",
        "Endocrinology",
        "Gastroenterology",
        "Hematology / Oncology",
        "Infectious Disease",
        "Nephrology",
        "Neurology",
        "OB/GYN",
        "Ophthalmology",
        "Orthopedics",
        "Pain Management",
        "Palliative Care",
        "Physical Therapy",
        "Podiatry",
        "Psychiatry",
        "Pulmonology",
        "Rheumatology",
        "Surgery - General",
        "Surgery - Cardiothoracic",
        "Urology",
        "Vascular Surgery",
        "Other",
    ]

    @classmethod
    def _specialty_options_html(cls) -> str:
        """Return <option> tags for the specialty dropdown."""
        opts = '<option value="">-- Select specialty --</option>'
        for s in cls.SPECIALTIES:
            opts += f'<option value="{s}">{s}</option>'
        return opts

    @classmethod
    def _specialist_row(cls, index: int) -> str:
        """Render a single specialist row with name, specialty dropdown, phone fields."""
        return (
            f'<div class="specialist-row" style="display:flex;gap:8px;margin-bottom:6px;">'
            f'<input type="text" name="specialist_{index}_name" class="awv-input" '
            f'placeholder="Provider name" style="flex:2;">'
            f'<select name="specialist_{index}_specialty" class="awv-select" style="flex:2;">'
            f'{cls._specialty_options_html()}'
            f'</select>'
            f'<input type="text" name="specialist_{index}_phone" class="awv-input" '
            f'placeholder="Phone number" style="flex:1;">'
            f'</div>'
        )

    def get_context(self) -> dict[str, Any]:
        """Return current providers context, including the patient's existing preferred pharmacies."""
        return {
            "is_initial": self.awv_type == AWVType.INITIAL,
            "provider_categories": self.PROVIDER_CATEGORIES,
            "existing_pharmacies": self._read_existing_pharmacies(self.patient_id),
            "instructions": (
                "Document all current healthcare providers and suppliers. "
                "CMS requires this list as part of the Annual Wellness Visit."
            ),
        }
