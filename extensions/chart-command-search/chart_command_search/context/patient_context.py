from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from logger import log

AI_DATE_RANGE_DAYS = 180


def fetch_patient_context(patient_id: str) -> dict[str, Any]:
    """Fetch broad patient data for AI context. Returns a dict of sections."""
    ctx: dict[str, Any] = {}

    try:
        from canvas_sdk.v1.data.patient import Patient

        patient = (
            Patient.objects.filter(id=patient_id)
            .select_related("default_provider")
            .first()
        )
        if patient:
            demo: dict[str, Any] = {
                "name": f"{patient.first_name or ''} {patient.last_name or ''}".strip(),
                "dob": str(patient.birth_date) if patient.birth_date else "",
                "sex": patient.sex_at_birth or "",
            }
            if patient.nickname:
                demo["nickname"] = patient.nickname
            if patient.prefix:
                demo["prefix"] = patient.prefix
            if patient.suffix:
                demo["suffix"] = patient.suffix
            if patient.clinical_note:
                demo["clinical_note"] = patient.clinical_note[:300]
            if patient.administrative_note:
                demo["admin_note"] = patient.administrative_note[:300]
            if patient.mrn:
                demo["mrn"] = patient.mrn
            prov = getattr(patient, "default_provider", None)
            if prov:
                prov_name = f"{prov.first_name or ''} {prov.last_name or ''}".strip()
                if prov_name:
                    demo["default_provider"] = prov_name
            ctx["demographics"] = demo
    except Exception as exc:
        log.warning("Failed to fetch demographics: %s", exc)

    try:
        from canvas_sdk.v1.data.patient import PatientContactPoint

        contacts = list(
            PatientContactPoint.objects.filter(
                patient__id=patient_id, state="active"
            ).values("system", "value", "use")[:10]
        )
        if contacts:
            ctx["contacts"] = [
                {k: v for k, v in c.items() if v} for c in contacts
            ]
    except Exception as exc:
        log.warning("Failed to fetch contacts: %s", exc)

    try:
        from canvas_sdk.v1.data.patient import PatientAddress

        addrs = list(
            PatientAddress.objects.filter(
                patient__id=patient_id, state="active"
            ).values("line1", "line2", "city", "state_code", "postal_code", "use")[:5]
        )
        if addrs:
            ctx["addresses"] = [
                {k: v for k, v in a.items() if v} for a in addrs
            ]
    except Exception as exc:
        log.warning("Failed to fetch addresses: %s", exc)

    try:
        from canvas_sdk.v1.data.condition import Condition

        conditions = (
            Condition.objects.filter(
                patient__id=patient_id,
                clinical_status__in=["active", "relapse", "remission"],
            )
            .prefetch_related("codings")
            .order_by("-onset_date")[:30]
        )
        cond_list = []
        for c in conditions:
            entry: dict[str, str] = {}
            codings = list(c.codings.all())
            if codings:
                entry["name"] = codings[0].display or ""
                entry["code"] = codings[0].code or ""
            entry["status"] = c.clinical_status or ""
            if c.onset_date:
                entry["onset"] = str(c.onset_date)
            cond_list.append({k: v for k, v in entry.items() if v})
        if cond_list:
            ctx["conditions"] = cond_list
    except Exception as exc:
        log.warning("Failed to fetch conditions: %s", exc)

    try:
        from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance

        allergies = (
            AllergyIntolerance.objects.filter(
                patient__id=patient_id, deleted=False
            )
            .prefetch_related("codings")
            .order_by("-recorded_date")[:20]
        )
        allergy_list = []
        for a in allergies:
            entry = {}
            codings = list(a.codings.all())
            if codings:
                entry["name"] = codings[0].display or ""
            if a.severity:
                entry["severity"] = a.severity
            if a.narrative:
                entry["narrative"] = a.narrative[:200]
            allergy_list.append({k: v for k, v in entry.items() if v})
        if allergy_list:
            ctx["allergies"] = allergy_list
    except Exception as exc:
        log.warning("Failed to fetch allergies: %s", exc)

    try:
        from canvas_sdk.v1.data.medication import Medication

        meds = (
            Medication.objects.filter(patient__id=patient_id, status="active")
            .prefetch_related("codings")
            .order_by("-start_date")[:25]
        )
        med_list = []
        for m in meds:
            entry = {}
            codings = list(m.codings.all())
            if codings:
                entry["name"] = codings[0].display or ""
            if m.clinical_quantity_description:
                entry["quantity"] = m.clinical_quantity_description
            if m.start_date:
                entry["start"] = str(m.start_date)
            med_list.append({k: v for k, v in entry.items() if v})
        if med_list:
            ctx["medications"] = med_list
    except Exception as exc:
        log.warning("Failed to fetch medications: %s", exc)

    try:
        from canvas_sdk.v1.data.lab import LabReport, LabValue

        cutoff = date.today() - timedelta(days=AI_DATE_RANGE_DAYS)
        lab_values = (
            LabValue.objects.filter(
                report__patient__id=patient_id,
                report__original_date__gte=cutoff,
            )
            .select_related("report")
            .prefetch_related("codings")
            .order_by("-report__original_date")[:50]
        )
        lab_list = []
        for lv in lab_values:
            entry: dict[str, str] = {}
            codings = list(lv.codings.all())
            if codings:
                entry["test"] = codings[0].name or ""
                entry["code"] = codings[0].code or ""
            if lv.value:
                entry["value"] = str(lv.value)
            if lv.units:
                entry["units"] = lv.units
            if lv.reference_range:
                entry["ref_range"] = lv.reference_range
            if lv.abnormal_flag:
                entry["flag"] = lv.abnormal_flag
            if lv.comment:
                entry["comment"] = str(lv.comment)[:200]
            if lv.observation_status:
                entry["status"] = lv.observation_status
            if lv.low_threshold:
                entry["low"] = lv.low_threshold
            if lv.high_threshold:
                entry["high"] = lv.high_threshold
            report = lv.report
            if report and report.original_date:
                entry["date"] = str(report.original_date)
            lab_list.append({k: v for k, v in entry.items() if v})
        if lab_list:
            ctx["lab_results"] = lab_list

        reports = (
            LabReport.objects.filter(
                patient__id=patient_id,
                original_date__gte=cutoff,
            )
            .prefetch_related("values", "values__codings")
            .order_by("-original_date")[:20]
        )
        report_list = []
        for r in reports:
            entry: dict[str, str] = {}
            if r.custom_document_name:
                entry["name"] = r.custom_document_name
            if r.original_date:
                entry["date"] = str(r.original_date)
            if r.requisition_number:
                entry["requisition"] = r.requisition_number
            vals = list(r.values.all())
            if vals:
                val_summaries = []
                for v in vals:
                    vc = list(v.codings.all())
                    vname = vc[0].name if vc else ""
                    vval = str(v.value or "")
                    vunits = v.units or ""
                    if vname or vval:
                        val_summaries.append(f"{vname}: {vval} {vunits}".strip())
                if val_summaries:
                    entry["values"] = "; ".join(val_summaries[:10])
            report_list.append({k: v for k, v in entry.items() if v})
        if report_list:
            ctx["lab_reports"] = report_list
    except Exception as exc:
        log.warning("Failed to fetch lab results: %s", exc)

    try:
        from canvas_sdk.v1.data.observation import Observation

        cutoff = date.today() - timedelta(days=AI_DATE_RANGE_DAYS)
        obs = (
            Observation.objects.filter(
                patient__id=patient_id,
                effective_datetime__date__gte=cutoff,
            )
            .prefetch_related("components", "codings")
            .order_by("-effective_datetime")[:60]
        )
        obs_list = []
        for o in obs:
            entry: dict[str, Any] = {"name": o.name or ""}
            if o.value:
                entry["value"] = str(o.value)
            if o.units:
                entry["units"] = o.units
            if o.effective_datetime:
                entry["date"] = str(o.effective_datetime.date())
            components = list(o.components.all())
            if components:
                entry["components"] = [
                    {
                        "name": c.name or "",
                        "value": str(c.value_quantity or ""),
                        "units": c.value_quantity_unit or "",
                    }
                    for c in components
                ]
            obs_list.append({k: v for k, v in entry.items() if v})
        if obs_list:
            ctx["vitals_and_observations"] = obs_list
    except Exception as exc:
        log.warning("Failed to fetch vitals/observations: %s", exc)

    try:
        from canvas_sdk.v1.data.immunization import Immunization

        immz = (
            Immunization.objects.filter(patient__id=patient_id, deleted=False)
            .prefetch_related("codings")
            .order_by("-date_ordered")[:20]
        )
        immz_list = []
        for im in immz:
            entry = {}
            codings = list(im.codings.all())
            if codings:
                entry["vaccine"] = codings[0].display or ""
            entry["status"] = im.status or ""
            if im.date_ordered:
                entry["date"] = str(im.date_ordered)
            immz_list.append({k: v for k, v in entry.items() if v})
        if immz_list:
            ctx["immunizations"] = immz_list
    except Exception as exc:
        log.warning("Failed to fetch immunizations: %s", exc)

    try:
        from canvas_sdk.v1.data.prescription import Prescription

        if Prescription is not None:
            cutoff = date.today() - timedelta(days=AI_DATE_RANGE_DAYS)
            rxs = (
                Prescription.objects.filter(
                    patient__id=patient_id,
                    written_date__gte=cutoff,
                )
                .select_related("medication", "prescriber")
                .prefetch_related("medication__codings")
                .order_by("-written_date")[:25]
            )
            rx_list = []
            for rx in rxs:
                entry: dict[str, str] = {}
                med = getattr(rx, "medication", None)
                if med:
                    codings = list(med.codings.all())
                    if codings:
                        entry["medication"] = codings[0].display or ""
                if rx.sig_original_input:
                    entry["sig"] = rx.sig_original_input[:200]
                if rx.dispense_quantity:
                    entry["quantity"] = str(rx.dispense_quantity)
                if rx.count_of_refills_allowed is not None:
                    entry["refills"] = str(rx.count_of_refills_allowed)
                if rx.pharmacy_name:
                    entry["pharmacy"] = rx.pharmacy_name
                if rx.written_date:
                    entry["date"] = str(rx.written_date)
                prescriber = getattr(rx, "prescriber", None)
                if prescriber:
                    name = f"{prescriber.first_name or ''} {prescriber.last_name or ''}".strip()
                    if name:
                        entry["prescriber"] = name
                rx_list.append({k: v for k, v in entry.items() if v})
            if rx_list:
                ctx["prescriptions"] = rx_list
    except Exception as exc:
        log.warning("Failed to fetch prescriptions: %s", exc)

    try:
        from canvas_sdk.v1.data.goal import Goal

        goals = (
            Goal.objects.filter(
                patient__id=patient_id,
                lifecycle_status__in=["active", "accepted", "planned", "proposed"],
            )
            .order_by("-start_date")[:15]
        )
        goal_list = []
        for g in goals:
            entry = {}
            if g.goal_statement:
                entry["goal"] = g.goal_statement[:200]
            if g.achievement_status:
                entry["achievement"] = g.achievement_status
            if g.priority:
                entry["priority"] = g.priority
            if g.due_date:
                entry["due"] = str(g.due_date)
            if g.progress:
                entry["progress"] = g.progress[:200]
            goal_list.append({k: v for k, v in entry.items() if v})
        if goal_list:
            ctx["goals"] = goal_list
    except Exception as exc:
        log.warning("Failed to fetch goals: %s", exc)

    try:
        from canvas_sdk.v1.data.referral import Referral

        refs = (
            Referral.objects.filter(patient__id=patient_id)
            .select_related("service_provider")
            .order_by("-date_referred")[:15]
        )
        ref_list = []
        for r in refs:
            entry = {}
            sp = getattr(r, "service_provider", None)
            if sp:
                entry["referred_to"] = getattr(sp, "name", "") or ""
            if r.clinical_question:
                entry["question"] = r.clinical_question[:200]
            if r.priority:
                entry["priority"] = r.priority
            if r.date_referred:
                entry["date"] = str(r.date_referred)
            if r.notes:
                entry["notes"] = r.notes[:200]
            ref_list.append({k: v for k, v in entry.items() if v})
        if ref_list:
            ctx["referrals"] = ref_list
    except Exception as exc:
        log.warning("Failed to fetch referrals: %s", exc)

    try:
        from canvas_sdk.v1.data.imaging import ImagingOrder

        cutoff = date.today() - timedelta(days=AI_DATE_RANGE_DAYS)
        imgs = (
            ImagingOrder.objects.filter(
                patient__id=patient_id,
                date_time_ordered__date__gte=cutoff,
            )
            .select_related("imaging_center", "ordering_provider")
            .order_by("-date_time_ordered")[:15]
        )
        img_list = []
        for im in imgs:
            entry = {}
            if im.imaging:
                entry["imaging"] = im.imaging[:200]
            entry["status"] = im.status or ""
            if im.priority:
                entry["priority"] = im.priority
            if im.date_time_ordered:
                entry["date"] = str(im.date_time_ordered.date())
            ic = getattr(im, "imaging_center", None)
            if ic:
                entry["center"] = getattr(ic, "name", "") or ""
            img_list.append({k: v for k, v in entry.items() if v})
        if img_list:
            ctx["imaging_orders"] = img_list
    except Exception as exc:
        log.warning("Failed to fetch imaging orders: %s", exc)

    try:
        from canvas_sdk.v1.data.lab import LabOrder

        cutoff = date.today() - timedelta(days=AI_DATE_RANGE_DAYS)
        lab_orders = (
            LabOrder.objects.filter(
                note__patient__id=patient_id,
                date_ordered__gte=cutoff,
            )
            .select_related("ordering_provider")
            .prefetch_related("tests")
            .order_by("-date_ordered")[:15]
        )
        lo_list = []
        for lo in lab_orders:
            entry: dict[str, Any] = {}
            tests = list(lo.tests.all())
            if tests:
                entry["tests"] = [
                    t.ontology_test_name or t.ontology_test_code or ""
                    for t in tests
                ]
            if lo.comment:
                entry["comment"] = lo.comment[:200]
            if lo.date_ordered:
                entry["date"] = str(lo.date_ordered)
            if lo.fasting_status:
                entry["fasting"] = lo.fasting_status
            prov = getattr(lo, "ordering_provider", None)
            if prov:
                name = f"{prov.first_name or ''} {prov.last_name or ''}".strip()
                if name:
                    entry["provider"] = name
            lo_list.append({k: v for k, v in entry.items() if v})
        if lo_list:
            ctx["lab_orders"] = lo_list
    except Exception as exc:
        log.warning("Failed to fetch lab orders: %s", exc)

    try:
        from canvas_sdk.v1.data.assessment import Assessment

        assessments = (
            Assessment.objects.filter(patient__id=patient_id)
            .select_related("condition")
            .prefetch_related("condition__codings")
            .order_by("-note__datetime_of_service")[:20]
        )
        assess_list = []
        for a in assessments:
            entry = {}
            cond = getattr(a, "condition", None)
            if cond:
                codings = list(cond.codings.all())
                if codings:
                    entry["condition"] = codings[0].display or ""
            if a.status:
                entry["status"] = a.status
            if a.narrative:
                entry["narrative"] = a.narrative[:200]
            if a.background:
                entry["background"] = a.background[:200]
            assess_list.append({k: v for k, v in entry.items() if v})
        if assess_list:
            ctx["assessments"] = assess_list
    except Exception as exc:
        log.warning("Failed to fetch assessments: %s", exc)

    _CONSENT_STATE_LABELS: dict[str, str] = {
        "accepted": "Accepted",
        "accepted_via_patient_portal": "Accepted via patient portal",
        "rejected": "Rejected",
        "rejected_via_patient_portal": "Rejected via patient portal",
    }
    try:
        from canvas_sdk.v1.data.patient_consent import (
            PatientConsent,
            PatientConsentCoding,
        )

        all_consent_types = {
            ct.dbid: ct
            for ct in PatientConsentCoding.objects.filter(is_mandatory=True)[:50]
        }
        signed_consents = (
            PatientConsent.objects.filter(patient__id=patient_id)
            .select_related("category", "rejection_reason")
            .order_by("-effective_date")[:15]
        )
        signed_type_ids: set[int] = set()
        consent_list = []
        for c in signed_consents:
            entry: dict[str, str] = {}
            cat = getattr(c, "category", None)
            if cat:
                entry["type"] = cat.display or ""
                signed_type_ids.add(cat.dbid)
                if cat.is_mandatory:
                    entry["mandatory"] = "Yes"
            raw_state = c.state or ""
            entry["status"] = _CONSENT_STATE_LABELS.get(raw_state, raw_state.replace("_", " ").title())
            if c.effective_date:
                entry["effective"] = str(c.effective_date)
            if c.expired_date:
                entry["expires"] = str(c.expired_date)
            rej = getattr(c, "rejection_reason", None)
            if rej:
                entry["rejection_reason"] = rej.display or ""
            consent_list.append({k: v for k, v in entry.items() if v})
        for ct_id, ct in all_consent_types.items():
            if ct_id not in signed_type_ids and ct.is_mandatory:
                consent_list.append({
                    "type": ct.display or "",
                    "mandatory": "Yes",
                    "status": "Not provided — this consent is required",
                })
        if consent_list:
            ctx["consents"] = consent_list
    except Exception as exc:
        log.warning("Failed to fetch consents: %s", exc)

    try:
        from canvas_sdk.v1.data.care_team import CareTeamMembership

        members = (
            CareTeamMembership.objects.filter(
                patient__id=patient_id,
                status__in=["active", "proposed"],
            )
            .select_related("staff", "role")
            .order_by("-created")[:15]
        )
        team_list = []
        for m in members:
            entry = {}
            staff = getattr(m, "staff", None)
            if staff:
                name = f"{staff.first_name or ''} {staff.last_name or ''}".strip()
                if name:
                    entry["member"] = name
            role = getattr(m, "role", None)
            if role:
                entry["role"] = role.display or ""
            elif m.role_display:
                entry["role"] = m.role_display
            entry["status"] = m.status or ""
            if m.lead:
                entry["lead"] = "Yes"
            team_list.append({k: v for k, v in entry.items() if v})
        if team_list:
            ctx["care_team"] = team_list
    except Exception as exc:
        log.warning("Failed to fetch care team: %s", exc)

    try:
        from canvas_sdk.v1.data.patient import PatientSetting

        settings = PatientSetting.objects.filter(patient__id=patient_id)[:50]
        prefs: dict[str, Any] = {}
        for s in settings:
            if s.name and s.value is not None:
                prefs[s.name] = s.value
        if prefs:
            ctx["preferences"] = prefs
    except Exception as exc:
        log.warning("Failed to fetch patient settings: %s", exc)

    try:
        from canvas_sdk.v1.data.coverage import Coverage

        coverages = (
            Coverage.objects.filter(patient__id=patient_id, state="active")
            .select_related("issuer")
            .order_by("coverage_rank")[:10]
        )
        cov_list = []
        for cov in coverages:
            entry: dict[str, str] = {}
            issuer = getattr(cov, "issuer", None)
            if issuer:
                entry["payer"] = issuer.name or ""
            if cov.plan:
                entry["plan"] = cov.plan
            if cov.plan_type:
                entry["plan_type"] = cov.plan_type
            if cov.coverage_rank:
                rank_labels = {1: "Primary", 2: "Secondary", 3: "Tertiary"}
                entry["rank"] = rank_labels.get(cov.coverage_rank, str(cov.coverage_rank))
            if cov.coverage_start_date:
                entry["start"] = str(cov.coverage_start_date)
            if cov.coverage_end_date:
                entry["end"] = str(cov.coverage_end_date)
            if cov.comments:
                entry["comments"] = cov.comments[:200]
            cov_list.append({k: v for k, v in entry.items() if v})
        if cov_list:
            ctx["coverages"] = cov_list
    except Exception as exc:
        log.warning("Failed to fetch coverages: %s", exc)

    try:
        from canvas_sdk.v1.data.claim import Claim

        cutoff = date.today() - timedelta(days=AI_DATE_RANGE_DAYS)
        claims = (
            Claim.objects.filter(
                note__patient__id=patient_id,
                note__datetime_of_service__date__gte=cutoff,
            )
            .select_related("current_queue", "note")
            .order_by("-note__datetime_of_service")[:20]
        )
        claim_list = []
        for cl in claims:
            entry: dict[str, str] = {}
            note = getattr(cl, "note", None)
            if note and note.datetime_of_service:
                entry["dos"] = str(note.datetime_of_service.date())
            queue = getattr(cl, "current_queue", None)
            if queue:
                entry["queue"] = queue.display_name or queue.name or ""
            if cl.narrative:
                entry["narrative"] = cl.narrative[:200]
            claim_list.append({k: v for k, v in entry.items() if v})
        if claim_list:
            ctx["claims"] = claim_list
    except Exception as exc:
        log.warning("Failed to fetch claims: %s", exc)

    return ctx
