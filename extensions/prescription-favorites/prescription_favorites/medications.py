"""Configuration for favorite medications."""

from typing import TypedDict


class MedicationConfig(TypedDict, total=False):
    """Type definition for medication configuration.

    Note: is_custom is optional and added dynamically by FavoritesService
    to distinguish hardcoded defaults from user-added favorites.
    """
    id: str
    display_name: str
    label: str | None  # Badge label (e.g., "Starting", "Titration", "Nausea")
    label_color: str | None  # Badge color (green, purple, blue, amber, rose)
    medication_name: str
    fdb_code: str
    sig: str
    days_supply: int
    quantity_to_dispense: float
    unit: str
    refills: int
    representative_ndc: str
    ncpdp_quantity_qualifier_code: str
    generic_substitution_allowed: bool
    search_terms: list[str]
    default_pharmacy_ncpdp_id: str | None
    default_pharmacy_name: str | None
    is_custom: bool  # True for user-added favorites, False for hardcoded defaults


FAVORITE_MEDICATIONS: dict[str, MedicationConfig] = {
    "wegovy_0.25mg": {
        "id": "wegovy_0.25mg",
        "display_name": "Wegovy 0.25 mg",
        "label": "Starting",
        "label_color": "green",
        "medication_name": "Wegovy 0.25 mg/0.5 mL subcutaneous pen injector",
        "fdb_code": "606783",
        "sig": "Inject subcutaneously once weekly",
        "days_supply": 28,
        "quantity_to_dispense": 4.0,
        "unit": "0.5 mL syringe",
        "refills": 0,
        "representative_ndc": "00169452514",
        "ncpdp_quantity_qualifier_code": "C28254",
        "generic_substitution_allowed": True,
        "search_terms": ["wegovy", "semaglutide", "0.25mg", "weight loss", "glp-1"],
        "default_pharmacy_ncpdp_id": "5919177",
        "default_pharmacy_name": "Amazon Pharmacy",
    },
    "wegovy_0.5mg": {
        "id": "wegovy_0.5mg",
        "display_name": "Wegovy 0.5 mg",
        "label": "Titration",
        "label_color": "green",
        "medication_name": "Wegovy 0.5 mg/0.5 mL subcutaneous pen injector",
        "fdb_code": "606781",
        "sig": "Inject subcutaneously once weekly",
        "days_supply": 28,
        "quantity_to_dispense": 4.0,
        "unit": "0.5 mL syringe",
        "refills": 0,
        "representative_ndc": "00169450514",
        "ncpdp_quantity_qualifier_code": "C28254",
        "generic_substitution_allowed": True,
        "search_terms": ["wegovy", "semaglutide", "0.5mg", "weight loss", "glp-1"],
        "default_pharmacy_ncpdp_id": "5919177",
        "default_pharmacy_name": "Amazon Pharmacy",
    },
    "wegovy_1mg": {
        "id": "wegovy_1mg",
        "display_name": "Wegovy 1 mg",
        "label": "Maintenance",
        "label_color": "green",
        "medication_name": "Wegovy 1 mg/0.5 mL subcutaneous pen injector",
        "fdb_code": "606782",
        "sig": "Inject subcutaneously once weekly",
        "days_supply": 28,
        "quantity_to_dispense": 4.0,
        "unit": "0.5 mL syringe",
        "refills": 2,
        "representative_ndc": "00169450114",
        "ncpdp_quantity_qualifier_code": "C28254",
        "generic_substitution_allowed": True,
        "search_terms": ["wegovy", "semaglutide", "1mg", "weight loss", "glp-1"],
        "default_pharmacy_ncpdp_id": "5919177",
        "default_pharmacy_name": "Amazon Pharmacy",
    },
    # "zepbound_2.5mg": {
    #     "id": "zepbound_2.5mg",
    #     "display_name": "Zepbound 2.5 mg · Starting",
    #     "medication_name": "Zepbound 2.5 mg/0.5 mL subcutaneous pen injector",
    #     "fdb_code": "617137",
    #     "sig": "Inject 2.5 mg subcutaneously once weekly",
    #     "days_supply": 28,
    #     "quantity_to_dispense": 4.0,
    #     "unit": "0.5 mL syringe",
    #     "refills": 0,
    #     "representative_ndc": "00002250680",
    #     "ncpdp_quantity_qualifier_code": "C28254",
    #     "generic_substitution_allowed": True,
    #     "search_terms": ["zepbound", "tirzepatide", "2.5mg", "weight loss", "glp-1", "gip"],
    #     "default_pharmacy_ncpdp_id": "2623735",
    #     "default_pharmacy_name": "Express Scripts",
    # },
    # "zepbound_5mg": {
    #     "id": "zepbound_5mg",
    #     "display_name": "Zepbound 5 mg · Titration",
    #     "medication_name": "Zepbound 5 mg/0.5 mL subcutaneous pen injector",
    #     "fdb_code": "617140",
    #     "sig": "Inject 5 mg subcutaneously once weekly",
    #     "days_supply": 28,
    #     "quantity_to_dispense": 4.0,
    #     "unit": "0.5 mL syringe",
    #     "refills": 0,
    #     "representative_ndc": "00002249580",
    #     "ncpdp_quantity_qualifier_code": "C28254",
    #     "generic_substitution_allowed": True,
    #     "search_terms": ["zepbound", "tirzepatide", "5mg", "weight loss", "glp-1", "gip"],
    #     "default_pharmacy_ncpdp_id": "2623735",
    #     "default_pharmacy_name": "Express Scripts",
    # },
    # "zepbound_10mg": {
    #     "id": "zepbound_10mg",
    #     "display_name": "Zepbound 10 mg · Maintenance",
    #     "medication_name": "Zepbound 10 mg/0.5 mL subcutaneous pen injector",
    #     "fdb_code": "617139",
    #     "sig": "Inject 10 mg subcutaneously once weekly",
    #     "days_supply": 28,
    #     "quantity_to_dispense": 4.0,
    #     "unit": "0.5 mL syringe",
    #     "refills": 2,
    #     "representative_ndc": "00002247180",
    #     "ncpdp_quantity_qualifier_code": "C28254",
    #     "generic_substitution_allowed": True,
    #     "search_terms": ["zepbound", "tirzepatide", "10mg", "weight loss", "glp-1", "gip"],
    #     "default_pharmacy_ncpdp_id": "2623735",
    #     "default_pharmacy_name": "Express Scripts",
    # },
    "ondansetron_4mg": {
        "id": "ondansetron_4mg",
        "display_name": "Ondansetron ODT 4 mg",
        "label": "Nausea",
        "label_color": "purple",
        "medication_name": "ondansetron 4 mg disintegrating tablet",
        "fdb_code": "285288",
        "sig": "Take 1 tablet by mouth every 8 hours as needed for nausea",
        "days_supply": 14,
        "quantity_to_dispense": 21.0,
        "unit": "tablet",
        "refills": 0,
        "representative_ndc": "42291045730",
        "ncpdp_quantity_qualifier_code": "C48542",
        "generic_substitution_allowed": True,
        "search_terms": ["ondansetron", "zofran", "4mg", "nausea", "anti-emetic", "odt"],
        "default_pharmacy_ncpdp_id": "0556540",
        "default_pharmacy_name": "OptumRx",
    },
    "omeprazole_20mg": {
        "id": "omeprazole_20mg",
        "display_name": "Omeprazole 20 mg",
        "label": "Reflux",
        "label_color": "purple",
        "medication_name": "omeprazole 20 mg capsule,delayed release",
        "fdb_code": "259872",
        "sig": "Take 1 capsule by mouth once daily before breakfast",
        "days_supply": 30,
        "quantity_to_dispense": 30.0,
        "unit": "capsule",
        "refills": 1,
        "representative_ndc": "51407064190",
        "ncpdp_quantity_qualifier_code": "C48480",
        "generic_substitution_allowed": True,
        "search_terms": ["omeprazole", "prilosec", "20mg", "acid reflux", "gerd", "ppi"],
        "default_pharmacy_ncpdp_id": "5906017",
        "default_pharmacy_name": "Empower Pharmacy",
    },
}
