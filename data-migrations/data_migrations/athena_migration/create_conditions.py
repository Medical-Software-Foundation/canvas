import csv

from data_migrations.template_migration.condition import ConditionLoaderMixin
from data_migrations.utils import fetch_from_json


class ConditionLoader(ConditionLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.json_file = "PHI/conditions.json"
        self.csv_file = "PHI/conditions.csv"
        self.environment = environment
        self.mapping_file = "mappings/icd10_mappings.csv"
        # self.fumage_helper = load_fhir_settings(environment)


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
            "Free Text Notes",
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()

            data = fetch_from_json(self.json_file)

            identifier_types = {}

            for row in data:
                for cond in row.get("conditions", []):
                    # condition_id = cond.get("id", "")
                    condition_id = cond["id"]
                    # category = cond["category"][0]["text"]

                    clinical_status = cond.get("clinicalStatus", {}).get("text", "")
                    patient_id = cond.get("subject", {}).get("reference", "").replace("Patient/", "")

                    id_type = condition_id[condition_id.index(".") + 1:]
                    id_type = id_type[:id_type.index("-")]

                    category_type = cond["category"][0]["text"] if cond.get("category") else ""

                    if id_type not in identifier_types:
                        if patient_id:
                            identifier_types[id_type] = {"has_patient": 1, "no_patient": 0, "categories": []}
                        else:
                            identifier_types[id_type] = {"has_patient": 0, "no_patient": 1, "categories": []}
                    else:
                        if patient_id:
                            identifier_types[id_type]["has_patient"] = identifier_types[id_type]["has_patient"] + 1
                        else:
                            identifier_types[id_type]["no_patient"] = identifier_types[id_type]["no_patient"] + 1

                    if category_type and category_type not in identifier_types[id_type]["categories"]:
                        identifier_types[id_type]["categories"].append(category_type)


                    icd_10_codes = [c["code"] for c in cond.get("code", {}).get("coding", []) if c["system"] == "http://hl7.org/fhir/sid/icd-10-cm"]
                    provider_id = [agent["who"]["reference"] for agent in cond.get("agent", [])][0].replace("Practitioner/", "") if cond.get("agent") else ""
                    notes = "\n".join([n.get("text") for n in cond.get("note", []) if n.get("text")])

                    row_to_write = {
                        "ID": condition_id,
                        "Patient Identifier": patient_id,
                        "Clinical Status": clinical_status, # There are conditions that are missing this value. What should we put if there is no clinicalStatus?
                        "ICD-10 Code": icd_10_codes[0] if icd_10_codes else "",
                        "Onset Date": cond.get("onsetDateTime", ""),
                        "Resolved Date": cond.get("abatementDateTime", ""),
                        "Recorded Provider": provider_id, # Providers are not listed for every condition;
                        "Free Text Notes": notes, # Contains html characters; strip?
                    }

                    writer.writerow(row_to_write)

            print(identifier_types)

        print("CSV successfully made")


if __name__ == "__main__":
    loader = ConditionLoader(environment="localhost")
    #loader.create_mapping_file()
    loader.make_csv()
