"""Whether a screening's order code means anything to *this* practice.

**The problem this exists to make visible.** A protocol card's order button
stages a command, and Canvas resolves the configured code against the practice's
own catalog for that command - the imaging picker, the Perform picker, the lab
compendium. A code in the wrong terminology, or simply absent from that
catalog, resolves to nothing and the order opens with every field empty. It
fails **silently**: the button works, the command appears, and only the person
who has to fill the form in finds out.

That cost this project five deploys. The mammogram seed ordered imaging with
LOINC ``24606-6`` and staged an empty order every time, while the bone-density
seed ordered imaging with CPT ``77080`` and pre-filled correctly. Same command,
same code path. The catalog is keyed on CPT, and nothing anywhere said so.

So: read the catalogs and say so in the editor, at configuration time, instead
of leaving a practice to discover it by ordering something and watching the form
open blank. It is the order-side half of showing which codes count as done, and
the same answer to the client's *"how can we know without a developer having to
answer every time?"*

Two rules shape all of this, and both are about not crying wolf:

* **An empty catalog means "cannot tell", never "not found".** If the table has
  no rows at all - not loaded on this instance, not readable from here - every
  code would look unresolvable and the editor would warn about all of them. A
  warning that fires on everything is one a practice learns to ignore, which
  would cost us the warnings that are real.
* **Any failure is silent.** This runs on the page that edits the rules; it must
  never be what stops that page loading.
"""

from typing import Any

from canvas_sdk.v1.data import ChargeDescriptionMaster, LabPartnerTest
from django.db.models import Q
from logger import log

# Which catalog backs which command. The imaging picker and the Perform picker
# both resolve against the charge master - which is why a CPT code works in
# both and a LOINC code works in neither. `refer`, `instruct`, `plan` and `task`
# carry no code field at all (ORDER_COMMANDS[...].code_field is None), so there
# is nothing to resolve and nothing to warn about.
CATALOG_CHARGE = "charge_master"
CATALOG_LAB = "lab_compendium"

_CATALOG_FOR_COMMAND = {
    "imaging_order": CATALOG_CHARGE,
    "perform": CATALOG_CHARGE,
    "lab_order": CATALOG_LAB,
}


def _wanted(screenings: list[dict]) -> dict[str, set[str]]:
    """The codes to check, grouped by the catalog that would have to know them."""
    wanted: dict[str, set[str]] = {}
    for screening in screenings:
        code = str(screening.get("order_code") or "").strip()
        if not code:
            continue
        # A command absent from the mapping has no code field to pre-fill -
        # `refer`, `instruct`, `plan` and `task` - so there is nothing to
        # resolve and nothing to warn about.
        catalog = _CATALOG_FOR_COMMAND.get(str(screening.get("order_command") or ""))
        if catalog:
            wanted.setdefault(catalog, set()).add(code)
    return wanted


def _missing_from_charge_master(codes: set[str]) -> set[str]:
    """Which of these the practice's charge master does not carry."""
    found = set(
        ChargeDescriptionMaster.objects.filter(cpt_code__in=codes).values_list(
            "cpt_code", flat=True
        )
    )
    missing = codes - found
    # Only now is the emptiness question worth a query, and only when we are
    # otherwise about to warn.
    if missing and not ChargeDescriptionMaster.objects.exists():
        return set()
    return missing


def _missing_from_lab_compendium(codes: set[str]) -> set[str]:
    """Which of these the practice's lab compendium does not carry.

    A lab test is orderable by the partner's own order code or by its CPT code,
    so either matching is enough for the picker to find it.
    """
    rows = LabPartnerTest.objects.filter(
        Q(order_code__in=codes) | Q(cpt_code__in=codes)
    ).values_list("order_code", "cpt_code")
    found = {value for row in rows for value in row if value}
    missing = codes - found
    if missing and not LabPartnerTest.objects.exists():
        return set()
    return missing


_READERS = {
    CATALOG_CHARGE: _missing_from_charge_master,
    CATALOG_LAB: _missing_from_lab_compendium,
}


def unresolvable_order_codes(screenings: list[dict]) -> list[str]:
    """Order codes that match nothing in this practice's own order catalogs.

    One query per catalog for the whole document, and a second only when a code
    is missing and the catalog's emptiness has to be ruled out - so a practice
    whose codes all resolve pays two queries however many screenings it has.

    Returns an empty list whenever the answer cannot be trusted: nothing to
    check, a catalog that is empty, or a read that failed. **Saying nothing is
    always safe here; a false warning is not.**
    """
    missing: set[str] = set()
    for catalog, codes in _wanted(screenings).items():
        try:
            missing |= _READERS[catalog](codes)
        except Exception as exc:
            log.warning(f"preventive_screenings: could not read the {catalog} ({exc})")
    return sorted(missing)


def order_code_warnings(config: dict[str, Any]) -> list[str]:
    """The same answer for a whole config document, for the editor."""
    screenings = config.get("screenings")
    return unresolvable_order_codes(screenings if isinstance(screenings, list) else [])
