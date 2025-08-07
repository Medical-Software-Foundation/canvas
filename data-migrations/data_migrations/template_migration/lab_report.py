import base64, csv, json, os
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from data_migrations.template_migration.utils import (
    validate_header,
    validate_required,
    validate_date,
    validate_enum,
    MappingMixin,
    FileWriterMixin,
    DocumentEncoderMixin,
)

class LabReportMixin(MappingMixin, FileWriterMixin, DocumentEncoderMixin):
    def load(self, validated_rows):
        ids = set()
        for payload_dict in validated_rows:
            if payload_dict["unique_attribute"] in self.done_records or payload_dict["unique_attribute"] in ids:
                print(' Already did record')
                continue
            try:
                canvas_id = self.fumage_helper.perform_create_lab_report(payload_dict["payload"])
                self.done_row(f"{payload_dict['unique_attribute']}|{payload_dict['patient_id']}|{payload_dict['canvas_patient_key']}|{canvas_id}")
                ids.add(payload_dict['unique_attribute'])
            except BaseException as e:
                self.error_row(f"{payload_dict['unique_attribute']}|{payload_dict['patient_id']}|{payload_dict['canvas_patient_key']}", f"{str(e)}")


class LabReportDocumentOnlyMixin(MappingMixin, FileWriterMixin, DocumentEncoderMixin):
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow.
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect.

        Since Documents are big, you may hit a `_csv.Error: field larger than field limit`
        error, then you can ingest as a JSON file where the keys match the CSV headers
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
                    "Lab Date",
                    "Document",
                    "Lab Test Name",
                    "Lab LOINC Code",
                }
            )

            validations = {
                "ID": [validate_required],
                "Patient Identifier": [validate_required],
                "Document": [validate_required],
                "Lab Date": [validate_required, validate_date],
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
        missing_files = []
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
            except BaseException as e:
                self.ignore_row(row['ID'], e)
                continue

            file_list = json.loads(row["Document"])
            b64_document_string = ""

            missing_files_for_row = []
            for fname in file_list:
                print(f"{self.documents_files_dir}{fname}")
                if not os.path.exists(f"{self.documents_files_dir}{fname}"):
                    missing_files_for_row.append(fname)

            if missing_files_for_row:
                missing_files.extend(missing_files_for_row)
                self.ignore_row(row['ID'], f"File(s) {', '.join(missing_files_for_row)} not found in supplied files.")
                continue

            b64_document_string = self.get_b64_document_string(file_list)
            if not b64_document_string:
                # This shouldn't ever happen with the current file set we have.
                self.error_row(row["ID"], "Error converting document")
                continue

            date = f"{row['Lab Date']}T00:00:00+00:00"

            payload = {
                "resourceType": "Parameters",
                "parameter": [
                    {
                        "name": "labReport",
                        "resource": {
                            "resourceType": "DiagnosticReport",
                            "status": "final",
                            "category": [
                                {
                                    "coding": [
                                        {
                                            "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                                            "code": "LAB",
                                            "display": "Laboratory"
                                        }
                                    ]
                                }
                            ],
                            "subject": {
                                "reference": f"Patient/{patient_key}",
                                "type": "Patient"
                            },
                            "presentedForm": [
                                {
                                    "data": b64_document_string,
                                    "contentType": "application/pdf"
                                }
                            ],
                            "effectiveDateTime": date,
                            "code": {
                                "coding": []
                            }
                        }
                    }
                ]
            }

            if row['Lab Test Name']:
                payload['parameter'].append({
                    "name": "labTestCollection",
                    "part": [
                        {
                            "name": "labTest",
                            "resource": {
                                "resourceType": "Observation",
                                "code": {
                                    "text": row['Lab Test Name'],
                                    "coding": [
                                        {
                                            "system": "http://loinc.org",
                                            "code": row['Lab LOINC Code'],
                                            "display": row['Lab Test Name']
                                        }
                                    ]
                                },
                                "effectiveDateTime": date,
                                "status": "final"
                            }
                        }
                    ]
                })

            # print(json.dumps(payload, indent=2))
            # return

            try:
                canvas_id = self.fumage_helper.perform_create_lab_report(payload)
                self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}")
                ids.add(row['ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)


        if missing_files:
            print("Some Files were missing:")
            print(missing_files)
