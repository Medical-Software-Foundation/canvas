import csv
import json

from data_migrations.template_migration.allergy import AllergyLoaderMixin


class AllergyLoader(AllergyLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.csv_file = "PHI/allergies.csv"
        self.json_file = "PHI/allergies.json"
        self.fdb_mapping_file = "mappings/fdb_mappings.csv"


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

                    output_list.append(allergy_row)

        output_list = list(set(output_list))

        headers = [
            "allergenname",
            "rxnormcode",
            "rxnormdescription",
            "translation_codings",
        ]

        with open(self.fdb_mapping_file, 'w') as f:
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
                patient_id = row.get("patientdetails", {}).get("fhir-patientid", "")

                for allergy in row["allergies"]:
                    reaction_text = ", ".join([r["reactionname"] for r in allergy["reactions"]])

                    row_to_write = {
                        "ID": allergy["id"],
                        "Patient Identifier": patient_id,
                        "Clinical Status": "active", # Use deactivatedate for inactive? Ask Jess and Ceci.
                        "Type": "allergy",
                        "FDB Code": "", # create mappings for Jess/Ceci
                        "Onset Date": "", # there is no onset date;
                        "Free Text Note": "",
                        "Reaction": reaction_text,
                        "Recorded Provider": allergy.get("lastmodifiedby", ""),
                    }

                    writer.writerow(row_to_write)

        print("CSV successfully made")


if __name__ == "__main__":
    loader = AllergyLoader('localhost')
    loader.create_rxnorm_mapping_file()
    # loader.make_csv()
