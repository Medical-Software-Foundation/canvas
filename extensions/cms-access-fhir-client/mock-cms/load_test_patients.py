"""Load the 5 CMS ACCESS synthetic test patients into allison-training.

Reads credentials from ~/.canvas/credentials.ini and posts Patient resources
to the Canvas FHIR API. Idempotent — skips MBIs that already exist.

Run:
    uv run python load_test_patients.py
"""
from __future__ import annotations

import configparser
import sys
from pathlib import Path

import httpx

HOST = "allison-training"
EMR_BASE_URL = f"https://{HOST}.canvasmedical.com"
FHIR_BASE_URL = f"https://fumage-{HOST}.canvasmedical.com"
TOKEN_URL = f"{EMR_BASE_URL}/auth/token/"
PATIENT_URL = f"{FHIR_BASE_URL}/Patient"
MBI_SYSTEM = "http://hl7.org/fhir/sid/us-mbi"

TEST_PATIENTS = [
    {"mbi": "3M88TE3HG30", "first": "XRESIDEE", "last": "XDEWAR FREEMYER", "dob": "1964-01-17"},
    {"mbi": "1CH4TE0XG00", "first": "XZHENWEN", "last": "XDUNCAN-PETER", "dob": "1960-04-04"},
    {"mbi": "7VX7TE9CQ10", "first": "XARKRA", "last": "XDEGAY", "dob": "1946-03-14"},
    {"mbi": "4YT9TE4CM20", "first": "XPAVOLO", "last": "XPAZOUR", "dob": "1939-06-22"},
    {"mbi": "2GD0TE2GF90", "first": "XNIBBY", "last": "XAROCHA MAYOR", "dob": "1949-04-10"},
]


def get_creds() -> tuple[str, str]:
    cfg = configparser.ConfigParser()
    cfg.read(Path.home() / ".canvas" / "credentials.ini")
    return cfg[HOST]["client_id"], cfg[HOST]["client_secret"]


def get_token(client_id: str, client_secret: str) -> str:
    r = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def find_by_mbi(token: str, mbi: str) -> str | None:
    r = httpx.get(
        PATIENT_URL,
        params={"identifier": f"{MBI_SYSTEM}|{mbi}"},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/fhir+json"},
        timeout=30,
    )
    r.raise_for_status()
    bundle = r.json()
    entries = bundle.get("entry", [])
    if entries:
        return entries[0]["resource"]["id"]
    return None


def create_patient(token: str, p: dict) -> str:
    body = {
        "resourceType": "Patient",
        "extension": [
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex", "valueCode": "UNK"},
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
             "extension": [{"url": "text", "valueString": "UNK"}]},
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
             "extension": [{"url": "text", "valueString": "UNK"}]},
        ],
        "identifier": [
            {"system": MBI_SYSTEM, "value": p["mbi"]},
        ],
        "active": True,
        "name": [{"use": "official", "family": p["last"], "given": [p["first"]]}],
        "birthDate": p["dob"],
        "gender": "unknown",
    }
    r = httpx.post(
        PATIENT_URL,
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        },
        timeout=30,
    )
    if not r.is_success:
        raise RuntimeError(f"POST Patient failed {r.status_code}: {r.text}")
    location = r.headers.get("Location", "")
    return location.rsplit("/", 1)[-1] if location else r.json().get("id", "")


def main() -> int:
    client_id, client_secret = get_creds()
    print(f"Authenticating to {TOKEN_URL}...")
    token = get_token(client_id, client_secret)
    print(f"OK — token length {len(token)}\n")

    for p in TEST_PATIENTS:
        existing = find_by_mbi(token, p["mbi"])
        if existing:
            print(f"SKIP  {p['mbi']}  {p['first']} {p['last']}  (exists, id={existing})")
            continue
        new_id = create_patient(token, p)
        print(f"CREATE {p['mbi']}  {p['first']} {p['last']}  → id={new_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
