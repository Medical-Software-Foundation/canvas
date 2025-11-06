from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from canvas_sdk.caching.plugins import get_cache
from logger import log
from typing import NamedTuple

from intake_agent.config import CACHE_TIMEOUT_SECONDS


class IntakeMessage(NamedTuple):
    role: str
    content: str
    timestamp: datetime

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> IntakeMessage:
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


class ProposedAppointment(NamedTuple):
    provider_id: str
    provider_name: str
    location_id: str
    location_name: str
    start_datetime: datetime
    duration: int

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "location_id": self.location_id,
            "location_name": self.location_name,
            "start_datetime": self.start_datetime,
            "duration": self.duration
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> ProposedAppointment:
        return cls(
            provider_id=data["provider_id"],
            provider_name=data["provider_name"],
            location_id=data["location_id"],
            location_name=data["location_name"],
            start_datetime=data["start_datetime"],
            duration=data["duration"],
        )

    def to_string(self) -> str:
        """
        Format the appointment in a natural, patient-facing way.

        Returns:
            Human-readable appointment description
        """
        # Format the datetime in a friendly way
        formatted_date = self.start_datetime.strftime("%A, %B %d")
        formatted_time = self.start_datetime.strftime("%I:%M %p").lstrip("0")

        # Build the string with provider, date/time, and location
        return f"{formatted_date} at {formatted_time} with {self.provider_name} at {self.location_name}"


class IntakeFieldInstructions:
        health_concerns = ""
        preferred_appointment = ""
        phone_number = ""
        phone_verified_timestamp = ""
        proposed_appointments = ""
        messages = ""
        target_fields_in_order = [
            "health_concerns", 
            "preferred_appointment",
            "phone_number",
            "phone_verified_timestamp",
            "proposed_appointments",
            "messages",
        ]


class IntakeSession(NamedTuple):
    session_id: str
    created_at: datetime
    patient_creation_pending: bool = False
    patient_id: str = ""
    patient_mrn: str = ""
    first_name: str = ""
    last_name: str = ""
    date_of_birth: datetime | None = None
    phone_number: str = ""
    phone_verification_code: str = ""
    phone_verified_timestamp: datetime | None = None
    health_concerns: str = ""
    proposed_appointments: list[ProposedAppointment] = []
    preferred_appointment: ProposedAppointment | None = None
    appointment_confirmation_timestamp: datetime | None = None
    policy_agreement_timestamp: datetime | None = None
    messages: list[IntakeMessage] = []

    def save(self):
        cache = get_cache()
        cache_key = f"intake_session:{self.session_id}"
        cache.set(cache_key, self.to_dict(), timeout_seconds=CACHE_TIMEOUT_SECONDS)

    def add_message(self, role: str, content: str) -> None:
        message = IntakeMessage(
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc)
        )
        self.messages.append(message)
        self.save()
        log.info(f"Added {role} message to session {self.session_id}")

    def internal_fields(self) -> list[str]:
        return [
            "session_id",
            "created_at",
            "patient_creation_pending",
            "patient_id",
            "patient_mrn",
            "phone_verification_code",
            "phone_verified_timestamp",
            "proposed_appointments",
            "appointment_confirmation_timestamp",
            "policy_agreement_timestamp",
            "messages"
        ]

    def target_fields_remaining(self) -> list[str]:
        target_fields_in_order = [
            ["health_concerns"], 
            ["proposed_appointments"],
            ["preferred_appointment"],
            ["phone_number"],
            ["phone_verified_timestamp"],
            ["first_name", "last_name", "date_of_birth"],
            ["policy_agreement_timestamp"],
            ["appointment_confirmation_timestamp"],
        ]
        remaining_field_groups = []
        for field_group in target_fields_in_order:
            fields_missing = []
            for field_name in field_group:
                field_value = getattr(self, field_name)
                if not field_value:
                    fields_missing.append(field_name)
            if fields_missing:
                remaining_field_groups.append(fields_missing)

        return remaining_field_groups

    def patient_exists(self) -> bool:
        return self.patient_id != ""

    def sufficient_data_to_create_patient(self) -> bool:
        return (
            self.first_name
            and self.last_name
            and self.date_of_birth
            and self.phone_verified
        )

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "patient_creation_pending": self.patient_creation_pending,
            "patient_id": self.patient_id,
            "patient_mrn": self.patient_mrn,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "phone_number": self.phone_number,
            "phone_verification_code": self.phone_verification_code,
            "phone_verified_timestamp": self.phone_verified_timestamp.isoformat() if self.phone_verified_timestamp else None,
            "health_concerns": self.health_concerns,
            "proposed_appointments": [a.to_dict() for a in self.proposed_appointments],
            "preferred_appointment": self.preferred_appointment.to_dict() if self.preferred_appointment else None,
            "appointment_confirmation_timestamp": self.appointment_confirmation_timestamp.isoformat() if self.appointment_confirmation_timestamp else None,
            "policy_agreement_timestamp": self.policy_agreement_timestamp.isoformat() if self.policy_agreement_timestamp else None,
            "messages": [m.to_dict() for m in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> IntakeSession:
        return cls(
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            patient_creation_pending=data["patient_creation_pending"],
            patient_id=data["patient_id"],
            patient_mrn=data["patient_mrn"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            date_of_birth=datetime.fromisoformat(data["date_of_birth"]) if data.get("date_of_birth") else None,
            phone_number=data["phone_number"],
            phone_verification_code=data.get("phone_verification_code", ""),
            phone_verified_timestamp=datetime.fromisoformat(data["phone_verified_timestamp"]) if data.get("phone_verified_timestamp") else None,
            health_concerns=data["health_concerns"],
            proposed_appointments=[ProposedAppointment.from_dict(a) for a in data.get("proposed_appointments", [])],
            preferred_appointment=ProposedAppointment.from_dict(data["preferred_appointment"]) if data.get("preferred_appointment") else None,
            appointment_confirmation_timestamp=datetime.fromisoformat(data["appointment_confirmation_timestamp"]) if data.get("appointment_confirmation_timestamp") else None,
            policy_agreement_timestamp=datetime.fromisoformat(data["policy_agreement_confirmed"]) if data.get("policy_agreement_confirmed") else None,
            messages=[IntakeMessage.from_dict(m) for m in data.get("messages", [])],
        )

    def messages_to_json(self) -> str:
        return json.dumps([m.to_dict() for m in self.messages])


class IntakeSessionManager:
    @classmethod
    def create_session(cls) -> IntakeSession:
        session = IntakeSession(
            session_id=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc)
        )
        session.save()
        log.info(f"Created new session: {session.session_id}")
        return session

    @classmethod
    def get_session(cls, session_id: str) -> IntakeSession:
        cache = get_cache()
        cache_key = f"intake_session:{session_id}"
        session_data = cache.get(cache_key)
        session = IntakeSession.from_dict(session_data)
        log.info(f"Retrieved session: {session.session_id}")
        return session
