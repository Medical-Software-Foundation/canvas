"""Patient matching service using extracted lab report demographics."""

from __future__ import annotations

from datetime import date
from typing import Any

from canvas_sdk.v1.data.patient import Patient
from logger import log

from extend_lab_intake.services.llm_client import LLMClient


class PatientMatchResult:
    """Result of patient matching operation."""

    def __init__(
        self,
        patient_id: str | None,
        confidence: str,  # "high", "medium", "low", "none"
        match_details: str,
        candidates_considered: int,
        patient_name: str | None = None,
    ) -> None:
        self.patient_id = patient_id
        self.confidence = confidence
        self.match_details = match_details
        self.candidates_considered = candidates_considered
        self.patient_name = patient_name


class ExtractedDemographics:
    """Demographics extracted from lab report."""

    def __init__(
        self,
        first_name: str | None = None,
        last_name: str | None = None,
        date_of_birth: date | None = None,
        mrn: str | None = None,
        ssn_last_four: str | None = None,
        phone: str | None = None,
        address: str | None = None,
    ) -> None:
        self.first_name = first_name
        self.last_name = last_name
        self.date_of_birth = date_of_birth
        self.mrn = mrn
        self.ssn_last_four = ssn_last_four
        self.phone = phone
        self.address = address

    @classmethod
    def from_extend_output(cls, output: dict[str, Any]) -> "ExtractedDemographics":
        """Parse demographics from Extend AI extraction output.

        The output structure depends on the Extend processor configuration.
        This method handles common field names.
        """
        from logger import log

        log.info(f"Parsing demographics from output keys: {list(output.keys())}")

        # Extend AI wraps extraction results in a "value" key
        if "value" in output and isinstance(output["value"], dict):
            output = output["value"]
            log.info(f"Unwrapped 'value' - new keys: {list(output.keys())}")

        # Try various common field names for patient demographics
        patient_info = output.get("patient", output)

        # Parse name - handle both combined and separate name fields
        first_name = None
        last_name = None

        # Check for separate name fields first
        first_name = (
            patient_info.get("first_name")
            or patient_info.get("firstName")
            or patient_info.get("patient_first_name")
        )
        last_name = (
            patient_info.get("last_name")
            or patient_info.get("lastName")
            or patient_info.get("patient_last_name")
        )

        # If not found, try combined name field and split it
        if not first_name and not last_name:
            full_name = (
                patient_info.get("patient_name")
                or patient_info.get("patientName")
                or patient_info.get("name")
            )
            if full_name:
                log.info(f"Found combined patient name: {full_name}")
                parts = full_name.strip().split()
                if len(parts) >= 2:
                    first_name = parts[0]
                    last_name = " ".join(parts[1:])
                elif len(parts) == 1:
                    last_name = parts[0]

        # Parse date of birth
        dob = None
        dob_str = (
            patient_info.get("date_of_birth")
            or patient_info.get("dob")
            or patient_info.get("patient_dob")
            or patient_info.get("patientDob")
            or patient_info.get("birthDate")
            or patient_info.get("birth_date")
        )
        if dob_str:
            log.info(f"Found DOB string: {dob_str}")
            try:
                # Try various date formats
                from datetime import datetime

                for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y", "%Y/%m/%d"]:
                    try:
                        dob = datetime.strptime(str(dob_str), fmt).date()
                        break
                    except ValueError:
                        continue
            except Exception as e:
                log.warning(f"Failed to parse DOB: {e}")

        log.info(f"Parsed demographics: first_name={first_name}, last_name={last_name}, dob={dob}")

        return cls(
            first_name=first_name,
            last_name=last_name,
            date_of_birth=dob,
            mrn=patient_info.get("mrn") or patient_info.get("medical_record_number"),
            ssn_last_four=patient_info.get("ssn_last_four") or patient_info.get("ssn4"),
            phone=patient_info.get("phone") or patient_info.get("phone_number"),
            address=patient_info.get("address"),
        )


class PatientMatcher:
    """Service to match extracted demographics to Canvas patients."""

    PATIENT_MATCH_SYSTEM_PROMPT = """You are a patient matching assistant for a healthcare system.
Your job is to determine if any of the candidate patients match the demographics from a lab report.

IMPORTANT: Patient matching must be accurate to avoid medical errors.
- A "high" confidence match requires exact name match AND exact date of birth match
- A "medium" confidence match requires close name match (allowing for typos/nicknames) AND exact date of birth
- A "low" confidence match requires partial matches that suggest the same person
- Return "none" if you cannot confidently identify a match

Respond with JSON in this format:
```json
{
    "matched_patient_id": "patient-uuid-here or null if no match",
    "confidence": "high|medium|low|none",
    "reasoning": "Brief explanation of why this is/isn't a match"
}
```"""

    def __init__(self, llm_client: LLMClient) -> None:
        """Initialize the patient matcher.

        Args:
            llm_client: LLM client for ambiguous match resolution
        """
        self.llm_client = llm_client

    def match_patient(
        self, demographics: ExtractedDemographics
    ) -> PatientMatchResult:
        """Match extracted demographics to a Canvas patient.

        Strategy:
        1. If MRN is present, try exact MRN lookup
        2. Query patients by name and DOB
        3. If multiple candidates, use LLM to select best match
        4. Return match result with confidence score

        Args:
            demographics: Extracted demographics from lab report

        Returns:
            PatientMatchResult with patient_id (or None) and confidence
        """
        log.info(
            f"Matching patient: {demographics.first_name} {demographics.last_name}, "
            f"DOB: {demographics.date_of_birth}"
        )

        # Strategy 1: MRN lookup (highest confidence)
        if demographics.mrn:
            mrn_match = self._match_by_mrn(demographics.mrn)
            if mrn_match:
                patient_name = f"{mrn_match.first_name} {mrn_match.last_name}".strip()
                return PatientMatchResult(
                    patient_id=str(mrn_match.id),
                    confidence="high",
                    match_details=f"Exact MRN match: {demographics.mrn}",
                    candidates_considered=1,
                    patient_name=patient_name or None,
                )

        # Strategy 2: Name + DOB query
        candidates = self._find_candidates(demographics)

        if not candidates:
            return PatientMatchResult(
                patient_id=None,
                confidence="none",
                match_details="No matching patients found",
                candidates_considered=0,
            )

        if len(candidates) == 1:
            patient = candidates[0]
            confidence = self._calculate_confidence(demographics, patient)
            patient_name = f"{patient.first_name} {patient.last_name}".strip()
            return PatientMatchResult(
                patient_id=str(patient.id),
                confidence=confidence,
                match_details=f"Single candidate: {patient.first_name} {patient.last_name}",
                candidates_considered=1,
                patient_name=patient_name or None,
            )

        # Strategy 3: Multiple candidates - use LLM to disambiguate
        return self._llm_match(demographics, candidates)

    def _match_by_mrn(self, mrn: str) -> Patient | None:
        """Look up patient by MRN."""
        try:
            # Canvas stores MRN in patient external_identifiers
            # This query depends on how MRN is stored in the Canvas instance
            patients = Patient.objects.filter(
                external_identifiers__value=mrn, external_identifiers__system__contains="mrn"
            ).all()
            if patients and len(patients) == 1:
                return patients[0]
        except Exception as e:
            log.warning(f"MRN lookup failed: {e}")
        return None

    def _find_candidates(self, demographics: ExtractedDemographics) -> list[Patient]:
        """Find candidate patients matching demographics."""
        candidates: list[Patient] = []

        try:
            # Build query based on available demographics
            queryset = Patient.objects.all()

            # Filter by DOB if available (strongest filter)
            if demographics.date_of_birth:
                queryset = queryset.filter(birth_date=demographics.date_of_birth)

            # Filter by name if available
            if demographics.last_name:
                # Use case-insensitive contains for flexibility
                queryset = queryset.filter(
                    last_name__icontains=demographics.last_name[:3]  # First 3 chars
                )

            # Limit candidates to prevent huge queries
            candidates = list(queryset[:50])

            # If we have first name, further filter in Python for flexibility
            if demographics.first_name and candidates:
                first_name_lower = demographics.first_name.lower()
                candidates = [
                    p
                    for p in candidates
                    if p.first_name
                    and (
                        p.first_name.lower().startswith(first_name_lower[:2])
                        or first_name_lower.startswith(p.first_name.lower()[:2])
                    )
                ]

        except Exception as e:
            log.error(f"Patient query failed: {e}")

        return candidates

    def _calculate_confidence(
        self, demographics: ExtractedDemographics, patient: Patient
    ) -> str:
        """Calculate match confidence for a single candidate."""
        score = 0

        # DOB match is worth 40 points
        if demographics.date_of_birth and patient.birth_date:
            if demographics.date_of_birth == patient.birth_date:
                score += 40

        # Last name match is worth 30 points
        if demographics.last_name and patient.last_name:
            if demographics.last_name.lower() == patient.last_name.lower():
                score += 30
            elif demographics.last_name.lower() in patient.last_name.lower():
                score += 15

        # First name match is worth 30 points
        if demographics.first_name and patient.first_name:
            if demographics.first_name.lower() == patient.first_name.lower():
                score += 30
            elif demographics.first_name.lower()[:3] == patient.first_name.lower()[:3]:
                score += 15

        if score >= 90:
            return "high"
        elif score >= 60:
            return "medium"
        elif score >= 30:
            return "low"
        return "none"

    def _llm_match(
        self, demographics: ExtractedDemographics, candidates: list[Patient]
    ) -> PatientMatchResult:
        """Use LLM to match when multiple candidates exist."""
        candidates_desc = []
        for p in candidates[:10]:  # Limit to 10 candidates for LLM
            candidates_desc.append(
                f"- ID: {p.id}, Name: {p.first_name} {p.last_name}, "
                f"DOB: {p.birth_date}"
            )

        user_prompt = f"""Lab Report Demographics:
- First Name: {demographics.first_name or 'Unknown'}
- Last Name: {demographics.last_name or 'Unknown'}
- Date of Birth: {demographics.date_of_birth or 'Unknown'}
- MRN: {demographics.mrn or 'Not provided'}
- Phone: {demographics.phone or 'Not provided'}

Candidate Patients:
{chr(10).join(candidates_desc)}

Which patient, if any, matches these demographics?"""

        result = self.llm_client.chat_with_json(
            self.PATIENT_MATCH_SYSTEM_PROMPT, user_prompt
        )

        if not result["success"]:
            log.warning(f"LLM match failed: {result['error']}")
            return PatientMatchResult(
                patient_id=None,
                confidence="none",
                match_details=f"LLM matching failed: {result['error']}",
                candidates_considered=len(candidates),
            )

        data = result["data"]
        matched_id = data.get("matched_patient_id")

        # Look up patient name if we have a match
        patient_name = None
        if matched_id:
            for candidate in candidates:
                if str(candidate.id) == matched_id:
                    patient_name = f"{candidate.first_name} {candidate.last_name}".strip()
                    break

        return PatientMatchResult(
            patient_id=matched_id,
            confidence=data.get("confidence", "none"),
            match_details=data.get("reasoning", "LLM-based match"),
            candidates_considered=len(candidates),
            patient_name=patient_name,
        )
