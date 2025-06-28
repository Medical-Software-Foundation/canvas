import csv
import json

from data_migrations.template_migration.allergy import AllergyLoaderMixin
from data_migrations.utils import (
    fetch_from_json,
    fetch_complete_csv_rows,
    load_fhir_settings
)


class AllergyLoader(AllergyLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.csv_file = "PHI/allergies.csv"
        self.json_file = "PHI/allergies.json"
        self.fdb_mapping_write_to_file = "mappings/fdb_mappings.csv"
        self.fdb_mapping_file = "mappings/fdb_mappings.json"
        self.fdb_mapping_by_name_file = "mappings/fdb_mappings_by_name.json"
        self.fdb_mappings = fetch_from_json(self.fdb_mapping_file)
        self.fdb_mappings_by_name = fetch_from_json(self.fdb_mapping_by_name_file)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.done_file = 'results/done_allergies.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.ignore_file = "results/ignored_allergies.csv"
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.error_file = 'results/errored_allergies.csv'
        self.fumage_helper = load_fhir_settings(environment)
        self.validation_error_file = "results/PHI/errored_allergy_validation.json"

        self.default_location = "7d1e74f5-e3f4-467d-81bb-08d90d1a158a"
        self.default_note_type_name = "Athena Historical Note"
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)

    def create_rxnorm_mapping_file(self):
        # We do not get FDB codes in this data. We do get RxNorm descriptions and
        # (sometimes) RxNorm codes. Canvas expects FDB codes for Allergies.
        # This method makes a mapping file so that someone can CX can fill it out
        # and map to the correct FDB codes.

        with open(self.json_file) as json_handle:
            data = json.loads(json_handle.read())
            output_list = []

            for row in data:
                for allergy in row["allergies"]:
                    translation_codings = [(t.get("codesystemdisplayname", ""), t.get("displayname", ""), t.get("value", ""),) for t in allergy.get("translations")]
                    translation_codings.sort()
                    translation_text = "\n".join(["; ".join(tr) for tr in translation_codings])

                    allergy_row = (
                        allergy["allergenname"],
                        allergy.get("rxnormcode", ""),
                        allergy.get("rxnormdescription", ""),
                        translation_text,
                    )

                    # ignore allergies we already mapped
                    if allergy_row[1] and allergy_row[1] in self.fdb_mappings:
                        continue
                    elif allergy_row[0] and allergy_row[0] in self.fdb_mappings_by_name:
                        continue

                    output_list.append(allergy_row)

        output_list = list(set(output_list))

        headers = [
            "allergenname",
            "rxnormcode",
            "rxnormdescription",
            "translation_codings",
        ]

        with open(self.fdb_mapping_write_to_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()

            for row in output_list:
                writer.writerow(
                    {
                        "allergenname": row[0],
                        "rxnormcode": row[1],
                        "rxnormdescription": row[2],
                        "translation_codings": row[3]
                    }
                )

    def make_csv(self):
        headers = [
            "ID",
            "Patient Identifier",
            "Clinical Status",
            "Type",
            "FDB Code",
            "Name",
            "Onset Date",
            "Free Text Note",
            "Reaction",
            "Recorded Provider"
        ]

        data = None
        with open(self.json_file) as json_handle:
            data = json.loads(json_handle.read())

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()

            for row in data:
                patient_id = row.get("patientdetails", {}).get("enterpriseid", "")

                for allergy in row["allergies"]:
                    reaction_text = ", ".join([r["reactionname"] for r in allergy["reactions"]])

                    fdb_code = ""
                    fdb_display = ""
                    free_text_note = ""

                    if allergy.get("rxnormcode") and allergy.get("rxnormcode") in self.fdb_mappings:
                        fdb_code = self.fdb_mappings[allergy["rxnormcode"]]["code"]
                        fdb_display = self.fdb_mappings[allergy["rxnormcode"]]["display"]
                    elif allergy.get("allergenname") and allergy.get("allergenname") in self.fdb_mappings_by_name:
                        fdb_code = self.fdb_mappings_by_name[allergy["allergenname"]]["code"]
                        fdb_display = self.fdb_mappings_by_name[allergy["allergenname"]]["display"]
                    else:
                        fdb_code = "1-143" # Code for no allergy information available
                        free_text_note = allergy.get("allergenname") or ""
                        fdb_display = "No Allergy Information Available"

                    clinical_status = "active"
                    if allergy.get("deactivatedate"):
                        clinical_status = "inactive"

                    row_to_write = {
                        "ID": allergy["id"],
                        "Patient Identifier": patient_id,
                        "Clinical Status": clinical_status,
                        "Type": "allergy",
                        "FDB Code": fdb_code,
                        "Name": fdb_display,
                        "Onset Date": "", # there is no onset date;
                        "Free Text Note": free_text_note,
                        "Reaction": reaction_text,
                        "Recorded Provider": allergy.get("lastmodifiedby", ""),
                    }

                    writer.writerow(row_to_write)

        print("CSV successfully made")

    def find_missing_rows(self, delimiter=","):
        headers = [
            "ID",
            "Patient Identifier",
            "Clinical Status",
            "Type",
            "FDB Code",
            "Name",
            "Onset Date",
            "Free Text Note",
            "Reaction",
            "Recorded Provider"
        ]

        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            with open("PHI/diff_allergies.csv", "w") as new_file:
                writer = csv.DictWriter(new_file, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()

                for row in reader:
                    if row['ID'] in self.done_records:
                        continue
                    else:
                        writer.writerow(row)


if __name__ == "__main__":
    loader = AllergyLoader('phi-test-accomplish')
    #loader.create_rxnorm_mapping_file()
    #loader.make_csv()

    #loader.find_missing_rows()

    valid_rows = loader.validate(delimiter=",")
    loader.load(valid_rows)
