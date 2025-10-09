from __future__ import annotations
import csv
from copy import deepcopy

from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from data_migrations.charm_migration.utils import CharmPatientAPI
from data_migrations.template_migration.condition import ConditionLoaderMixin
from data_migrations.utils import (
    fetch_complete_csv_rows,
    fetch_from_json,
    load_fhir_settings,
    write_to_json
)

class LatestItemUtils:
    """Utilities to select latest items by date or by a fallback key per group/code."""

    @staticmethod
    def _try_parse_iso_date(value: Any) -> Optional[date]:
        """Return date if value is an ISO "YYYY-MM-DD" string; otherwise None."""
        if value is None:
            return None
        try:
            return date.fromisoformat(str(value))
        except Exception:
            return None

    def latest_by_group(
        self,
        items: Iterable[Mapping[str, Any]],
        group_key: str,
        date_key: str = "date",
        ignore_invalid: bool = True,
        fallback_key: Optional[str] = None,
    ) -> Dict[Any, Mapping[str, Any]]:
        """Return a mapping of group -> latest item within that group.

        - group_key: key to group by (e.g., "id" or "code")
        - date_key: key holding the ISO date string
        - ignore_invalid: if True, skip items with missing group/date; if False, raise
        - fallback_key: when dates are equal or all empty/invalid, pick item with
          the largest value of this key
        """
        # Collect all items per group to support fallback selection if needed
        group_to_items: Dict[Any, List[Mapping[str, Any]]] = {}
        # Track best-by-date per group while scanning
        best_by_date: Dict[Any, Tuple[Optional[date], Mapping[str, Any]]] = {}

        for item in items:
            if group_key not in item:
                if ignore_invalid:
                    continue
                else:
                    raise KeyError(f"Missing group key '{group_key}' in item: {item}")
            group_value = item[group_key]
            group_to_items.setdefault(group_value, []).append(item)

            parsed = self._try_parse_iso_date(item.get(date_key))
            current = best_by_date.get(group_value)
            if parsed is not None:
                if current is None or current[0] is None or parsed > current[0]:
                    best_by_date[group_value] = (parsed, item)
                elif parsed == current[0] and fallback_key is not None:
                    # Tiebreaker: use largest fallback_key value
                    current_fallback = current[1].get(fallback_key)
                    item_fallback = item.get(fallback_key)
                    if current_fallback is not None and item_fallback is not None:
                        if item_fallback > current_fallback:
                            best_by_date[group_value] = (parsed, item)
            else:
                # Keep at least a placeholder so we know the group exists
                if current is None:
                    best_by_date[group_value] = (None, item)

        result: Dict[Any, Mapping[str, Any]] = {}
        for group_value, (best_dt, best_item) in best_by_date.items():
            if best_dt is not None:
                result[group_value] = best_item
                continue
            # All dates invalid/empty for this group
            if fallback_key is None:
                # If no fallback specified, either skip or raise depending on ignore_invalid
                if ignore_invalid:
                    continue
                else:
                    raise ValueError(
                        f"All items in group '{group_value}' have invalid/empty '{date_key}', and no fallback_key provided"
                    )
            # Choose by largest fallback key value
            candidates = group_to_items.get(group_value, [])
            # Filter out missing fallback_key when possible; if none left, use all
            with_key = [i for i in candidates if fallback_key in i]
            if with_key:
                candidates = with_key
            try:
                result[group_value] = max(candidates, key=lambda i: i.get(fallback_key))
            except Exception:
                # If comparison fails or candidates empty, fall back safely
                result[group_value] = candidates[0] if candidates else best_item

        return result

    def dedupe_by_latest_code(
        self,
        items: Iterable[Mapping[str, Any]],
        code_key: str = "code",
        date_key: str = "from_date",
        ignore_invalid: bool = False,
        fallback_key: Optional[str] = "patient_diagnosis_id",
    ) -> List[Mapping[str, Any]]:
        """Return one item per code, selecting the item with the most recent date.

        Falls back to choosing the item with the largest value of `fallback_key`
        when all dates in a code group are empty/invalid (e.g., use fallback_key="id").
        """
        by_code = self.latest_by_group(
            items,
            group_key=code_key,
            date_key=date_key,
            ignore_invalid=ignore_invalid,
            fallback_key=fallback_key,
        )
        return list(by_code.values())


class ConditionLoader(ConditionLoaderMixin, LatestItemUtils):
    def __init__(self, environment, *args, **kwargs):
        self.json_file = "PHI/conditions.json"
        self.csv_file = "PHI/conditions.csv"
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)
        self.done_file = "results/done_conditions.csv"
        self.error_file = "results/errored_conditions.csv"
        self.ignore_file = "results/ignored_conditions.csv"
        self.validation_error_file = 'results/PHI/errored_condition_validation.json'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map_file = "PHI/patient_id_map.json"
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)
        self.icd10_map_file = "../template_migration/mappings/icd10_map.json"
        self.icd10_map = fetch_from_json(self.icd10_map_file)

        self.condition_map_file = "mappings/condition_map.json"
        self.condition_map = fetch_from_json(self.condition_map_file)

        self.do_not_migrate_file = "mappings/conditions_do_not_migrate.json"
        self.do_not_migrate_list = fetch_from_json(self.do_not_migrate_file)

        self.map_to_surgical_history_file = "mappings/map_to_surgical_history.json"
        self.map_to_surgical_history = fetch_from_json(self.map_to_surgical_history_file)

        self.default_location = "e4b42f50-df8d-44a6-931b-1f09f0d7f81b"
        self.default_note_type_name = "Charm Historical Note"

    def dedupe_diagnosis_ids(self, patient_diagnoses):
        # Only keep the latest record based on from_date if a patient has duplicate conditions
        # per ICD10 code
        return self.dedupe_by_latest_code(patient_diagnoses)

    def make_patient_api_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)

        patient_file_contents = fetch_from_json("PHI/patients.json")
        patient_ids = [p["patient_id"] for p in patient_file_contents]

        condition_list = charm_patient_api.fetch_diagnoses(patient_ids=patient_ids)
        write_to_json(self.json_file, condition_list)


    def make_csv(self):
        data = fetch_from_json(self.json_file)
        headers = [
            "ID",
            "Patient Identifier",
            "Clinical Status",
            "ICD-10 Code",
            "Onset Date",
            "Free text notes",
            "Resolved Date",
            "Recorded Provider",
            "Name"
        ]
        with open(self.csv_file, "w") as fhandle:
            writer = csv.DictWriter(
                fhandle,
                fieldnames=headers,
                delimiter=",",
                quotechar='"',
                quoting=csv.QUOTE_MINIMAL
            )
            writer.writeheader()

            for row in data:
                patient_id = row["patient_id"]
                patient_include_diagnoses = []

                patient_diagnoses = deepcopy(row["diagnoses"])
                for cnd in patient_diagnoses:
                    condition_text = cnd["diagnosis_name"]
                    condition_code_type = cnd["code_type"]
                    if condition_code_type == "ICD10":
                        condition_icd10_code = cnd["code"]
                    else:
                        condition_icd10_code = ""

                    mapping_key = f"{condition_text}|{condition_icd10_code}"

                    condition_mapped = self.condition_map.get(mapping_key)
                    icd_10_code = ""
                    icd_10_name = ""

                    if condition_mapped:
                        icd_10_code = condition_mapped["code"]
                        icd_10_name = condition_mapped["display"]
                    elif mapping_key in self.do_not_migrate_list:
                        self.ignore_row(cnd["patient_diagnosis_id"], "Ignoring because code is in the do not map list")
                        continue
                    elif mapping_key in self.map_to_surgical_history:
                        self.ignore_row(cnd["patient_diagnosis_id"], "Ignoring because needs mapping to surgical history")
                        continue
                        # separately imported to surgical history in create_conditions_as_surgical_history.py
                    else:
                        # there shouldn't be any of these
                        self.ignore_row(cnd["patient_diagnosis_id"], "Ignoring due to no ICD10 mapping found")
                        continue

                    cnd["code"] = icd_10_code.replace(".", "")
                    cnd["code_type"] = "ICD10"
                    cnd["diagnosis_name"] = icd_10_name
                    patient_include_diagnoses.append(cnd)

                dedupe_diagnoses = self.dedupe_diagnosis_ids(patient_include_diagnoses)
                filtered_out_ids = [
                    d["patient_diagnosis_id"] for d in row["diagnoses"] if d["patient_diagnosis_id"] not in [c["patient_diagnosis_id"] for c in dedupe_diagnoses]
                ]
                for id in filtered_out_ids:
                    self.ignore_row(id, "Filtered out duplicated patient condition by ICD-10 code")

                for diagnosis in dedupe_diagnoses:
                    status_dict = {
                        "Active": "active",
                        "Inactive": "resolved",
                        "Resolved": "resolved",
                    }
                    clinical_status = status_dict[diagnosis["status"]]
                    # if there is a status of active and also a to_date, mark the condition as resolved (per client instructions)
                    if clinical_status == "active" and diagnosis["to_date"]:
                        clinical_status = "resolved"

                    row_to_write = {
                        "ID": diagnosis["patient_diagnosis_id"],
                        "Patient Identifier": patient_id,
                        "Clinical Status": clinical_status,
                        "ICD-10 Code": diagnosis["code"].replace(".", "") if diagnosis["code_type"] == "ICD10" else "",
                        "Onset Date": diagnosis["from_date"],
                        "Free text notes": diagnosis["comments"],
                        "Resolved Date": diagnosis["to_date"],
                        "Recorded Provider": "",
                        "Name": diagnosis["diagnosis_name"],
                    }

                    writer.writerow(row_to_write)
        print(f"Successfully created {self.csv_file}")



    def patient_imported_icd10_codes(self):
        patient_imported_codes = {}
        headers = ['id', 'patient_id', 'patient_key', 'canvas_externally_exposable_id', 'icd10_code']
        with open("results/done_conditions.csv") as fhandle:
            reader = csv.DictReader(fhandle, fieldnames=headers, delimiter="|")
            for row in reader:
                patient_id = row["patient_id"]
                # header row
                if row['id'] == 'id':
                    continue
                if patient_id not in patient_imported_codes:
                    patient_imported_codes[patient_id] = [row["icd10_code"]]
                else:
                    patient_imported_codes[patient_id].append(row["icd10_code"])
        return patient_imported_codes


    def check_conditions_not_imported(self):
        done_ids = set()
        ignored_ids = set()
        others = set()

        ignored = fetch_complete_csv_rows(self.ignore_file)

        data = fetch_from_json(self.json_file)
        for row in data:
            patient_id = row["patient_id"]
            for diagnosis in row["diagnoses"]:
                diagnosis_id = diagnosis["patient_diagnosis_id"]
                if diagnosis_id in self.done_records:
                    done_ids.add(diagnosis_id)
                elif diagnosis_id in ignored:
                    ignored_ids.add(diagnosis_id)
                else:
                    others.add(diagnosis_id)
        print(len(others))


if __name__ == "__main__":
    loader = ConditionLoader(environment="ways2well")
    # loader.patient_id_check()
    # loader.make_patient_api_json()
    # loader.make_csv()
    # valid_rows = loader.validate(delimiter=",")
    # loader.load(valid_rows)

    # TODO when importing new batch - ignore when an ICD 10 code has already been imported for a patient;
    loader.check_conditions_not_imported()
