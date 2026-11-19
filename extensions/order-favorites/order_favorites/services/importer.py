"""Check and import practice favorites from CSV.

One row per favorite, prescriptions and labs in the same file:

    type,name,details
    rx,Atorvastatin 20 mg · 90 day,atorvastatin 20 mg tablet|Take 1 tablet by mouth at bedtime|90|90|tablet|3
    lab,Vitamin D check,Generic Lab|Vitamin D 25-OH|E55.9|no|

details is split on "|":
    rx:  medication | sig | days supply | quantity | unit | refills | pharmacy NCPDP id
         (only the medication is required; leave the others empty to fill in on the command)
    lab: lab partner | tests | diagnoses (optional) | fasting yes/no (optional) | comment (optional)
Several tests or diagnoses are separated with ";". A medication is matched by its exact FDB name or
FDB code, a test by its order code or exact name. Nothing is guessed: an ambiguous or unknown value
fails the row with the reason.

The sandbox has no csv module, so lines are split by hand (carried over from lab_order_favorites).
Quoted values may contain commas; a value can't span lines.
"""

from __future__ import annotations

from typing import Any

from order_favorites.services.catalog import resolve_partner, resolve_tests
from order_favorites.services.favorites import Invalid, clean_favorite
from order_favorites.services.lookups import LookupFailed, find_diagnosis, find_medication, icd10_display

MAX_ROWS = 200
TRUE_VALUES = {"yes", "y", "true", "1"}
FALSE_VALUES = {"no", "n", "false", "0", ""}
TEMPLATE = (
    "type,name,details\n"
    "rx,Example prescription,medication name|sig (optional)|days supply (optional)|quantity (optional)|unit (optional)|refills (optional)|pharmacy NCPDP id (optional)\n"
    "lab,Example lab,lab partner|test code or name; another test|ICD-10 code; another code|yes or no|comment\n"
)


def split_line(line: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_quotes:
            if ch == '"' and i + 1 < len(line) and line[i + 1] == '"':
                current.append('"')
                i += 2
                continue
            if ch == '"':
                in_quotes = False
            else:
                current.append(ch)
        elif ch == '"' and not current:
            in_quotes = True
        elif ch == ",":
            fields.append("".join(current))
            current = []
        elif ch not in ("\r", "\n"):
            current.append(ch)
        i += 1
    fields.append("".join(current))
    return fields


def _parts(details: str, count: int) -> list[str]:
    parts = [p.strip() for p in details.split("|")]
    return parts + [""] * (count - len(parts))


def _multi(value: str) -> list[str]:
    return [p.strip() for p in value.split(";") if p.strip()]


def _rx_body(details: str, cache: dict[str, Any]) -> dict[str, Any]:
    med_name, sig, days, qty, unit, refills, pharmacy = _parts(details, 7)[:7]
    if not med_name:
        raise Invalid("The medication is missing.")
    if med_name not in cache:
        cache[med_name] = find_medication(med_name)
    med, reason = cache[med_name]
    if med is None:
        raise Invalid(reason[0].upper() + reason[1:] + ".")
    wanted = unit.strip().lower()
    matches = [u for u in med["units"] if u["description"].lower() in (wanted, wanted.rstrip("s"))]
    if wanted and not matches:
        offered = ", ".join(u["description"] for u in med["units"]) or "none"
        raise Invalid(f"{med['name']} isn't dispensed by \"{unit}\". Units offered: {offered}.")
    chosen = matches[0] if matches else {"description": "", "representative_ndc": "", "ncpdp_quantity_qualifier_code": ""}
    return {
        "fdb_code": med["fdb_code"],
        "medication": med["name"],
        "sig": sig,
        "days_supply": days,
        "quantity": qty,
        "unit": chosen["description"],
        "representative_ndc": chosen["representative_ndc"],
        "ncpdp_quantity_qualifier_code": chosen["ncpdp_quantity_qualifier_code"],
        "refills": refills,
        "pharmacy_ncpdp_id": pharmacy,
        "pharmacy_name": f"NCPDP {pharmacy}" if pharmacy else "",
    }


def _lab_body(details: str, cache: dict[str, Any]) -> dict[str, Any]:
    partner_value, tests_value, dx_value, fasting_value, comment = _parts(details, 5)[:5]
    partner, reason = resolve_partner(partner_value)
    if partner is None:
        raise Invalid(reason[0].upper() + reason[1:] + ".")
    tests, missing, shared = resolve_tests(str(partner.id), _multi(tests_value))
    problems = []
    if shared:
        problems.append(f"{partner.name} has more than one test named {', '.join(shared)}. Use its order code instead.")
    if missing:
        problems.append(f"{partner.name} has no test with the code or name {', '.join(missing)}.")
    if problems:
        raise Invalid(" ".join(problems))
    diagnoses = []
    for code in _multi(dx_value):
        if code not in cache:
            cache[code] = find_diagnosis(code)
        if cache[code] is None:
            raise Invalid(f"{code} isn't an ICD-10 code.")
        diagnoses.append(cache[code])
    fasting = fasting_value.strip().lower()
    if fasting not in TRUE_VALUES | FALSE_VALUES:
        raise Invalid("Fasting must be yes or no.")
    return {
        "lab_partner_id": str(partner.id),
        "tests": tests,
        "diagnoses": diagnoses,
        "fasting": fasting in TRUE_VALUES,
        "comment": comment,
    }


def summary(kind: str, details: dict[str, Any]) -> str:
    if kind == "rx":
        return str(details["medication"]) + (f" · {details['days_supply']} days" if details["days_supply"] else "")
    count = len(details["tests"])
    text = f"{details['lab_partner_name']} · {count} test{'' if count == 1 else 's'}"
    if details["diagnoses"]:
        text += " · " + ", ".join(icd10_display(d["code"]) for d in details["diagnoses"])
    return text


def check_csv(text: str) -> dict[str, Any]:
    """Check every row. Returns {rows: [{row, name, ok, reason, summary, favorite}], error}."""
    lines = [line for line in text.lstrip("﻿").splitlines() if line.strip()]
    if not lines:
        return {"rows": [], "error": "Paste or upload a CSV first."}
    header = [h.strip().lower() for h in split_line(lines[0])]
    if header[:3] != ["type", "name", "details"]:
        return {"rows": [], "error": "The first line must be the header: type,name,details"}
    if len(lines) - 1 > MAX_ROWS:
        return {"rows": [], "error": f"Import at most {MAX_ROWS} rows at a time."}

    cache: dict[str, Any] = {}
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        cells = split_line(line)
        cells += [""] * (3 - len(cells))
        # An unquoted comma inside details splits it into more cells; put them back together.
        kind, name, details = cells[0].strip().lower(), cells[1].strip(), ",".join(cells[2:]).strip()
        row: dict[str, Any] = {"row": number, "name": name or "(no name)", "ok": False, "reason": "", "summary": ""}
        try:
            if kind not in ("rx", "lab"):
                raise Invalid("Type must be rx or lab.")
            body = _rx_body(details, cache) if kind == "rx" else _lab_body(details, cache)
            body["name"] = name
            kind, name, clean = clean_favorite(body, kind)
            row.update(ok=True, summary=summary(kind, clean), favorite={"kind": kind, "name": name, "details": clean})
        except Invalid as exc:
            row["reason"] = str(exc)
        except LookupFailed:
            row["reason"] = "Canvas's medication or diagnosis search didn't answer. Try again."
        rows.append(row)
    return {"rows": rows, "error": ""}
