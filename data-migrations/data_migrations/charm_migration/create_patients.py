import csv, json

from data_migrations.template_migration.patient import PatientLoaderMixin
from data_migrations.utils import fetch_from_json, load_fhir_settings, load_simple_api_key, write_to_json
from data_migrations.charm_migration.utils import CharmPatientAPI
from data_migrations.template_migration.utils import FileWriterMixin

from data_migrations.template_migration.utils import validate_phone_number


STATE_CODE_MAP = {
    "Alabama": "AL",
    "Alaska": "AK",
    "American Samoa": "AS",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "District Of Columbia": "DC",
    "Federated States Of Micronesia": "FM",
    "Florida": "FL",
    "Georgia": "GA",
    "Guam": "GU",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Marshall Islands": "MH",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Northern Mariana Islands": "MP",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Palau": "PW",
    "Pennsylvania": "PA",
    "Puerto Rico": "PR",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virgin Islands": "VI",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
    # AE covers the following: https://help.nfc.usda.gov/publications/CLER-CARRIER/37612.htm
    "Armed Forces Europe": "AE",
    "Armed Forces Canada": "AE",
    "Armed Forces Middle East": "AE",
    "Armed Forces Pacific": "AP",
    "Armed Forces Americas": "AA",
    "Washington, D.C.": "DC",
}

class PatientLoader(PatientLoaderMixin, FileWriterMixin):
    def __init__(self, environment) -> None:
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.csv_file = 'PHI/patients.csv'
        self.json_file = 'PHI/patients.json'
        self.validation_error_file = 'results/PHI/errored_patient_validation.json'
        self.error_file = 'results/PHI/errored_patients.csv'
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)
        self.simple_api_key = load_simple_api_key(environment)

        self.corrected_us_patients_file = "mappings/corrected_us_patients.json"
        self.corrected_us_patients = fetch_from_json(self.corrected_us_patients_file)

        self.corrected_intl_patients_file = "mappings/corrected_intl_patients.json"
        self.corrected_intl_patients_map = fetch_from_json(self.corrected_intl_patients_file)

        self.patient_do_not_migrate_file = "mappings/patient_do_not_migrate_list.json"
        self.patient_do_not_migrate_list = fetch_from_json(self.patient_do_not_migrate_file)

        self.migrate_as_is_file = "mappings/migrate_as_is.json"
        self.migrate_as_is = fetch_from_json(self.migrate_as_is_file)

        self.patient_identifier_value = "Charm ID"
        super().__init__()

    def make_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        patient_list = charm_patient_api.fetch_patients()
        write_to_json(self.json_file, patient_list)

    def make_csv(self):
        headers = [
            "First Name",
            "Middle Name",
            "Last Name",
            "Date of Birth",
            "Sex at Birth",
            "Preferred Name",
            "Address Line 1",
            "Address Line 2",
            "City",
            "State",
            "Postal Code",
            "Country",
            "Mobile Phone Number",
            "Mobile Text Consent",
            "Home Phone Number",
            "Email",
            "Email Consent",
            "Timezone",
            "Clinical Note",
            "Administrative Note",
            "Identifier System 1",
            "Identifier Value 1",
            "Identifier System 2",
            "Identifier Value 2",
            "Identifier System 3",
            "Identifier Value 3",
            "Metadata",
        ]

        data = fetch_from_json(self.json_file)

        with open(self.csv_file, "w") as fhandle:
            writer = csv.DictWriter(
                fhandle,
                fieldnames=headers,
                delimiter=",",
                quotechar='"',
                quoting=csv.QUOTE_MINIMAL
            )
            writer.writeheader()

            state_abbreviations = set(STATE_CODE_MAP.values())

            for row in data:
                state = row["state"]
                # some states are full names and some are two digit codes
                if row["state"] != "" and state.upper() not in state_abbreviations:
                    state = STATE_CODE_MAP.get(state.title(), "ZZ") # default to international if not a US state

                metadata = []
                mobile_number = row["mobile"]
                home_number = row["home_phone"]

                # For international phone numbers, put them in metadata if they don't validate
                if row["country"] and row["country"].lower() != "us":
                    mobile_valid, mobile_number = validate_phone_number(row["mobile"], "mobile")
                    home_valid, home_number = validate_phone_number(row["home_phone"], "home_phone")

                    if not mobile_valid:
                        mobile_number = ""
                        metadata.append(
                            {
                                "key": "international_mobile_number",
                                "value": row["mobile"]
                            }
                        )

                    if not home_valid:
                        home_number = ""
                        metadata.append(
                            {
                                "key": "international_home_phone_number",
                                "value": row["home_phone"]
                            }
                        )

                row_to_write = {
                    "First Name": row["first_name"],
                    "Middle Name": "", # not in data
                    "Last Name": row["last_name"],
                    "Date of Birth": row["dob"],
                    "Sex at Birth": row["gender"].upper(),
                    "Preferred Name": "", # not in data
                    "Address Line 1": row["address_line1"],
                    "Address Line 2": row["address_line2"],
                    "City": row["city"],
                    "State": state,
                    "Postal Code": row["postal_code"],
                    "Country": row["country"],
                    "Mobile Phone Number": mobile_number,
                    "Mobile Text Consent": True if row["text_notification"] == "true" else "",
                    "Home Phone Number": home_number,
                    "Email": row["email"],
                    "Email Consent": True if row["email_notification"] == "true" else "",
                    "Timezone": "",
                    "Clinical Note": "",
                    "Administrative Note": "",
                    "Identifier System 1": self.patient_identifier_value,
                    "Identifier Value 1": row["patient_id"],
                    "Identifier System 2": "",
                    "Identifier Value 2": "",
                    "Identifier System 3": "",
                    "Identifier Value 3": "",
                    "Metadata": json.dumps(metadata)
                }

                if row["patient_id"] in self.patient_do_not_migrate_list:
                    print("Ignoring because on do not migrate list")
                    continue

                if row["patient_id"] in self.corrected_us_patients:
                    corrections = self.corrected_us_patients[row["patient_id"]]
                    row_to_write["Address Line 1"] = corrections["Address Line 1"]
                    row_to_write["Address Line 2"] = corrections["Address Line 2"]
                    row_to_write["City"] = corrections["City"]
                    row_to_write["State"] = corrections["State"]
                    row_to_write["Postal Code"] = corrections["Postal Code"]
                    row_to_write["Mobile Phone Number"] = corrections["Mobile Phone Number"]
                    row_to_write["Home Phone Number"] = corrections["Home Phone Number"]
                    print(f"updated corrections for patient id {row["patient_id"]}")

                if row["patient_id"] in self.corrected_intl_patients_map:
                    intl_corrections = self.corrected_intl_patients_map[row["patient_id"]]
                    row_to_write["Country"] = intl_corrections["Country"].lower()
                    row_to_write["Address Line 1"] = intl_corrections["Address Line 1"]
                    row_to_write["Address Line 2"] = intl_corrections["Address Line 2"]
                    row_to_write["City"] = intl_corrections["City"]
                    row_to_write["State"] = "ZZ"
                    row_to_write["Postal Code"] = intl_corrections["Postal Code"]

                    mobile_valid, mobile_number = validate_phone_number(row_to_write["Mobile Phone Number"], "Mobile Phone Number")
                    home_valid, home_number = validate_phone_number(row_to_write["Home Phone Number"], "Home Phone Number")

                    intl_metadata = []
                    if not mobile_valid:
                        intl_metadata.append(
                            {
                                "key": "international_mobile_number",
                                "value": row_to_write["Mobile Phone Number"]
                            }
                        )
                        row_to_write["Mobile Phone Number"] = ""

                    if not home_valid:
                        intl_metadata.append(
                            {
                                "key": "international_home_phone_number",
                                "value": row_to_write["Home Phone Number"]
                            }
                        )
                        row_to_write["Home Phone Number"] = ""
                    row_to_write["Metadata"] = json.dumps(intl_metadata)

                if row["patient_id"] in self.migrate_as_is:
                    as_is_corrections = self.migrate_as_is[row["patient_id"]]
                    row_to_write["Country"] = as_is_corrections["Country"].lower()
                    row_to_write["Address Line 1"] = as_is_corrections["Address Line 1"]
                    row_to_write["Address Line 2"] = as_is_corrections["Address Line 2"]
                    row_to_write["City"] = as_is_corrections["City"]
                    row_to_write["State"] = as_is_corrections["State"]
                    row_to_write["Postal Code"] = as_is_corrections["Postal Code"]
                    row_to_write["Mobile Phone Number"] = as_is_corrections["Mobile Phone Number"]

                writer.writerow(row_to_write)
        print(f"Successfully wrote to {self.csv_file}")

    def check_import_counts(self):
        data = fetch_from_json(self.json_file)
        patient_map = fetch_from_json(self.patient_map_file)
        for patient_record in data:
            patient_id = patient_record["patient_id"]
            if patient_id not in patient_map and patient_id not in self.patient_do_not_migrate_list:
                print(patient_id)


if __name__ == "__main__":
    patient_loader = PatientLoader("ways2well")

    # patient_loader.make_csv()
    # valid_rows = patient_loader.validate(delimiter=",")

    # patient_loader.load(valid_rows, system_unique_identifier=patient_loader.patient_identifier_value)
    patient_loader.check_import_counts()
