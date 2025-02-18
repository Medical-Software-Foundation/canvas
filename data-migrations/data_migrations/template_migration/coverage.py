import re, pytz, arrow, csv, json
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from data_migrations.template_migration.utils import (
    validate_header,
    validate_required,
    validate_date,
    validate_enum,
    MappingMixin,
    FileWriterMixin,
)


class CoverageLoaderMixin(MappingMixin, FileWriterMixin):
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow.
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect:

        A unique ID for each line item must be provided to avoid duplicate entries
        - If the subscriber is not the patient, the subscriber must be added as a patient on the demographics tab
        - All coverages must be added to Canvas before migration can run
        - Payor ID must match payor ID in your instance
        - Payor ID can be found by utilizing the OrganizationSearch FHIR endpoint

        Required Formats/Values:
            Patient Identifier: Canvas key, unique identifier defined on the demographics page
            Type: Supported list available in CoverageCreate documentation
            Subscriber: Only required if patient is not subscriber - Canvas key, unique identifier defined on the demographics page
            Relationship to Subscriber: self, child, spouse, other, injured
            Coverage Start Date: MM/DD/YYYY or YYYY-MM-DD
            Order: Number 1-5
            "
    """

    def validate(self, delimiter='|'):
        """
            Loop throw the CSV file to validate each row has the correct columns and values
            Append validated rows to a list to use to load.
            Export errors to a file/console

        """
        validated_rows = []
        errors = defaultdict(list)
        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            validate_header(reader.fieldnames,
                accepted_headers = {
                    "ID",
                    "Patient Identifier",
                    "Type",
                    "Subscriber",
                    "Member ID",
                    "Relationship to Subscriber",
                    "Coverage Start Date",
                    "Payor ID",
                    "Order",
                    "Group Number",
                    "Plan Name"
                }
            )

            validations = {
                "ID": [validate_required],
                "Patient Identifier": [validate_required],
                "Subscriber": [validate_required],
                "Member ID": [validate_required],
                "Coverage Start Date": [validate_date],
                "Payor ID": [validate_required],
                "Order": [validate_required, (validate_enum, {"possible_options": ['1', '2', '3', '4', '5']})],
                "Relationship to Subscriber": [(validate_enum, {"possible_options": ['self', 'child', 'spouse', 'other', 'injured']})]
            }

            for row in reader:
                error = False
                key = f"{row['ID']} {row['Patient Identifier']}"

                for field, validator_funcs in validations.items():
                    for validator_func in validator_funcs:
                        kwargs = {}
                        if isinstance(validator_func, tuple):
                            validator_func, kwargs = validator_func

                        valid, value = validator_func(row[field].strip(), field, **kwargs)
                        if valid:
                            row[field] = value
                        else:
                            errors[key].append(value)
                            error = True

                if not error:
                    validated_rows.append(row)

        if errors:
            print(f"Some rows contained errors, please see {self.validation_error_file}.")
            write_to_json(self.validation_error_file, errors)
        else:
            print('All rows have passed validation!')

        return validated_rows

    def map_payor(self, payor):
        # map the location if needed
        if hasattr(self, "payor_map"):
            payor_id = self.payor_map.get(payor)

            if not payor_id:
                raise Exception(f'    Ignoring due no payor map with {payor}')

            return payor_id
        return payor

    def find_subscriber(self, first_name: str, last_name: str, dob: str):
        # Performs a Fumage search to find a patient based on first_name, last_name and dob;
        # Will return the patient ID from the source API by doing a reverse mapping from the Canvas
        # patient key.
        print("Looking up subscriber")
        patient_search_response = self.fumage_helper.search(
            "Patient",
            {
                "given": first_name,
                "family": last_name,
                "birthDate": dob
            }
        )
        response_data = patient_search_response.json()
        if response_data['total'] == 1:
            return self.reverse_patient_map.get(response_data['entry'][0]['resource']['id'])

    def load(self, validated_rows):
        """
            Takes the validated rows from self.validate() and
            loops through to send them off the FHIR Create

            Outputs to CSV to keep track of records
            If any  error, the error message will output to the errored file
        """

        self.patient_map = fetch_from_json(self.patient_map_file)

        total_count = len(validated_rows)
        print(f'      Found {len(validated_rows)} records')
        ids = set()
        for i, row in enumerate(validated_rows):
            print(f'Ingesting ({i+1}/{total_count})')

            if row['ID'] in ids or row['ID'] in self.done_records:
                print(' Already did record')
                continue

            patient = row['Patient Identifier']
            patient_key = ""
            try:
                # try mapping required Canvas identifiers
                patient_key = self.map_patient(patient)
                subscriber_key = self.map_patient(row['Subscriber'])
                payer_id = self.map_payor(row['Payor ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)
                continue

            payload = {
              "resourceType": "Coverage",
              "order": row['Order'],
              "status": "active",
              "subscriber": {
                "reference": f"Patient/{subscriber_key}"
              },
              "subscriberId": row['Member ID'],
              "beneficiary": {
                "reference": f"Patient/{patient_key}"
              },
              "relationship": {
                "coding": [
                  {
                    "system": "http://hl7.org/fhir/ValueSet/subscriber-relationship",
                    "code": row['Relationship to Subscriber']
                  }
                ]
              },
              "payor": [
               {
                 "identifier": {
                   "system": "https://www.claim.md/services/era/",
                   "value": payer_id
                 }
               }
             ],
              "class": (
                ([{
                  "type": {
                    "coding": [
                      {
                        "system": "http://hl7.org/fhir/ValueSet/coverage-class",
                        "code": "plan"
                      }
                    ]
                  },
                  "value": row['Plan Name']
                }] if row['Plan Name'] else []) +
                ([{
                  "type": {
                    "coding": [
                      {
                        "system": "http://hl7.org/fhir/ValueSet/coverage-class",
                        "code": "group"
                      }
                    ]
                  },
                  "value": row['Group Number']
                }] if row['Group Number'] else [])
              ),
                "period": {
                    "start": row["Coverage Start Date"]
                }
            }

            #print(json.dumps(payload, indent=2))

            try:
                canvas_id = self.fumage_helper.perform_create(payload)
                self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}")
                ids.add(row['ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)
