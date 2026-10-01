"""Who a fax went to or came from: the contact card and the contact directory match."""

from dataclasses import dataclass
from typing import Any

from canvas_sdk.v1.data import ServiceProvider

from failed_fax_dashboard.services.sources import SourceSpec, walk
from failed_fax_dashboard.services.util import chunked, last_ten

DIRECTORY_SOURCE = "Matched in your contact directory"
MATCH_CHUNK = 100


@dataclass(frozen=True)
class Contact:
    """What the contact card shows."""

    name: str
    specialty: str
    practice: str
    phone: str
    fax: str
    address: str
    source: str

    def as_dict(self) -> dict[str, str]:
        """The contact as the dashboard receives it."""
        return {
            "name": self.name,
            "specialty": self.specialty,
            "practice": self.practice,
            "phone": self.phone,
            "fax": self.fax,
            "address": self.address,
            "source": self.source,
        }


def provider_name(provider: ServiceProvider) -> str:
    """A person's full name, or the organization's name (organizations have no last name)."""
    if provider.last_name:
        return f"{provider.first_name} {provider.last_name}".strip()
    return provider.first_name or provider.practice_name or ""


def contact_from_provider(provider: ServiceProvider, source: str) -> Contact:
    """Build a contact card from a directory entry."""
    return Contact(
        name=provider_name(provider),
        specialty=provider.specialty or "",
        practice=provider.practice_name or "",
        phone=provider.business_phone or "",
        fax=provider.business_fax or "",
        address=provider.business_address or "",
        source=source,
    )


def _pattern(digits: str) -> str:
    """A regex that matches ``digits`` at the end of a number however it is punctuated."""
    return r"\D*".join(digits) + r"\D*$"


def directory_matches(numbers: list[str]) -> dict[str, ServiceProvider]:
    """Directory entries by last 10 digits of fax number, only where exactly one entry matches.

    A match is an active ``ServiceProvider`` whose ``business_fax`` ends in the same 10
    digits. A number shared by two entries is left out because there is no telling which
    one was meant.
    """
    wanted = sorted({last_ten(number) for number in numbers if len(last_ten(number)) == 10})
    found: dict[str, list[ServiceProvider]] = {}
    for chunk in chunked(wanted, MATCH_CHUNK):
        regex = "|".join(f"(?:{_pattern(digits)})" for digits in chunk)
        providers = ServiceProvider.objects.filter(is_active=True, business_fax__regex=regex)
        for provider in providers:
            digits = last_ten(provider.business_fax)
            if digits in chunk:
                found.setdefault(digits, []).append(provider)
    return {digits: matches[0] for digits, matches in found.items() if len(matches) == 1}


def sent_contact(
    spec: SourceSpec, event: Any, number: str, directory: ServiceProvider | None
) -> Contact | None:
    """The recipient of a sent fax, taken from the item when it names one."""
    named = walk(event, spec.contact_path)
    if named is not None:
        return contact_from_provider(named, spec.contact_source)
    lab_name = walk(event, spec.lab_name_path)
    if lab_name:
        return Contact(
            name=lab_name,
            specialty=directory.specialty or "" if directory else "",
            practice="",
            phone=directory.business_phone or "" if directory else "",
            fax=number,
            address=directory.business_address or "" if directory else "",
            source=spec.contact_source,
        )
    if directory is not None:
        return contact_from_provider(directory, DIRECTORY_SOURCE)
    return None
