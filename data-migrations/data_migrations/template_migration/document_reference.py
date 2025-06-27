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

class DocumentReferenceMixin(MappingMixin, FileWriterMixin, DocumentEncoderMixin):
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow.
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect.

        Since Documents are big, you may hit a `_csv.Error: field larger than field limit`
        error, then you can ingest as a JSON file where the keys match the CSV headers
    """

    def validate_rows(self, headers, rows):
        validated_rows = []
        errors = defaultdict(list)
        validate_header(headers,
            accepted_headers = {
                "ID",
                "Patient Identifier",
                "Type",
                "Clinical Date",
                "Category",
                "Document",
                "Description",
                "Provider",
            }
        )

        validations = {
            "ID": [validate_required],
            "Patient Identifier": [validate_required],
            "Category": [validate_required, (validate_enum, {"possible_options": ['patientadministrativedocument', 'uncategorizedclinicaldocument']})],
            "Type": [validate_required],
            "Document": [validate_required],
            "Clinical Date": [validate_required, validate_date],
        }

        for row in rows:
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

    def validate_as_csv(self, delimiter='|'):
        """
            Loop throw the CSV file to validate each row has the correct columns and values
            Append validated rows to a list to use to load.
            Export errors to a file/console

        """
        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            return self.validate_rows(reader.fieldnames, reader)

    def validate_as_json(self):
        rows = fetch_from_json(self.template_json_file)
        headers = list(rows[0].keys())
        return self.validate_rows(headers, rows)

    def base64_encode_file(self, file_path):
        with open(file_path, "rb") as fhandle:
            contents = fhandle.read()
            encoded_contents = base64.b64encode(contents)
            return encoded_contents.decode("utf-8")

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
                if not os.path.exists(f"{self.documents_files_dir}{fname}"):
                    missing_files_for_row.append(fname)

            if missing_files_for_row:
                missing_files.extend(missing_files_for_row)
                self.ignore_row(row['ID'], f"File(s) {", ".join(missing_files_for_row)} not found in supplied files.")
                continue

            if len(file_list) == 1:
                file_path = file_list[0]
                if file_path.endswith(".tiff") or file_path.endswith(".tif"):
                    pdf_output = self.tiff_to_pdf(f"{self.documents_files_dir}{file_path}")
                    b64_document_string = self.base64_encode_file(pdf_output)
                    # clean up the file
                    os.remove(pdf_output)
                elif file_path.endswith(".pdf"):
                    b64_document_string = self.base64_encode_file(f"{self.documents_files_dir}{file_path}")
                elif file_path.endswith(".png"):
                    b64_document_string = self.convert_and_base64_encode([f"{self.documents_files_dir}{file_path}"])
                elif file_path.endswith(".jpeg") or file_path.endswith(".jpg"):
                    b64_document_string = self.convert_and_base64_encode([f"{self.documents_files_dir}{file_path}"])
                else:
                # This shouldn't ever happen with the current file set we have.
                    self.error_row(row["ID"], "Error converting document")
            elif len(file_list) > 1:
                b64_document_string = self.convert_and_base64_encode([f"{self.documents_files_dir}{p}" for p in file_list])


            payload = {
                "resourceType": "DocumentReference",
                "extension": [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-comment",
                        "valueString": row['Description']
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-clinical-date",
                        "valueDate": row['Clinical Date']
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-review-mode",
                        "valueCode": "RN"
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-reviewer",
                        "valueReference": {
                            "reference": "Practitioner/5eede137ecfe4124b8b773040e33be14",
                        }
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-priority",
                        "valueBoolean": False
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-requires-signature",
                        "valueBoolean": False
                    }
                ],
                "status": "current",
                "type": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": row['Type']
                        }
                    ]
                },
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://schemas.canvasmedical.com/fhir/document-reference-category",
                                "code": row['Category']
                            }
                        ]
                    }
                ],
                "subject": {
                    "reference": f"Patient/{patient_key}",
                    "type": "Patient"
                },
                "content": [
                    {
                        "attachment": {
                            "contentType": "application/pdf",
                            "data": b64_document_string
                        }
                    }
                ]
            }

            canvas_staff_key = self.doctor_map.get(row["Provider"])
            if canvas_staff_key:
                payload["author"] = [
                    {
                        "reference": f"Practitioner/{canvas_staff_key}",
                        "type": "Practitioner"
                    }
                ]

            #print(json.dumps(payload, indent=2))

            try:
                canvas_id = self.fumage_helper.perform_create(payload)
                self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}")
                ids.add(row['ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)

        if missing_files:
            print("Some Files were missing:")
            print(missing_files)
