import re, pytz, arrow, csv, json
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from data_migrations.template_migration.utils import (
    validate_header,
    validate_required,
    validate_date,
    validate_enum,
    MappingMixin,
    FileWriterMixin
)
from data_migrations.template_migration.note import NoteMixin


class AllergyLoaderMixin(MappingMixin, NoteMixin, FileWriterMixin):
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow.
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect:

        Required Formats/Values (Case Insensitive):
            Patient Identifier: Canvas key, unique identifier defined on the demographics page
            Clinical Status: Active, Resolved
            Type: Allergy, Intolerance
            Onset Date: MM/DD/YYYY or YYYY-MM-DD
            Recorded Provider: Staff Canvas key.  If omitted, defaults to Canvas Bot
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
                    "Clinical Status",
                    "Type",
                    "FDB Code",
                    "Name",
                    "Onset Date",
                    "Free Text Note",
                    "Reaction",
                    "Recorded Provider"
                }
            )

            validations = {
                "ID": [validate_required],
                "Patient Identifier": [validate_required],
                "Clinical Status": [validate_required, (validate_enum, {"possible_options": ['active', 'inactive']})],
                "Type": [validate_required, (validate_enum, {'possible_options': ['allergy', 'intolerance']})],
                "FDB Code": [validate_required],
                "Name": [validate_required],
                "Onset Date": [validate_date],
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

    def load(self, validated_rows, note_kwargs={}):
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
                practitioner_key = self.map_provider(row['Recorded Provider'])
                note_id = row.get("Note ID") or self.get_or_create_historical_data_input_note(patient_key, **note_kwargs)
            except BaseException as e:
                self.ignore_row(row['ID'], e)
                continue

            # If an FDB code is delimited with "```", then we need to make 2 records - one for each code;
            fdb_codes = row["FDB Code"].split("```")
            for fdb in fdb_codes:
                payload = {
                    "resourceType": "AllergyIntolerance",
                    "extension": [
                        {
                            "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                            "valueId": note_id,
                        }
                    ],
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                                "code": row['Clinical Status']
                            }
                        ],
                    },
                    "verificationStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                                "code": "confirmed",
                                "display": "Confirmed"
                            }
                        ],
                        "text": "Confirmed"
                    },
                    "type": row['Type'],
                    "code": {
                        "coding": [
                            {
                                "system": "http://www.fdbhealth.com/",
                                "code": fdb,
                                "display": row["Name"]
                            }
                        ]
                    },
                    "patient": {
                        "reference": f"Patient/{patient_key}"
                    },
                    "note": (
                        ([{"text": row['Reaction']}] if row['Reaction'] else []) +
                        ([{"text": f"Notes: {row['Free Text Note']}"}] if row['Free Text Note'] else [])
                    )
                }

                if onset := row['Onset Date']:
                    payload['onsetDateTime'] = onset
                if practitioner_key:
                    payload['recorder'] = {
                        "reference": f"Practitioner/{practitioner_key}"
                    }

                # print(json.dumps(payload, indent=2))

                try:
                    canvas_id = self.fumage_helper.perform_create(payload)
                    self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}|{fdb}")
                    ids.add(row['ID'])
                except BaseException as e:
                    self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)
