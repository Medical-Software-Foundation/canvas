import re, pytz, arrow, csv, json
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from data_migrations.template_migration.note import NoteMixin
from data_migrations.template_migration.utils import (
    validate_header,
    validate_required,
    validate_date,
    validate_enum,
    MappingMixin,
    FileWriterMixin,
)


class ConditionLoaderMixin(MappingMixin, NoteMixin, FileWriterMixin):
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow.
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect:

        Required Formats/Values (Case Insensitive):
            Patient Identifier: Canvas key, unique identifier defined on the demographics page
            Clinical Status: Active, Resolved
            ICD-10 Code: Conditions with codes that are not ICD-10 will not render properly in Canvas
            Onset Date: MM/DD/YYYY or YYYY-MM-DD
            Resolved Date: MM/DD/YYYY or YYYY-MM-DD
            Recorded Provider: Staff Canvas key.  If omitted, defaults to Canvas Bot
    """

    def validate_icd10_display_name(self, row):
        icd10_code = row["ICD-10 Code"].replace(".", "").replace("-", "")
        if icd10_code in self.icd10_map:
            return False, self.icd10_map[icd10_code]

        return True, f"Display lookup for ICD-10 {row['Name']}|{icd10_code} not found."

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
                    "ICD-10 Code",
                    "Onset Date",
                    "Free text notes",
                    "Resolved Date",
                    "Recorded Provider",
                    "Name"
                }
            )

            validations = {
                "Patient Identifier": [validate_required],
                "ICD-10 Code": [validate_required],
                "Onset Date": [validate_date],
                "Resolved Date": [validate_date],
                "Clinical Status": [validate_required, (validate_enum, {"possible_options": ['active', 'resolved']})]
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

                error, value = self.validate_icd10_display_name(row)
                if error:
                    errors[key].append(value)
                else:
                    row["ICD-10 Display"] = value

                if not error:
                    validated_rows.append(row)

        if errors:
            print(f"Some rows contained errors, please see {self.validation_error_file}.")
            write_to_json(self.validation_error_file, errors)
        else:
            print('All rows have passed validation!')

        return validated_rows

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

            practitioner_key = ""
            try:
                practitioner_key = self.map_provider(row['Recorded Provider'])
            except BaseException:
                practitioner_key = ""

            patient = row['Patient Identifier']
            patient_key = ""
            try:
                # try mapping required Canvas identifiers
                patient_key = self.map_patient(patient)
                note_id = row.get("Note ID") or self.get_or_create_historical_data_input_note(patient_key)
            except BaseException as e:
                self.ignore_row(row['ID'], e)
                continue

            payload = {
                "resourceType": "Condition",
                "extension": [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                        "valueId": note_id,
                    }
                ],
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": row['Clinical Status'],
                        }
                    ]
                },
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                                "code": "encounter-diagnosis",
                                "display": "Encounter Diagnosis"
                            }
                        ]
                    }
                ],
                "code": {
                    "coding": [{
                        "system": "http://hl7.org/fhir/sid/icd-10-cm",
                        "code": row['ICD-10 Code'],
                        "display": row['ICD-10 Display']
                    }]
                },
                "subject": {
                    "reference": f"Patient/{patient_key}"
                }

            }

            if onset := row['Onset Date']:
                payload['onsetDateTime'] = onset
            if resolved_date := row['Resolved Date']:
                payload['abatementDateTime'] = resolved_date
            if notes := row['Free text notes']:
                payload['note'] = [{"text": notes}]
            if practitioner_key:
                payload['recorder'] = {
                    "reference": f"Practitioner/{practitioner_key}"
                }

            #print(json.dumps(payload, indent=2))

            if 'note' in payload:
                if len(payload['note'][0]['text']) > 1000:
                    self.ignore_row(row['ID'], f"ignoring temporarily because of notes character limit {len(payload['note'][0]['text'])} > 1000")
                    continue

            try:
                canvas_id = self.fumage_helper.perform_create(payload)
                self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}|{row['ICD-10 Code']}")
                ids.add(row['ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)
