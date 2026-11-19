"""The fixed menu of building blocks a screening rule is assembled from.

An admin configuring a screening never types a code, a code system or a Django
model name. They pick a "counts as done when" entry from this catalog, and the
catalog carries the two things the rest of the plugin needs: which kind of chart
record proves the screening happened (the *source*), and which codes in that
record mean it (a CMS/eCQM *value set* shipped with the SDK).

Three things live here, and nothing else does:

* ``SOURCES`` - the kinds of chart record a completion can be found in.
* ``VALUE_SETS`` - the curated code sets, each already paired with the source it
  belongs in, so the admin picks one thing rather than two that must agree.
* ``ORDER_COMMANDS`` - the commands a protocol card can offer to stage.

The value sets are a deliberately short, reviewed list rather than every set the
SDK ships (there are tens of thousands). A screening this list cannot express is
still configurable: a rule can carry its own codes instead of a value-set key,
which is how a practice adds something that is not a quality measure at all.
"""

# The sandbox does not expose the `type` builtin, so `type[ValueSet]` annotations
# would raise NameError when this module is loaded on the instance. Deferring
# annotation evaluation keeps them as documentation without evaluating them.
# `canvas validate` catches this; nothing else does.
from __future__ import annotations

from typing import Any, NamedTuple

from canvas_sdk.commands import (
    ImagingOrderCommand,
    InstructCommand,
    LabOrderCommand,
    PerformCommand,
    PlanCommand,
    ReferCommand,
    TaskCommand,
)
from canvas_sdk.value_set.v2026.assessment import FallsScreening, TobaccoUseScreening
from canvas_sdk.value_set.v2026.condition import (
    CongenitalOrAcquiredAbsenceOfCervix,
    HistoryOfBilateralMastectomy,
    MalignantNeoplasmOfColon,
)
from canvas_sdk.value_set.v2026.diagnostic_study import CtColonography, Mammography
from canvas_sdk.value_set.v2026.laboratory_test import (
    FecalOccultBloodTestFobt,
    HpvTest,
    PapTest,
    SdnaFitTest,
)
from canvas_sdk.value_set.v2026.procedure import (
    BilateralMastectomy,
    Colonoscopy,
    FlexibleSigmoidoscopy,
    HysterectomyWithNoResidualCervix,
    TotalColectomy,
)
from canvas_sdk.value_set.value_set import ValueSet

# --- Sources -----------------------------------------------------------------
#
# Each key names a kind of chart record. ``services.completion`` owns the query
# for each one; the two modules must agree on these strings, and a test holds
# them together.

SOURCE_IMAGING = "imaging_report"
SOURCE_LAB = "lab_result"
SOURCE_PROCEDURE = "procedure"
SOURCE_QUESTIONNAIRE = "questionnaire"
SOURCE_CONDITION = "condition"
SOURCE_REFERRAL = "referral_report"

# Phrased as they appear in the admin sentence: "...when there is a <label>".
SOURCES: dict[str, str] = {
    SOURCE_IMAGING: "imaging report",
    SOURCE_LAB: "lab result",
    SOURCE_PROCEDURE: "recorded procedure",
    SOURCE_QUESTIONNAIRE: "completed questionnaire",
    SOURCE_CONDITION: "condition on the problem list",
    SOURCE_REFERRAL: "referral report",
}


class CatalogEntry(NamedTuple):
    """One pickable code set: what to call it, where to look, what matches.

    ``also`` names further sources the same codes can turn up in. A colonoscopy
    is the case that forced it: the instance's own CMS130v6 looks for one in
    ``referral_reports`` **or** ``imaging_reports``, where this catalog looked
    only at ``Procedure``. One record in the wrong table is not a cosmetic
    miss - the patient reads as never screened and is chased for a test they
    have had.

    Every listed source is read, and the **most recent** date across all of
    them wins. Each is still one query for the whole batch, so a value set
    naming three sources costs three queries per run, not three per screening
    and not three per patient.
    """

    label: str
    source: str
    value_set: type[ValueSet]
    also: tuple[str, ...] = ()


# --- Procedure codes the SDK's value sets do not carry ------------------------
#
# The v2026 sets behind the imaging and lab screenings are **LOINC-only**, and
# LOINC is how a *result* is coded. When a practice records the same screening
# with the **Perform** command, Canvas writes a ``Procedure`` row carrying a
# **CPT** code instead - so the screening genuinely happened and none of those
# value sets could see it.
#
# Found at UAT and confirmed against the instance 2026-09-22: the three
# mammogram options Perform offers write CPT **77065, 77066 and 77067** to
# ``Procedure``, and the SDK's ``Mammography`` carries 92 LOINC codes and not
# one of them. Out of the box the card never cleared, and the only way a
# practice could discover why was to record one and watch nothing happen.
#
# Each class below leaves the SDK's codes untouched and adds the procedure
# codes beside them, so an entry matches wherever Canvas actually put the
# record. Subclassing rather than editing keeps the SDK set unmutated - other
# entries share those classes.
#
# **Adding a code can only make an already-screened patient read as done.** It
# removes false "overdue" cards and cannot create one, which is the same
# reasoning that made the CMS130v6 modalities safe to add without a clinical
# decision. The direction that would need review is taking codes away.


class MammographyOrProcedure(ValueSet):
    """Mammography, plus the codes a recorded mammogram procedure carries."""

    VALUE_SET_NAME = "Mammogram, as a report or a recorded procedure"
    LOINC = Mammography.LOINC
    # 77067 screening, 77065/77066 diagnostic, 77061-77063 tomosynthesis. A
    # diagnostic mammogram still images the breast, so it satisfies a screening
    # recommendation: that patient is in active workup, not overdue for a look.
    CPT = {"77067", "77066", "77065", "77063", "77062", "77061"}
    # Retired from CPT in 2018, but still carried on imported history - and the
    # legacy v2018 set the instance's own CMS125v6 uses lists all three.
    HCPCSLEVELII = {"G0202", "G0204", "G0206"}


class CtColonographyOrProcedure(ValueSet):
    """CT colonography, plus its procedure codes."""

    VALUE_SET_NAME = "CT colonography, as a report or a recorded procedure"
    LOINC = CtColonography.LOINC
    # 74263 screening, 74261/74262 diagnostic.
    CPT = {"74263", "74262", "74261"}


class FecalOccultBloodOrProcedure(ValueSet):
    """FOBT/FIT, plus the codes an in-office stool test carries."""

    VALUE_SET_NAME = "FOBT / FIT stool test, as a result or a recorded procedure"
    LOINC = FecalOccultBloodTestFobt.LOINC
    # 82270 guaiac (screening), 82274 immunoassay (FIT).
    CPT = {"82270", "82274"}
    # G0328 is the Medicare FIT code.
    HCPCSLEVELII = {"G0328"}


class PapTestOrProcedure(ValueSet):
    """Cervical cytology, plus the collection and procedure codes."""

    VALUE_SET_NAME = "Pap test, as a result or a recorded procedure"
    LOINC = PapTest.LOINC
    CPT = {"88141", "88142", "88143", "88164", "88165", "88166", "88167", "88174", "88175"}
    # Q0091 is the collection itself - what a Perform in the office records.
    HCPCSLEVELII = {"Q0091", "G0123", "G0124", "G0141", "G0143", "G0144", "G0145", "G0147",
                    "G0148", "P3000", "P3001"}


# Keys are stable identifiers stored in the config document. Renaming one
# silently breaks every rule that points at it, so treat them as permanent and
# change only the label.
VALUE_SETS: dict[str, CatalogEntry] = {
    # Read from Procedure as well: a mammogram recorded with Perform lands
    # there with a CPT code, which the LOINC-only SDK set cannot match.
    "mammography": CatalogEntry(
        "Mammogram", SOURCE_IMAGING, MammographyOrProcedure, (SOURCE_PROCEDURE,)
    ),
    # The endoscopies are read in three places. CMS130v6 reads them from
    # referral reports or imaging reports and never from Procedure; Canvas can
    # record them as any of the three depending on how the result arrived.
    "colonoscopy": CatalogEntry(
        "Colonoscopy", SOURCE_PROCEDURE, Colonoscopy, (SOURCE_REFERRAL, SOURCE_IMAGING)
    ),
    "flexible_sigmoidoscopy": CatalogEntry(
        "Flexible sigmoidoscopy",
        SOURCE_PROCEDURE,
        FlexibleSigmoidoscopy,
        (SOURCE_REFERRAL, SOURCE_IMAGING),
    ),
    "fobt": CatalogEntry(
        "FOBT / FIT stool test", SOURCE_LAB, FecalOccultBloodOrProcedure, (SOURCE_PROCEDURE,)
    ),
    # The two modalities the instance's own CMS130v6 accepts and this catalog
    # did not. Both only ever make a patient *less* overdue, which is why they
    # were safe to add without a clinical decision.
    "sdna_fit_test": CatalogEntry("sDNA-FIT (Cologuard) stool DNA test", SOURCE_LAB, SdnaFitTest),
    "ct_colonography": CatalogEntry(
        "CT colonography",
        SOURCE_IMAGING,
        CtColonographyOrProcedure,
        (SOURCE_REFERRAL, SOURCE_PROCEDURE),
    ),
    "pap_test": CatalogEntry(
        "Pap test (cervical cytology)", SOURCE_LAB, PapTestOrProcedure, (SOURCE_PROCEDURE,)
    ),
    "hpv_test": CatalogEntry("HPV test", SOURCE_LAB, HpvTest),
    "falls_screening": CatalogEntry("Falls risk screening", SOURCE_QUESTIONNAIRE, FallsScreening),
    "tobacco_use_screening": CatalogEntry(
        "Tobacco use screening", SOURCE_QUESTIONNAIRE, TobaccoUseScreening
    ),
    # Exclusions: a patient carrying one of these should never see the
    # screening it rules out. These are the anatomical ones, where the
    # screening is not merely low-value but impossible.
    "absence_of_cervix": CatalogEntry(
        "Absent cervix", SOURCE_CONDITION, CongenitalOrAcquiredAbsenceOfCervix
    ),
    # Surgical history is where the native protocols look for these, not the
    # procedure table: CMS125v6 and CMS130v6 both read `patient.conditions`.
    # An exclusion missed is the wrong-patient recommendation the brief calls
    # the highest-stakes failure, so these are read in both places.
    "hysterectomy_no_cervix": CatalogEntry(
        "Hysterectomy leaving no cervix",
        SOURCE_PROCEDURE,
        HysterectomyWithNoResidualCervix,
        (SOURCE_CONDITION,),
    ),
    "bilateral_mastectomy": CatalogEntry(
        "Bilateral mastectomy", SOURCE_PROCEDURE, BilateralMastectomy, (SOURCE_CONDITION,)
    ),
    "history_bilateral_mastectomy": CatalogEntry(
        "History of bilateral mastectomy", SOURCE_CONDITION, HistoryOfBilateralMastectomy
    ),
    "total_colectomy": CatalogEntry(
        "Total colectomy", SOURCE_PROCEDURE, TotalColectomy, (SOURCE_CONDITION,)
    ),
    "colorectal_cancer": CatalogEntry(
        "Colorectal cancer", SOURCE_CONDITION, MalignantNeoplasmOfColon
    ),
}


class OrderCommandEntry(NamedTuple):
    """One command a card can offer to stage, and the field its code goes in."""

    label: str
    command: Any
    code_field: str | None
    code_is_list: bool = False
    # What the Commands API calls that same field. It is not always the Python
    # name - see the note below - and a recommendation has to use this one.
    code_api_field: str | None = None


# ``code_field`` is the field a configured code is written into, and
# ``code_is_list`` says whether that field takes one code or several (verified
# against each command's model fields). A None field means the command takes no
# code, so the rule's code is left out and the provider picks in the staged
# command rather than being handed a wrong one.
#
# ``code_api_field`` is the same field's name in the Commands API, and it differs
# from the Python name on every command that takes a code:
#
#     image_code        -> image
#     tests_order_codes -> tests
#     cpt_code          -> perform
#
# This matters because ``_BaseCommand.recommendation_context`` builds its payload
# from ``TrackableFieldsModel.values``, which keys by the **Python** field name.
# A staged command therefore arrived with a key Canvas does not recognise, and
# opened with every field blank - the button worked, the pre-fill did not.
# Observed on a real chart 2026-09-20 on an imaging order; it affected all three.
ORDER_COMMANDS: dict[str, OrderCommandEntry] = {
    "imaging_order": OrderCommandEntry(
        "Imaging order", ImagingOrderCommand, "image_code", False, "image"
    ),
    "lab_order": OrderCommandEntry(
        "Lab order", LabOrderCommand, "tests_order_codes", True, "tests"
    ),
    "perform": OrderCommandEntry("Perform", PerformCommand, "cpt_code", False, "perform"),
    "refer": OrderCommandEntry("Referral", ReferCommand, None),
    "instruct": OrderCommandEntry("Instruct", InstructCommand, None),
    "plan": OrderCommandEntry("Plan", PlanCommand, None),
    "task": OrderCommandEntry("Task", TaskCommand, None),
}


def value_set_for(key: str) -> type[ValueSet] | None:
    """The value set a rule's key names, or None when the key is unknown.

    A rule pointing at a key this version no longer ships resolves to None and
    is treated as unmeasurable rather than as "not done" - see the "unknown is
    never positive" rule in ``services.screenings``.
    """
    entry = VALUE_SETS.get(key)
    return entry.value_set if entry else None


def extra_sources_for(key: str) -> tuple[str, ...]:
    """The further sources a catalog key's codes can also turn up in.

    Empty for a key that is not in the catalog, which covers both a retired key
    and a rule carrying its own codes: an admin's custom codes are read in the
    one source they chose, because nothing here knows where else to look.
    """
    entry = VALUE_SETS.get(key)
    return entry.also if entry else ()


def catalog_for_ui() -> dict[str, Any]:
    """The catalog as plain JSON for the admin page's pickers.

    Value-set classes never cross into the page; only their keys and labels do.
    """
    return {
        "sources": [{"key": key, "label": label} for key, label in SOURCES.items()],
        "value_sets": [
            {
                "key": key,
                "label": entry.label,
                "source": entry.source,
                # Every source actually read, not only the primary one, so the
                # editor can say where a screening is looked for.
                "sources": [entry.source, *entry.also],
                # The codes themselves. Until 2026-09-22 the editor was sent
                # only the key, the label and the source, so a practice picking
                # "Mammogram" had no way to learn it meant 92 LOINC codes and
                # nothing else - and no way to find out why a recorded mammogram
                # did not clear the card except by recording one and watching
                # nothing happen. That is exactly the question the client asked
                # us to stop needing a developer for.
                "systems": {
                    name: sorted(codes) for name, codes in sorted(entry.value_set.values.items())
                },
            }
            for key, entry in VALUE_SETS.items()
        ],
        "order_commands": [
            {"key": key, "label": entry.label, "takes_code": entry.code_field is not None}
            for key, entry in ORDER_COMMANDS.items()
        ],
    }
