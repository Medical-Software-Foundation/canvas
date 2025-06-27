import os
import arrow

from data_migrations.utils import (
    fetch_from_json,
    fetch_from_csv,
    write_to_json,
    fetch_complete_csv_rows,
    load_fhir_settings
)

from data_migrations.template_migration.lab_report import LabReportMixin


class LabReportLoader(LabReportMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/labresults/labresults.json"
        self.labresults_files_dir = "PHI/labresults"
        self.temp_pdf_dir = "PHI/pdf_temp"
        self.validation_error_file = 'results/PHI/errored_labreport_validation.json'
        self.done_file = 'results/done_lab_reports.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.error_file = 'results/errored_lab_reports.csv'
        self.ignore_file = f"results/ignored_lab_reports.csv"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.fumage_helper = load_fhir_settings(environment)
        self.blank_pdf_file = "template_files/blank_pdf.pdf"
        self.blank_pdf_b64_string = self.base64_encode_file(self.blank_pdf_file)

        super().__init__(*args, **kwargs)

    def get_observation_date(self, labresult):
        date_val = None

        if observation_dt_val := labresult.get("observationdatetime"):
            return observation_dt_val
        elif observation_date_val := labresult.get("observationdate"):
            date_val = observation_date_val
        elif encounter_date_val := labresult.get("encounterdate"):
            date_val = encounter_date_val

        if date_val:
            return arrow.get(date_val, "MM/DD/YYYY", tzinfo="America/New York").isoformat()
        return None

    def strip_comparator(self, value):
        comparators = [">=", "<=", ">", "<"]
        for comparator in comparators:
            if value.startswith(comparator):
                return comparator, value[len(comparator):]
        return "", value


    def create_fhir_payload(self, labresult, canvas_patient_key):
        validation_errors = []

        api_payload = {
            "resourceType": "Parameters",
            "parameter": []
        }

        observation_date_val = self.get_observation_date(labresult)

        if not observation_date_val:
            validation_errors.append("Missing observation date")

        b64_document_string = ""

        if labresult.get("originaldocument", {}).get("reference"):
            file_path = labresult["originaldocument"]["reference"]
            if file_path.endswith(".tiff"):
                pdf_output = self.tiff_to_pdf(f"{self.labresults_files_dir}{file_path}")
                b64_document_string = self.base64_encode_file(pdf_output)
                # clean up the file
                os.remove(pdf_output)
            elif file_path.endswith(".pdf"):
                b64_document_string = self.base64_encode_file(f"{self.labresults_files_dir}{file_path}")
            elif file_path.endswith(".png"):
                b64_document_string = self.convert_and_base64_encode([f"{self.labresults_files_dir}{file_path}"], custom_name=labresult["labresultid"])
            elif file_path.endswith(".jpeg") or file_path.endswith(".jpg"):
                b64_document_string = self.convert_and_base64_encode([f"{self.labresults_files_dir}{file_path}"], custom_name=labresult["labresultid"])
            else:
                # This shouldn't ever happen with the current file set we have.
                validation_errors.append("Unsupported file format for document")
        elif labresult.get("pages"):
            documents = [(int(page["pageordering"]), page["reference"]) for page in labresult["pages"]]
            # sort to get the correct page ordering
            documents.sort()
            documents = [f"{self.labresults_files_dir}{doc[1]}" for doc in documents]
            b64_document_string = self.convert_and_base64_encode(documents, custom_name=labresult["labresultid"])
        else:
            b64_document_string = self.blank_pdf_b64_string
            # validation_errors.append("No file present in data")

        lab_report_parameter = {
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
                    "reference": f"Patient/{canvas_patient_key}",
                    "type": "Patient"
                },
                "presentedForm": [
                    {
                        "data": b64_document_string, # base64 encoded PDF file
                        "contentType": "application/pdf"
                    }
                ],
                "effectiveDateTime": observation_date_val,
                "code": {
                    "coding": []
                }
            }
        }

        api_payload["parameter"].append(lab_report_parameter)

        lab_test_result_loinc = labresult.get("labresultloinc")
        lab_test_result_display = labresult.get("description")
        # If there is not sufficient information for the lab test (display, coding), then
        # return early. If there is a document, the document will still be attempted to be uploaded (unless it is the blank PDF fallback).
        if not all([lab_test_result_display, lab_test_result_loinc]):
            # We can't upload if there is not sufficient lab test data and no file.
            if b64_document_string == self.blank_pdf_b64_string:
                validation_errors.append("Cannot upload result because there is no lab result loinc or display and there is no file present.")
            if validation_errors:
                api_payload = None
            if not validation_errors:
                self.ignore_row(labresult["labresultid"], f"Missing lab test LOINC and/or display for labresult ID {labresult["labresultid"]}. Will still attempt to upload the document.")
            return api_payload, validation_errors

        lab_test_part = {
            "name": "labTest",
            "resource": {
                "resourceType": "Observation",
                "code": {
                    "text": lab_test_result_display,
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": lab_test_result_loinc,
                            "display": lab_test_result_display
                        }
                    ]
                },
                "effectiveDateTime": observation_date_val,
                "status": "final"
            }
        }

        lab_values = []

        for observation in labresult.get("observations", []):
            observation_identifier = observation.get("observationidentifier", "")

            observation_status = observation.get("resultstatus", "final")
            if observation_status == "incomplete":
                observation_status = "preliminary"
            if observation_status not in ["amended", "cancelled", "corrected", "entered-in-error", "final", "preliminary", "registered", "unknown"]:
                self.ignore_row(labresult["labresultid"], f"Ignoring lab value with observationidentifier {observation_identifier} due to unsupported resultstatus. Will still attempt to upload the document.")
                continue

            observation_loinc = observation.get("loinc")
            if not observation_loinc:
                self.ignore_row(labresult["labresultid"], f"Ignoring lab value with observationidentifier {observation_identifier} due to missing LOINC code. Will still attempt to upload the document.")
                continue

            observation_loinc_display = observation.get("analytename")
            if not observation_loinc_display:
                self.ignore_row(labresult["labresultid"], f"Ignoring lab value with observationidentifier {observation_identifier} due to missing LOINC display. Will still attempt to upload the document.")
                continue

            lab_value_value = observation.get("value", "")
            lab_value_units = observation.get("units", "")

            if observation_status == "preliminary" and lab_value_value == "" and lab_value_units == "":
                self.ignore_row(labresult["labresultid"], f"Ignoring lab value with observationidentifier {observation_identifier} due to preliminary data that is missing values and units. Will still attempt to upload the document.")
                continue

            value_key = "valueQuantity"
            value_val = {
                "value": lab_value_value,
                "unit": lab_value_units,
                "system": "http://unitsofmeasure.org"
            }

            if lab_value_value and not lab_value_units:
                value_key = "valueString"
                value_val = lab_value_value

            comparator = ""
            if value_key == "valueQuantity" and any(
                [
                    lab_value_value.startswith(">"),
                    lab_value_value.startswith("<"),
                    lab_value_value.startswith(">="),
                    lab_value_value.startswith("<="),
                 ]
            ):
                comparator, val = self.strip_comparator(lab_value_value)
                value_val["value"] = val
                value_val["comparator"] = comparator

            # if a valueQuantity value doesn't convert to a float, make it a valueString instead
            if value_key == "valueQuantity":
                try:
                    float(value_val["value"])
                except ValueError:
                    value_key = "valueString"
                    value_val = f"{lab_value_value} {lab_value_units}"

            lab_value_part = {
                "name": "labValue",
                "resource": {
                    "resourceType": "Observation",
                    "status": observation_status,
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": observation_loinc,
                                "display": observation_loinc_display
                            }
                        ]
                    },
                    "effectiveDateTime": observation_date_val,
                    value_key: value_val
                }
            }

            if observation.get("referencerange"):
                lab_value_part["resource"]["referenceRange"] = [
                    {
                        "text": observation["referencerange"]
                    }
                ]

            # abnormalflag possible values are:
            # 'normal', 'alert low', 'below low normal', 'above high normal', 'low', 'high', 'abnormal', 'alert high', 'critical high';
            # Canvas only supports an 'Abnormal' status. Any status besides normal should be marked as abnormal in Canvas.

            if observation.get("abnormalflag") in ["alert low", "below low normal", "above high normal", "low", "high", "abnormal", "alert high", "critical high"]:
                lab_value_part["resource"]["interpretation"] = [
                    {
                        "text": "Abnormal",
                        "coding": [
                            {
                                "code": "A",
                                "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                                "display": "Abnormal"
                            }
                        ]
                    }
                ]

            lab_values.append(lab_value_part)

        api_payload["parameter"].append(
            {
                "name": "labTestCollection",
                "part": [
                    lab_test_part,
                    *lab_values
                ]
            }
        )

        if validation_errors:
            api_payload = None
        return api_payload, validation_errors


    def validate_record(self, labresult, canvas_patient_key):
        payload, errors = self.create_fhir_payload(labresult, canvas_patient_key)
        return payload, errors


    def validate(self):
        data = fetch_from_json(self.json_file)

        validation_errors = {}
        valid_payloads = []
        already_seen = []

        for obj in data:
            patient_enterprise_id = obj["patientdetails"]["enterpriseid"]

            for result in obj["labresults"]:
                labresult_id = result["labresultid"]

                if labresult_id in self.done_records or labresult_id in already_seen:
                    # skip those we've already loaded
                    continue

                canvas_patient_key = ""
                try:
                    canvas_patient_key = self.map_patient(patient_enterprise_id)
                except BaseException as e:
                    self.ignore_row(labresult_id, e)
                    continue

                payload, errors = self.validate_record(result, canvas_patient_key)
                if errors:
                    validation_errors[labresult_id] = errors
                else:
                    valid_payload_dict = {
                        "unique_attribute": labresult_id,
                        "patient_id": patient_enterprise_id,
                        "canvas_patient_key": canvas_patient_key,
                        "payload": payload
                    }
                    valid_payloads.append(valid_payload_dict)
                already_seen.append(labresult_id)
        write_to_json(self.validation_error_file, validation_errors)
        return valid_payloads


    def page_order_issue_research(self):
        done_records = fetch_from_csv(self.done_file, key="id", delimiter="|")
        problem_file_ids = []
        data = fetch_from_json(self.json_file)
        for obj in data:
            patient_enterprise_id = obj["patientdetails"]["enterpriseid"]

            for labresult in obj["labresults"]:
                labresult_id = labresult["labresultid"]

                # these would have used the original document
                if labresult.get("originaldocument", {}).get("reference"):
                    pass

                elif labresult.get("pages"):
                    has_double_digit_pages = [(int(page["pageordering"]), page["reference"]) for page in labresult["pages"] if int(page["pageordering"]) > 9]
                    if has_double_digit_pages and labresult_id in self.done_records:
                        info = [labresult_id, done_records[labresult_id][0]['canvas_diagnosticreport_id']]
                        if info not in problem_file_ids:
                            problem_file_ids.append(info)
        problem_file_ids.sort()
        print(len(problem_file_ids))
        print(len(list(set([i[0] for i in problem_file_ids]))))
        write_to_json("problem_file_ids.json", problem_file_ids)


if __name__ == "__main__":
    loader = LabReportLoader(environment="phi-test-accomplish")
    loader.page_order_issue_research()
    # valid_rows = loader.validate()
    # loader.load(valid_rows)
