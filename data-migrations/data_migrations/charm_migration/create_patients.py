import csv

from data_migrations.template_migration.patient import PatientLoaderMixin
from data_migrations.utils import fetch_from_json, load_fhir_settings, write_to_json
from data_migrations.charm_migration.utils import CharmPatientAPI
from data_migrations.template_migration.utils import FileWriterMixin


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
    "Wyoming": "WY"
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
            "Identifier Value 3"
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
                if row["state"] != "" and state not in state_abbreviations:
                    state = STATE_CODE_MAP.get(state)
                    if not state:
                        # TODO - what do to with non-US addresses?
                        print("Skipping because of non-US address")
                        continue

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
                    "Mobile Phone Number": row["mobile"],
                    "Mobile Text Consent": True if row["text_notification"] == "true" else "",
                    "Home Phone Number": row["home_phone"],
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
                    "Identifier Value 3": ""
                }
                writer.writerow(row_to_write)

        print(f"Successfully wrote to {self.csv_file}")


if __name__ == "__main__":
    patient_loader = PatientLoader("phi-ways2well-test")
    # patient_loader.make_json()
    # patient_loader.make_csv()
    valid_rows = patient_loader.validate(delimiter=",")
    patient_loader.load(valid_rows, system_unique_identifier=patient_loader.patient_identifier_value)
