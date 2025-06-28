import csv, re, html

from data_migrations.template_migration.condition import ConditionLoaderMixin
from data_migrations.utils import (
    fetch_complete_csv_rows,
    fetch_from_json,
    load_fhir_settings
)


def find_escaped_characters(text):
    """
    Finds HTML escaped characters in a string and returns a list of them.
    """
    unescaped_text = html.unescape(text)
    if unescaped_text == text:
      return []

    escaped_characters = []
    i = 0
    while i < len(text):
      if text[i] == '&':
        match = re.match(r"&[a-zA-Z0-9#]+;", text[i:])
        if match:
          escaped_characters.append(match.group(0))
          i += len(match.group(0))
          continue
      i+=1
    return escaped_characters


class ConditionLoader(ConditionLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.json_file = "PHI/conditions.json"
        self.csv_file = "PHI/conditions.csv"
        self.environment = environment
        self.snomed_to_icd_10_mapping_file = "mappings/snomed_to_icd10_map.json"
        self.snomed_to_icd_10_mapping = fetch_from_json(self.snomed_to_icd_10_mapping_file)
        self.mapping_file = "mappings/icd10_mappings.csv"
        self.doctor_map_file = "mappings/provider_id_mapping.json"
        self.doctor_map = fetch_from_json(self.doctor_map_file)
        self.fumage_helper = load_fhir_settings(environment)
        self.done_file = "results/done_conditions.csv"
        self.error_file = "results/errored_conditions.csv"
        self.ignore_file = "results/ignored_conditions.csv"
        self.validation_error_file = 'results/PHI/errored_condition_validation.json'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.icd10_map_file = "../template_migration/mappings/icd10_map.json"
        self.icd10_map = fetch_from_json(self.icd10_map_file)
        self.patient_map_file = "PHI/patient_id_map.json"
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)
        self.default_location = "7d1e74f5-e3f4-467d-81bb-08d90d1a158a"
        self.default_note_type_name = "Athena Historical Note"


    def create_mapping_file(self):
        data = fetch_from_json(self.json_file)
        codes_to_map = []
        for row in data:
            for cond in row.get("conditions", []):
                icd_10_codings = [c for c in cond.get("code", {}).get("coding", []) if c["system"] == "http://hl7.org/fhir/sid/icd-10-cm"]
                # If we don't have an ICD-10, let's get any others for mapping
                if not icd_10_codings and "code" in cond:
                    codes_to_map.extend(cond["code"]["coding"])
        code_tuples = [(c["system"], c["code"], c["display"], "", "",) for c in codes_to_map]
        # dedupe
        code_tuples = list(set(code_tuples))
        with open(self.mapping_file, 'w') as fhandle:
            writer = csv.writer(fhandle)
            # write header
            writer.writerow(("system", "code", "display", "icd10_code", "icd10_display",))
            # write data
            writer.writerows(code_tuples)



    def make_csv(self):
        headers = [
            "ID",
            "Patient Identifier",
            "Clinical Status",
            "ICD-10 Code",
            "Onset Date",
            "Resolved Date",
            "Recorded Provider",
            "Free text notes",
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()

            data = fetch_from_json(self.json_file)

            # The encounter references are in different entries than the conditions.
            # To get the originating provider, we need to make a map for these.
            diagnosis_encounter_map = {}
            for row in data:
                for cond in row.get("conditions", []):
                    condition_id = cond["id"]
                    id_type = condition_id[condition_id.index(".") + 1:]
                    id_type = id_type[:id_type.index("-")]
                    if id_type in ["cn.EncounterDx.acs", "cn.Problem.acs", "cn.PregnancyProblem.acs"]:
                        provider_id = [agent["who"]["reference"] for agent in cond.get("agent", [])][0].replace("Practitioner/", "") if cond.get("agent") else ""
                        if provider_id and 'Provider-' in provider_id:
                            provider_ref = provider_id.replace("a-25828.", "")
                            condition_key = cond["target"][0]["reference"].replace("Condition/a-25828.", "")
                            diagnosis_encounter_map[condition_key] = provider_ref

            for row in data:
                for cond in row.get("conditions", []):
                    condition_id = cond["id"]

                    clinical_status = cond.get("clinicalStatus", {}).get("text", "")
                    if clinical_status.lower() == "inactive":
                        clinical_status = "resolved"
                    patient_id = cond.get("subject", {}).get("reference", "").replace("Patient/", "").replace("a-25828.E-", "")

                    id_type = condition_id[condition_id.index(".") + 1:]
                    id_type = id_type[:id_type.index("-")]

                    # ignore these records - there is no patient attached to them
                    if id_type in ["cn.EncounterDx.acs", "cn.Problem.acs", "cn.PregnancyProblem.acs"]:
                        continue

                    icd_10_code = ""

                    icd_10_codes = [c for c in cond.get("code", {}).get("coding", []) if c["system"] == "http://hl7.org/fhir/sid/icd-10-cm"]
                    if icd_10_codes:
                        icd_10_code = icd_10_codes[0]["code"]
                    else:
                        snomed_codes = [c for c in cond.get("code", {}).get("coding", []) if c["system"] == "http://snomed.info/sct"]
                        if snomed_codes:
                            map_to_icd_10 = self.snomed_to_icd_10_mapping.get(snomed_codes[0]["code"])
                            if map_to_icd_10:
                                icd_10_code = map_to_icd_10[0]
                                icd_10_display = map_to_icd_10[1]
                    # remove periods in ICD codes
                    icd_10_code = icd_10_code.replace(".", "")

                    condition_id_stripped = condition_id.replace("a-25828.", "")
                    provider_id = diagnosis_encounter_map.get(condition_id_stripped, "")
                    if provider_id:
                        provider_id = provider_id.replace("Provider-", "")

                    notes = "\n".join([n.get("text") for n in cond.get("note", []) if n.get("text")])
                    # strip html tags
                    notes = re.sub('<[^<]+?>', '', notes)
                    # prevent line breaks and carriage returns in csv
                    notes = notes.replace("\n", "\\n").replace("\r", "\\n")

                    notes_has_escaped_chars = find_escaped_characters(notes)
                    if notes_has_escaped_chars:
                        notes = html.unescape(notes)

                    row_to_write = {
                        "ID": condition_id_stripped,
                        "Patient Identifier": patient_id,
                        "Clinical Status": clinical_status.lower() if clinical_status else "active",
                        "ICD-10 Code": icd_10_code,
                        "Onset Date": cond.get("onsetDateTime", ""),
                        "Resolved Date": cond.get("abatementDateTime", ""),
                        "Recorded Provider": provider_id,
                        "Free text notes": notes,
                    }

                    writer.writerow(row_to_write)

        print("CSV successfully made")


if __name__ == "__main__":
    loader = ConditionLoader(environment="phi-test-accomplish")
    # loader.create_mapping_file()
    # loader.make_csv()
    valid_rows = loader.validate(delimiter=",")
    loader.load(validated_rows=valid_rows)
