"""Preventive Services Checklist module."""

from __future__ import annotations

import datetime
from typing import Any

from canvas_sdk.v1.data.patient import Patient, SexAtBirth

from guided_awv.modules.base import AWVType, BaseModule


class PreventiveServicesModule(BaseModule):
    """
    Preventive Services Checklist section.

    Displays age and gender-appropriate screenings with due dates.
    Subsequent AWV shows status since last AWV with gap identification.

    Supports ordering directly from this section via SimpleAPI.
    """

    ORDER = 14
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-shield-alt"

    @property
    def TITLE(self) -> str:  # type: ignore[override]
        """Return title based on AWV type."""
        if self.awv_type == AWVType.SUBSEQUENT:
            return "Preventive Services (Gap Analysis)"
        return "Preventive Services Checklist"

    def render_content_html(self) -> str:
        """Render preventive services checklist."""
        ctx = self.get_context()
        if ctx.get("error"):
            return f'<div class="awv-module-content">{self._alert(ctx["error"], "error")}</div>'
        html = ""
        html += self._info_row("Patient Age", str(ctx["patient_age"]))
        html += self._info_row("Sex at Birth", str(ctx["patient_sex"]))
        html += self._divider()
        html += self._subtitle("Recommended Screenings & Immunizations")
        for svc in ctx["services"]:
            if not svc.get("eligible", True):
                continue
            freq = f' <span style="font-size:10px;color:#666;">({svc["frequency"]})</span>' if svc.get("frequency") else ""
            note_html = f'<div style="font-size:11px;color:#888;padding:2px 0 4px 0;">{svc["note"]}</div>' if svc.get("note") else ""
            html += (
                f'<div class="awv-info-row" style="align-items:flex-start;">'
                f'<span class="awv-info-label">{svc["name"]}{freq}'
                f'<div style="display:flex;align-items:center;gap:6px;margin-top:4px;">'
                f'<label style="font-size:11px;color:#666;white-space:nowrap;">Last done:</label>'
                f'<input type="date" name="svc_{svc["id"]}_last_date" '
                f'style="font-size:11px;padding:2px 4px;border:1px solid #ddd;border-radius:3px;color:#555;">'
                f'</div>'
                f'<div style="display:flex;align-items:center;gap:6px;margin-top:4px;">'
                f'<label style="font-size:11px;color:#666;white-space:nowrap;">Next due:</label>'
                f'<input type="date" name="svc_{svc["id"]}_next_date" '
                f'style="font-size:11px;padding:2px 4px;border:1px solid #ddd;border-radius:3px;color:#555;">'
                f'</div></span>'
                f'<span class="awv-info-value">'
                f'<label class="awv-checkbox"><input type="checkbox" name="svc_{svc["id"]}_ordered" value="ordered"> Ordered</label>'
                f'<label class="awv-checkbox"><input type="checkbox" name="svc_{svc["id"]}_discussed" value="discussed"> Discussed</label>'
                f'</span></div>'
                f'{note_html}'
            )

        # Chronic disease monitoring section
        html += self._divider()
        html += self._subtitle("Chronic Disease Monitoring")
        chronic_items = [
            ("hba1c", "HbA1c (Diabetes)"),
            ("diabetic_eye_exam", "Diabetic Eye Exam"),
            ("diabetic_foot_exam", "Diabetic Foot Exam"),
            ("lipid_panel_cvd", "Lipid Panel (CVD Monitoring)"),
        ]
        for item_id, item_label in chronic_items:
            html += (
                f'<div class="awv-info-row" style="align-items:flex-start;">'
                f'<span class="awv-info-label">{item_label}'
                f'<div style="display:flex;align-items:center;gap:6px;margin-top:4px;">'
                f'<label style="font-size:11px;color:#666;white-space:nowrap;">Last done:</label>'
                f'<input type="date" name="chronic_{item_id}_last_date" '
                f'style="font-size:11px;padding:2px 4px;border:1px solid #ddd;border-radius:3px;color:#555;">'
                f'</div></span>'
                f'<span class="awv-info-value">'
                f'<label class="awv-checkbox"><input type="checkbox" name="chronic_{item_id}" value="ordered"> Ordered</label>'
                f'<label class="awv-checkbox"><input type="checkbox" name="chronic_{item_id}_discussed" value="discussed"> Discussed</label>'
                f'</span></div>'
            )

        # Behavioral health monitoring section
        html += self._divider()
        html += self._subtitle("Behavioral Health Monitoring")
        bh_items = [
            ("annual_depression", "Annual Depression Screening"),
            ("annual_cognitive", "Annual Cognitive Assessment"),
        ]
        for item_id, item_label in bh_items:
            html += (
                f'<div class="awv-info-row" style="align-items:flex-start;">'
                f'<span class="awv-info-label">{item_label}'
                f'<div style="display:flex;align-items:center;gap:6px;margin-top:4px;">'
                f'<label style="font-size:11px;color:#666;white-space:nowrap;">Last done:</label>'
                f'<input type="date" name="bh_{item_id}_last_date" '
                f'style="font-size:11px;padding:2px 4px;border:1px solid #ddd;border-radius:3px;color:#555;">'
                f'</div></span>'
                f'<span class="awv-info-value">'
                f'<label class="awv-checkbox"><input type="checkbox" name="bh_{item_id}" value="completed_today"> Completed Today</label>'
                f'</span></div>'
            )

        html += self._divider()
        html += self._subtitle("Documentation")
        html += self._radio_group(
            "prevention_plan_created",
            "Personalized prevention plan created?",
            ["Yes", "No"],
            required=True,
        )
        html += (
            '<div id="prevention-plan-warning" class="awv-alert awv-alert--warning" style="display:none;">'
            'CMS requires a personalized prevention plan for AWV billing compliance. '
            'Selecting "No" will leave Element 10 incomplete in the Provider Attestation.'
            '</div>'
        )
        html += self._radio_group(
            "written_copy_given",
            "Written copy of plan given to patient?",
            ["Yes", "No"],
            required=True,
        )
        html += (
            '<div id="written-copy-warning" class="awv-alert awv-alert--warning" style="display:none;">'
            'CMS requires the patient receive a written copy of the prevention plan for AWV billing compliance.'
            '</div>'
        )

        return f'<div class="awv-module-content">{html}{self._save_button("savePreventiveServices", "Save Services")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return preventive services context based on patient demographics."""
        patient = Patient.objects.filter(id=self.patient_id).first()
        if not patient:
            return {"services": [], "error": "Patient not found"}

        age = self._calculate_age(patient.birth_date)
        sex = patient.sex_at_birth

        services = self._build_services_list(age, sex)

        return {
            "is_subsequent": self.awv_type == AWVType.SUBSEQUENT,
            "patient_age": age,
            "patient_sex": sex,
            "services": services,
            "note_id": self.note_id,
        }

    def _calculate_age(self, birth_date: datetime.date | None) -> int:
        """Calculate patient age from birth date."""
        if not birth_date:
            return 0
        today = datetime.date.today()
        return today.year - birth_date.year - (
            (today.month, today.day) < (birth_date.month, birth_date.day)
        )

    def _build_services_list(self, age: int, sex: str) -> list[dict[str, Any]]:
        """Build age/gender-appropriate preventive services list.

        Also available as module-level function ``build_services_list(age, sex)``.
        """
        services = []

        # Universal services (all patients 65+)
        services.append({
            "id": "influenza",
            "name": "Influenza Vaccine",
            "frequency": "Annual",
            "eligible": True,
            "cpt_codes": ["90658", "90686"],
            "icd10_ordering_code": "Z23",
            "ordering_enabled": True,
        })

        services.append({
            "id": "pneumococcal",
            "name": "Pneumococcal Vaccine (PCV15/PCV20 or PPSV23)",
            "frequency": "Per schedule",
            "eligible": age >= 65,
            "cpt_codes": ["90670", "90732", "90671"],
            "icd10_ordering_code": "Z23",
            "ordering_enabled": True,
        })

        services.append({
            "id": "covid_vaccine",
            "name": "COVID-19 Vaccine (updated)",
            "frequency": "Annual (updated formula)",
            "eligible": True,
            "cpt_codes": ["91318"],
            "ordering_enabled": True,
        })

        services.append({
            "id": "tdap_td",
            "name": "Tdap / Td Vaccine",
            "frequency": "Tdap once, then Td booster every 10 years",
            "eligible": age >= 18,
            "cpt_codes": ["90715", "90714"],
            "icd10_ordering_code": "Z23",
            "ordering_enabled": True,
        })

        services.append({
            "id": "shingles",
            "name": "Shingrix (Recombinant Zoster Vaccine)",
            "frequency": "2-dose series",
            "eligible": age >= 50,
            "cpt_codes": ["90750"],
            "ordering_enabled": True,
        })

        services.append({
            "id": "rsv",
            "name": "RSV Vaccine (Abrysvo / Arexvy)",
            "frequency": "Single dose",
            "eligible": age >= 60,
            "note": "ACIP recommends shared clinical decision-making for adults 60+. Administer one dose of RSV vaccine.",
            "cpt_codes": ["90679", "90680"],
            "ordering_enabled": True,
        })

        # Colorectal cancer screening
        services.append({
            "id": "colorectal",
            "name": "Colorectal Cancer Screening",
            "frequency": "Per method (annual FIT/FOBT, every 3y FIT-DNA, every 10y colonoscopy)",
            "eligible": 45 <= age <= 85,
            "ordering_enabled": True,
            "options": [
                {"label": "FIT/FOBT (annual)", "cpt": "82274"},
                {"label": "Cologuard (every 3 years)", "cpt": "81528"},
                {"label": "Colonoscopy (every 10 years)", "cpt": "G0121"},
            ],
        })

        # Bone density (women 65+, or post-menopausal < 65 with risk)
        if sex in (SexAtBirth.FEMALE, "F"):
            services.append({
                "id": "dexa",
                "name": "Bone Density (DEXA Scan)",
                "frequency": "Every 2 years (if normal)",
                "eligible": age >= 65,
                "cpt_codes": ["77080"],
                "ordering_enabled": True,
            })

            # Mammography
            services.append({
                "id": "mammogram",
                "name": "Mammography Screening",
                "frequency": "Annual (ages 40-74) or biennial",
                "eligible": 40 <= age <= 74,
                "cpt_codes": ["77067"],
                "ordering_enabled": True,
            })

            # Cervical cancer screening (women 21-65, USPSTF A/B)
            services.append({
                "id": "cervical_cancer",
                "name": "Cervical Cancer Screening (Pap / HPV)",
                "frequency": "Pap every 3y (21-29), Pap+HPV co-test every 5y or Pap every 3y (30-65)",
                "eligible": 21 <= age <= 65,
                "note": "USPSTF A/B recommendation. May discontinue after 65 if adequate prior screening and not high risk.",
                "cpt_codes": ["88175", "87624"],
                "ordering_enabled": True,
            })

        # Lung cancer screening (heavy smokers 50-80)
        services.append({
            "id": "ldct_lung",
            "name": "Low-Dose CT Lung Screening (LDCT)",
            "frequency": "Annual (if qualifying smoker)",
            "eligible": 50 <= age <= 80,
            "note": "Eligibility: 20+ pack-year history, current or quit < 15 years ago",
            "cpt_codes": ["71271"],
            "ordering_enabled": True,
        })

        # Diabetes / prediabetes screening
        services.append({
            "id": "diabetes_screen",
            "name": "Diabetes / Prediabetes Screening",
            "frequency": "Every 3 years (if overweight/obese)",
            "eligible": True,
            "cpt_codes": ["82947", "83036"],
            "ordering_enabled": True,
        })

        # Abdominal aortic aneurysm (men 65-75, one-time if smoker)
        if sex in (SexAtBirth.MALE, "M"):
            services.append({
                "id": "aaa",
                "name": "Abdominal Aortic Aneurysm Ultrasound",
                "frequency": "One-time screen (age 65-75, ever-smoker)",
                "eligible": 65 <= age <= 75,
                "cpt_codes": ["76706"],
                "ordering_enabled": True,
            })

            # Prostate cancer screening discussion (men 55-69, USPSTF C)
            services.append({
                "id": "prostate_psa",
                "name": "Prostate Cancer Screening (PSA) — Shared Decision-Making",
                "frequency": "Discuss individually (ages 55-69)",
                "eligible": 55 <= age <= 69,
                "note": "USPSTF C recommendation. Discuss benefits and harms of PSA-based screening. Document shared decision-making.",
                "cpt_codes": ["84153"],
                "ordering_enabled": True,
            })

        # Hepatitis C screening (one-time, adults 18-79, USPSTF B)
        services.append({
            "id": "hep_c",
            "name": "Hepatitis C Screening (Anti-HCV)",
            "frequency": "One-time screening",
            "eligible": 18 <= age <= 79,
            "note": "USPSTF B recommendation. One-time screening for all adults 18-79. Repeat if ongoing risk factors.",
            "cpt_codes": ["86803"],
            "ordering_enabled": True,
        })

        # Lipid panel
        services.append({
            "id": "lipids",
            "name": "Lipid Panel",
            "frequency": "Every 5 years (or per risk)",
            "eligible": True,
            "cpt_codes": ["80061"],
            "ordering_enabled": True,
        })

        return services


def build_services_list(age: int, sex: str) -> list[dict[str, Any]]:
    """Build age/sex-appropriate preventive services list.

    Standalone version of PreventiveServicesModule._build_services_list
    for use outside the module class (e.g., prevention plan generation).
    """
    from canvas_sdk.v1.data.patient import SexAtBirth

    services: list[dict[str, Any]] = []

    services.append({"id": "influenza", "name": "Influenza Vaccine", "frequency": "Annual", "eligible": True})
    services.append({"id": "pneumococcal", "name": "Pneumococcal Vaccine (PCV15/PCV20 or PPSV23)", "frequency": "Per schedule", "eligible": age >= 65})
    services.append({"id": "covid_vaccine", "name": "COVID-19 Vaccine (updated)", "frequency": "Annual (updated formula)", "eligible": True})
    services.append({"id": "tdap_td", "name": "Tdap / Td Vaccine", "frequency": "Tdap once, then Td booster every 10 years", "eligible": age >= 18})
    services.append({"id": "shingles", "name": "Shingrix (Recombinant Zoster Vaccine)", "frequency": "2-dose series", "eligible": age >= 50})
    services.append({"id": "rsv", "name": "RSV Vaccine (Abrysvo / Arexvy)", "frequency": "Single dose", "eligible": age >= 60})
    services.append({"id": "colorectal", "name": "Colorectal Cancer Screening", "frequency": "Per method (annual FIT/FOBT, every 3y FIT-DNA, every 10y colonoscopy)", "eligible": 45 <= age <= 85})
    if sex in (SexAtBirth.FEMALE, "F"):
        services.append({"id": "dexa", "name": "Bone Density (DEXA Scan)", "frequency": "Every 2 years (if normal)", "eligible": age >= 65})
        services.append({"id": "mammogram", "name": "Mammography Screening", "frequency": "Annual (ages 40-74) or biennial", "eligible": 40 <= age <= 74})
        services.append({"id": "cervical_cancer", "name": "Cervical Cancer Screening (Pap / HPV)", "frequency": "Pap every 3y (21-29), Pap+HPV co-test every 5y or Pap every 3y (30-65)", "eligible": 21 <= age <= 65})
    services.append({"id": "ldct_lung", "name": "Low-Dose CT Lung Screening (LDCT)", "frequency": "Annual (if qualifying smoker)", "eligible": 50 <= age <= 80})
    services.append({"id": "diabetes_screen", "name": "Diabetes / Prediabetes Screening", "frequency": "Every 3 years (if overweight/obese)", "eligible": True})
    if sex in (SexAtBirth.MALE, "M"):
        services.append({"id": "aaa", "name": "Abdominal Aortic Aneurysm Ultrasound", "frequency": "One-time screen (age 65-75, ever-smoker)", "eligible": 65 <= age <= 75})
        services.append({"id": "prostate_psa", "name": "Prostate Cancer Screening (PSA)", "frequency": "Discuss individually (ages 55-69)", "eligible": 55 <= age <= 69})
    services.append({"id": "hep_c", "name": "Hepatitis C Screening (Anti-HCV)", "frequency": "One-time screening", "eligible": 18 <= age <= 79})
    services.append({"id": "lipids", "name": "Lipid Panel", "frequency": "Every 5 years (or per risk)", "eligible": True})

    return [s for s in services if s.get("eligible", True)]
