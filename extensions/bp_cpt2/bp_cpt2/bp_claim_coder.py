"""
Shared utility functions for the BP CPT2 extension.
"""

import json
from datetime import datetime
from typing import Optional

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.billing_line_item import AddBillingLineItem, UpdateBillingLineItem
from canvas_sdk.v1.data import Note, Observation, Assessment, BillingLineItem, Command, Medication
from logger import log


# BP CPT/HCPCS Code Definitions - Individual codes as constants
# Systolic BP codes
CPT_3074F = "3074F"  # Systolic BP < 130 mmHg
CPT_3075F = "3075F"  # Systolic BP 130-139 mmHg
CPT_3077F = "3077F"  # Systolic BP >= 140 mmHg

# Diastolic BP codes
CPT_3078F = "3078F"  # Diastolic BP < 80 mmHg
CPT_3079F = "3079F"  # Diastolic BP 80-89 mmHg
CPT_3080F = "3080F"  # Diastolic BP >= 90 mmHg

# BP control status codes
HCPCS_G8783 = "G8783"  # BP documented and controlled
HCPCS_G8784 = "G8784"  # BP documented but not controlled
HCPCS_G8752 = "G8752"  # Most recent BP < 140/90 (can coexist with control status)

# BP not documented codes
HCPCS_G8950 = "G8950"  # BP not documented, reason not given
HCPCS_G8951 = "G8951"  # BP not documented, documented reason

# Treatment plan codes
HCPCS_G8753 = "G8753"  # BP >= 140/90 and treatment plan documented
HCPCS_G8754 = "G8754"  # BP >= 140/90 and no treatment plan, reason not given
HCPCS_G8755 = "G8755"  # BP >= 140/90 and no treatment plan, documented reason

# Code categories - codes within the same category are mutually exclusive
SYSTOLIC_CODES = {CPT_3074F, CPT_3075F, CPT_3077F}
DIASTOLIC_CODES = {CPT_3078F, CPT_3079F, CPT_3080F}
CONTROL_STATUS_CODES = {HCPCS_G8783, HCPCS_G8784}
NOT_DOCUMENTED_CODES = {HCPCS_G8950, HCPCS_G8951}
TREATMENT_PLAN_CODES = {HCPCS_G8753, HCPCS_G8754, HCPCS_G8755}

# All BP-related codes (union of all categories plus G8752)
BP_RELATED_CODES = (
    SYSTOLIC_CODES |
    DIASTOLIC_CODES |
    CONTROL_STATUS_CODES |
    NOT_DOCUMENTED_CODES |
    TREATMENT_PLAN_CODES |
    {HCPCS_G8752}
)


def get_blood_pressure_readings(note: Note) -> tuple[Optional[float], Optional[float]]:
    """
    Retrieve the minimum systolic and diastolic BP readings from up to 3 most recent observations for a specific note.

    This function retrieves up to 3 most recent blood pressure observations for the given note,
    parses each observation, and returns the minimum systolic and minimum diastolic values found
    across all observations.

    Args:
        note: Note object to get BP readings from (required)

    Returns:
        Tuple of (min_systolic, min_diastolic) as floats, or (None, None) if not found

    Examples:
        >>> get_blood_pressure_readings(my_note)
        (135.0, 85.0)  # Minimum values from up to 3 observations
    """
    # Build filters for the specific note
    filters = {
        "deleted": False,
        "entered_in_error_id__isnull": True,
        "committer_id__isnull": False,
        "note_id": note.dbid
    }

    # Get up to 3 most recent blood_pressure observations
    bp_observations = list(Observation.objects.filter(
        **filters,
        category='vital-signs',
        name='blood_pressure'
    ).exclude(value='').order_by('-created')[:3])

    log.info(f"Note {note.id} - Retrieved {len(bp_observations)} BP observation(s)")

    # Collect all valid systolic and diastolic values
    systolic_values = []
    diastolic_values = []

    for i, bp_observation in enumerate(bp_observations, 1):
        systolic = None
        diastolic = None

        if bp_observation and bp_observation.value:
            # Try parsing the value format "120/60"
            try:
                parts = bp_observation.value.split('/')
                if len(parts) == 2:
                    systolic = float(parts[0].strip())
                    diastolic = float(parts[1].strip())
                    log.info(f"Note {note.id} - Observation {i}: Parsed BP '{bp_observation.value}' -> {systolic}/{diastolic}")
            except (ValueError, AttributeError) as e:
                log.error(f"Note {note.id} - Observation {i}: Failed to parse BP value '{bp_observation.value}': {e}")

        # If parsing failed, try checking components
        if systolic is None or diastolic is None:
            if bp_observation and hasattr(bp_observation, 'components'):
                try:
                    # components might be a RelatedManager, so call .all() to get queryset
                    components_list = bp_observation.components.all() if hasattr(bp_observation.components, 'all') else []
                    log.info(f"Note {note.id} - Observation {i}: Checking components: {components_list}")
                    for component in components_list:  # pragma: no cover
                        # Fallback parsing for alternative component-based BP format
                        if 'systolic' in component.get('code', {}).get('text', '').lower():
                            systolic = float(component.get('value', {}).get('quantity', {}).get('value', 0))
                        elif 'diastolic' in component.get('code', {}).get('text', '').lower():
                            diastolic = float(component.get('value', {}).get('quantity', {}).get('value', 0))
                except (AttributeError, TypeError) as e:  # pragma: no cover
                    log.info(f"Note {note.id} - Observation {i}: Unable to parse components: {e}")

        # Add valid values to our lists
        if systolic is not None:
            systolic_values.append(systolic)
        if diastolic is not None:
            diastolic_values.append(diastolic)

    # Calculate minimum values
    systolic_value = min(systolic_values) if systolic_values else None
    diastolic_value = min(diastolic_values) if diastolic_values else None

    # Log the final result
    log.info(f"Note {note.id} - Final BP readings (minimum of {len(bp_observations)} observation(s)) - Systolic: {systolic_value}, Diastolic: {diastolic_value}")

    return systolic_value, diastolic_value


def prepare_note_commands_data(note: Note) -> str:
    """Extract and format all commands from the note for LLM analysis."""
    commands = Command.objects.filter(note=note)

    commands_data = []
    for cmd in commands:
        cmd_info = {
            "schema_key": cmd.schema_key,
            "data": cmd.data if cmd.data else {}
        }
        commands_data.append(cmd_info)

    if not commands_data:
        return "No commands documented in this note."

    return json.dumps(commands_data, indent=2)


def prepare_medications_data(patient_id: str) -> str:
    """Extract and format active medications for LLM analysis."""
    medications = Medication.objects.for_patient(patient_id).filter(deleted=False)

    medications_data = []
    for med in medications:
        med_info = {
            "name": med.fhir_medication_display if hasattr(med, 'fhir_medication_display') else str(med),
            "status": med.status if hasattr(med, 'status') else "unknown"
        }
        medications_data.append(med_info)

    if not medications_data:
        return "No active medications documented for this patient."

    return json.dumps(medications_data, indent=2)


def analyze_treatment_plan(
    openai_api_key: Optional[str],
    commands_data: str,
    medications_data: str,
    systolic: float,
    diastolic: float
) -> dict:
    """
    Use LLM to analyze if blood pressure treatment plan is documented.

    Args:
        openai_api_key: OpenAI API key for LLM analysis
        commands_data: JSON string of note commands
        medications_data: JSON string of patient medications
        systolic: Systolic blood pressure reading
        diastolic: Diastolic blood pressure reading

    Returns dict with:
        - has_treatment_plan (bool): Whether a treatment plan is documented
        - has_documented_reason (bool): Whether there's a documented reason for no treatment plan
        - explanation (str): Brief explanation of the analysis
    """
    from bp_cpt2.llm_openai import LlmOpenai

    # Check API key
    if not openai_api_key:
        log.error("OPENAI_API_KEY not provided")
        return {
            "has_treatment_plan": False,
            "has_documented_reason": False,
            "explanation": "Unable to analyze: OpenAI API key not configured"
        }

    llm = LlmOpenai(api_key=openai_api_key, model="gpt-4")

    system_prompt = """You are a clinical documentation analyst specializing in hypertension management.
Your task is to analyze clinical note data to determine if a blood pressure treatment plan is documented.

A treatment plan is considered documented if ANY of the following are present:
1. New or adjusted antihypertensive medications prescribed or planned
2. Lifestyle modifications specifically for blood pressure control (e.g., diet changes, exercise, salt restriction)
3. Follow-up plans specifically for blood pressure monitoring or management
4. Referrals to specialists for hypertension management
5. Patient education about blood pressure control

If NO treatment plan is found, check if there's a documented reason why (e.g., "patient declined",
"awaiting specialist consult", "recent medication change, monitoring before adjustment").

You must respond with valid JSON in the following format:
```json
{
    "has_treatment_plan": true/false,
    "has_documented_reason": true/false,
    "explanation": "brief explanation of your analysis"
}
```"""

    user_prompt = f"""Analyze the following clinical data for blood pressure treatment plan documentation.

Patient's Blood Pressure: {systolic}/{diastolic} mmHg (UNCONTROLLED - requires treatment plan)

Clinical Note Commands:
{commands_data}

Active Medications:
{medications_data}

Based on this information, determine:
1. Is there a documented treatment plan for blood pressure management?
2. If no treatment plan, is there a documented reason why?

Provide your analysis in JSON format."""

    # Use chat_with_json to get structured response
    result = llm.chat_with_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_retries=3
    )

    if result["success"]:
        return result["data"]
    else:
        log.error(f"LLM analysis failed: {result['error']}")
        return {
            "has_treatment_plan": False,
            "has_documented_reason": False,
            "explanation": f"LLM analysis failed: {result['error']}"
        }


def determine_treatment_code(analysis_result: dict) -> Optional[str]:
    """
    Determine the appropriate treatment billing code based on LLM analysis.

    Returns:
        HCPCS_G8753: Treatment plan documented
        HCPCS_G8754: No treatment plan, reason not given
        HCPCS_G8755: No treatment plan, documented reason
        None: Should not add treatment code
    """
    has_treatment_plan = analysis_result.get("has_treatment_plan", False)
    has_documented_reason = analysis_result.get("has_documented_reason", False)

    if has_treatment_plan:
        return HCPCS_G8753
    elif has_documented_reason:
        return HCPCS_G8755
    else:
        return HCPCS_G8754


def get_hypertension_related_assessments(note: Note, openai_api_key: Optional[str]) -> list[str]:
    """
    Get assessment IDs that are related to hypertension using LLM analysis.

    Args:
        note: Note object to get assessments from
        openai_api_key: OpenAI API key for LLM analysis

    Returns:
        List of assessment IDs (as strings) that are hypertension-related
    """
    from bp_cpt2.llm_openai import LlmOpenai

    # Get all assessments for this note
    assessments = list(Assessment.objects.filter(note_id=note.dbid, deleted=False))
    if not assessments:
        return []

    # Build assessment data for LLM analysis
    assessment_data = []
    for assessment in assessments:
        if not assessment.condition:
            continue

        # Get condition codings
        codings = []
        try:
            condition_codings = assessment.condition.codings.filter(system='ICD-10')
            for coding in condition_codings:
                coding_info = {
                    "system": coding.system if hasattr(coding, 'system') else '',
                    "code": coding.code if hasattr(coding, 'code') else '',
                    "display": coding.display if hasattr(coding, 'display') else ''
                }
                codings.append(coding_info)
        except (AttributeError, Exception):
            pass

        if codings:
            assessment_entry = {
                "assessment_id": str(assessment.id),
                "codings": codings
            }
            assessment_data.append(assessment_entry)

    if not assessment_data:
        return []

    # Use LLM to identify hypertension-related assessments
    try:
        if not openai_api_key:
            log.warning(f"Note {note.id} - OPENAI_API_KEY not configured, cannot filter hypertension-related assessments")
            return []

        client = LlmOpenai(api_key=openai_api_key)

        system_prompt = "You are a medical coding assistant that helps identify hypertension-related diagnoses."
        user_prompt = f"""Analyze the following assessments and determine which ones are clearly related to hypertension (high blood pressure).

Assessments to analyze:
{assessment_data}

Return a JSON object with a single key "hypertension_related_assessment_ids" containing an array of assessment_id strings that are related to hypertension.

Examples of hypertension-related conditions:
- Essential hypertension
- Hypertensive heart disease
- Hypertensive chronic kidney disease
- Secondary hypertension
- Hypertensive crisis
- Renovascular hypertension
- And other conditions that are directly caused by or related to high blood pressure

Do NOT include conditions that are merely risk factors for hypertension (like diabetes, obesity) or complications that can occur with many conditions.

If none of the assessments are hypertension-related, return an empty array."""

        response = client.chat_with_json(system_prompt=system_prompt, user_prompt=user_prompt, max_retries=2)

        if response and isinstance(response, dict) and response.get('success'):
            response_data = response.get('data', {})
            related_ids = response_data.get('hypertension_related_assessment_ids', [])

            if isinstance(related_ids, list):
                log.info(f"Note {note.id} - Found {len(related_ids)} hypertension-related assessments")
                return related_ids
            else:
                log.warning(f"Note {note.id} - LLM returned invalid format for hypertension_related_assessment_ids")
                return []
        else:
            error_msg = response.get('error', 'Unknown error') if isinstance(response, dict) else 'Invalid response format'
            log.warning(f"Note {note.id} - LLM request failed: {error_msg}")
            return []

    except Exception as e:
        log.error(f"Note {note.id} - Error identifying hypertension-related assessments: {e}")
        return []


def process_bp_billing_for_note(
    note: Note,
    openai_api_key: Optional[str],
    include_treatment_codes: bool = True,
    was_just_locked: bool = False
) -> list[Effect]:
    """
    Process BP-related billing codes for a note.

    This function handles:
    1. Updating assessment links for existing BP billing codes
    2. Analyzing treatment plans for uncontrolled BP (if include_treatment_codes is True)
    3. Adding appropriate treatment plan codes (if include_treatment_codes is True)
    4. Optionally pushing charges (if was_just_locked is True)

    Args:
        note: Note object to process
        openai_api_key: OpenAI API key for LLM analysis
        include_treatment_codes: Whether to analyze and add treatment plan codes
        was_just_locked: Whether this is being called immediately after a note lock event
                         (controls both cache deduplication and charge pushing)

    Returns:
        List of Effect objects
    """
    from canvas_sdk.effects.note import Note as NoteEffect

    # Check cache for duplicate lock processing
    if was_just_locked:
        try:
            cache = get_cache()
            cache_key = f"lock:{note.id}"

            if cache_key in cache:
                log.info(f"Note {note.id} - Already processed for lock event, skipping duplicate")
                return []

            # Set cache key with ISO timestamp, expires after 5 minutes (300 seconds)
            cache.set(cache_key, datetime.now().isoformat(), timeout_seconds=300)
            log.info(f"Note {note.id} - Marked as processed for lock event")
        except RuntimeError:
            # Cache is not available in test environment, continue processing
            log.debug(f"Note {note.id} - Cache not available (test environment?), skipping deduplication")
            pass

    patient = note.patient
    log.info(f"Processing note {note.id} for patient {patient.id}")

    effects = []

    # Get hypertension-related assessments ONCE for all operations
    hypertension_assessments = get_hypertension_related_assessments(note, openai_api_key)

    # Get existing BP-related billing line items
    existing_bp_billing_items = BillingLineItem.objects.filter(
        note_id=note.dbid,
        cpt__in=BP_RELATED_CODES
    )

    if existing_bp_billing_items.exists():
        log.info(f"Note {note.id} - Found {existing_bp_billing_items.count()} BP billing codes to update with {len(hypertension_assessments)} hypertension-related assessments")

        for billing_item in existing_bp_billing_items:
            # Get existing assessment IDs from the billing item
            existing_assessment_ids = []

            # TODO: Get the billing line item's current assessments to merge with
            # BUG: https://github.com/canvas-medical/canvas-plugins/issues/1262
            # TODO: Unskip the skipped tests when this is fixed
            # TODO: The following represents a gesture of how one might hope it would work
            # try:
            #     if hasattr(billing_item, 'assessment_ids'):
            #         assessments = billing_item.assessment_ids
            #         if assessments is not None:
            #             if isinstance(assessments, list):
            #                 existing_assessment_ids = [str(aid) for aid in assessments if aid]
            #             elif isinstance(assessments, str):
            #                 # Handle comma-separated string format
            #                 existing_assessment_ids = [aid.strip() for aid in assessments.split(',') if aid.strip()]
            # except Exception as e:
            #     log.warning(f"Could not retrieve existing assessment_ids for billing item {billing_item.id}: {e}")
            #     existing_assessment_ids = []

            # Combine existing assessments with new hypertension-related assessments (unique set)
            all_assessments = [str(aid) for aid in existing_assessment_ids] + [str(aid) for aid in hypertension_assessments]
            combined_assessment_ids = list(set(all_assessments))

            update_effect = UpdateBillingLineItem(
                billing_line_item_id=str(billing_item.id),
                assessment_ids=combined_assessment_ids
            )
            effects.append(update_effect.apply())
            log.info(f"Updated billing code {billing_item.cpt} with {len(combined_assessment_ids)} total assessments (preserved {len(existing_assessment_ids)} existing, {len(hypertension_assessments)} hypertension-related) for note {note.id}")

    # Get BP readings for this note
    systolic, diastolic = get_blood_pressure_readings(note)

    # Only analyze treatment codes if enabled
    if not include_treatment_codes:
        log.info(f"Note {note.id} - Treatment plan codes disabled, skipping treatment plan analysis")
        return effects

    # Only add treatment codes if BP is uncontrolled (>= 140/90)
    if systolic is None or diastolic is None:
        log.info(f"No BP readings found for note {note.id}, skipping treatment plan analysis")
        return effects

    if systolic < 140 and diastolic < 90:
        log.info(f"BP is controlled ({systolic}/{diastolic}), no treatment plan codes needed")
        return effects

    log.info(f"BP is uncontrolled ({systolic}/{diastolic}), analyzing treatment plan")

    # Prepare data for LLM analysis
    commands_data = prepare_note_commands_data(note)
    medications_data = prepare_medications_data(str(patient.id))

    # Analyze with LLM
    analysis_result = analyze_treatment_plan(
        openai_api_key=openai_api_key,
        commands_data=commands_data,
        medications_data=medications_data,
        systolic=systolic,
        diastolic=diastolic
    )

    log.info(f"Treatment plan analysis result: {analysis_result}")

    # Determine appropriate treatment code
    treatment_code = determine_treatment_code(analysis_result)

    if not treatment_code:
        log.info("No treatment code determined")
        return effects

    # Check if this code already exists
    existing_codes = set(
        BillingLineItem.objects.filter(
            note_id=note.dbid
        ).values_list("cpt", flat=True)
    )

    if treatment_code in existing_codes:
        log.info(f"Treatment code {treatment_code} already exists for note {note.id}, skipping")
        return effects

    # Create billing line item effect
    billing_item = AddBillingLineItem(
        note_id=str(note.id),
        cpt=treatment_code,
        units=1,
        assessment_ids=hypertension_assessments,
        modifiers=[]
    )

    log.info(f"Added treatment billing code {treatment_code} for patient {patient.id}: {analysis_result.get('explanation')}")

    effects.append(billing_item.apply())

    # Only push charges if note was just locked and is billable
    if was_just_locked and note.note_type_version and note.note_type_version.is_billable:
        note_effect = NoteEffect(instance_id=str(note.id))
        effects.append(note_effect.push_charges())

    return effects
