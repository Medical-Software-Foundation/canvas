import os
import arrow
import time
import json

from data_migrations.utils import (
    fetch_from_json,
    fetch_from_csv,
    write_to_json,
    fetch_complete_csv_rows,
    load_fhir_settings
)

from data_migrations.charm_migration.utils import CharmFHIRAPI, CharmPatientAPI
from data_migrations.template_migration.lab_report import LabReportMixin

from data_migrations.charm_migration.utils import APIException


class LabReportLoader(LabReportMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/labresults/labresults.json"
        self.json_file_expanded = "PHI/labresults/labresults_expanded.json"
        self.json_file_fhir = "PHI/labresults/labresults_fhir.json"
        self.labresults_files_dir = "PHI/labresults/files"
        self.temp_pdf_dir = "PHI/pdf_temp"
        self.validation_error_file = 'results/PHI/errored_labreport_validation.json'
        self.done_file = 'results/done_lab_reports.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.error_file = 'results/errored_lab_reports.csv'
        self.ignore_file = f"results/ignored_lab_reports.csv"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.fumage_helper = load_fhir_settings(environment)
        self.test_loinc_mapping_file = "mappings/labtest_loinc_map.json"
        self.lab_test_loinc_mapping = fetch_from_json(self.test_loinc_mapping_file)
        # self.blank_pdf_file = "template_files/blank_pdf.pdf"
        # self.blank_pdf_b64_string = self.base64_encode_file(self.blank_pdf_file)

        super().__init__(*args, **kwargs)

    def make_patient_api_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        lab_results = charm_patient_api.fetch_lab_results()
        write_to_json(self.json_file, lab_results)

    def retrieve_files(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        lab_results = fetch_from_json(self.json_file)
        for lab_result in lab_results:
            group_id = lab_result["group_id"]
            if pdf_url := lab_result.get("pdf_link"):
                pdf_response = charm_patient_api.fetch_lab_file(pdf_url)
                with open(f"{self.labresults_files_dir}/{group_id}.pdf", "wb") as fhandle:
                    fhandle.write(pdf_response.content)

    def retrieve_expanded_lab_values(self):
        lab_results = fetch_from_json(self.json_file)
        lab_result_ids = [lr["group_id"] for lr in lab_results]
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        expanded_lab_results = charm_patient_api.fetch_expanded_lab_results(lab_result_ids)
        write_to_json(self.json_file_expanded, expanded_lab_results)

    def look_up_lab_test_loinc_codes(self):
        test_entry_dict = fetch_from_json(self.test_loinc_mapping_file)
        charm_fhir_api = CharmFHIRAPI(environment=self.environment)
        labs_expanded = fetch_from_json(self.json_file_expanded)
        count = 0
        for labresult in labs_expanded.values():
            for labtest in labresult["result_report"]["tests"]:
                test_entry_id = labtest["test_entry_id"]
                if test_entry_id not in test_entry_dict and test_entry_id:
                    print(f"Looking up test entry for {test_entry_id} - Count {count}")
                    try:
                        fhir_diagnostic_report = charm_fhir_api.get(f"/DiagnosticReport/{test_entry_id}-LAB")
                    except APIException as e:
                        print(e)
                        continue
                    response_data = fhir_diagnostic_report.json()
                    test_entry_dict[test_entry_id] = response_data["code"]
                    # incremental write in case of failures
                    if count % 1000 == 0:
                        write_to_json(self.test_loinc_mapping_file, test_entry_dict)
                count += 1
        write_to_json(self.test_loinc_mapping_file, test_entry_dict)

    def strip_comparator(self, value):
        comparators = [">=", "<=", ">", "<"]
        for comparator in comparators:
            if value.startswith(comparator):
                return comparator, value[len(comparator):]
        return "", value

    def remove_items_with_missing_codings_or_values(self, payload):
        new_payload = {
            "resourceType": "Parameters",
            "parameter": []
        }
        for parameter in payload["parameter"]:
            if parameter["name"] == "labReport":
                new_payload["parameter"].append(parameter)
            elif parameter["name"] == "labTestCollection":
                new_lab_test_collection = {
                    "name": "labTestCollection",
                    "part": []
                }
                for part in parameter["part"]:
                    if part["name"] == "labTest":
                        if part["resource"]["code"]["coding"][0]["code"] and part["resource"]["code"]["coding"][0]["display"]:
                            new_lab_test_collection["part"].append(part)
                        else:
                            # if we don't have a coding or display for the test, we can't import the test or values
                            break
                    elif part["name"] == "labValue":
                        if part["resource"]["code"]["coding"][0]["code"] and bool(("valueQuantity" in part["resource"] and part["resource"]["valueQuantity"]["value"]) or ("valueString" in part["resource"] and part["resource"]["valueString"])):
                            new_lab_test_collection["part"].append(part)
                        else:
                            continue
                if new_lab_test_collection["part"]:
                    new_payload["parameter"].append(new_lab_test_collection)
        return new_payload


    def create_lab_report_payloads(self):
        labs_expanded = fetch_from_json(self.json_file_expanded)

        status_dict = {
            "Final": "final",
            "Canceled": "cancelled",
            "Corrected": "corrected",
            "Pending": "preliminary",
            "Deprecated": "unknown"
        }

        payloads = []

        for lab_report in labs_expanded.values():
            lab_report_id = lab_report["result_report"]["group_id"]
            patient_id = lab_report["result_report"].get("patient_details", {}).get("patient_id")
            patient_key = ""

            if patient_id:
                patient_key = self.patient_map.get(patient_id)

            if not patient_key:
                self.ignore_row(lab_report_id, "Ignoring due to no patient map")
                continue

            date_fmt = "MMM DD, YYYY HH:mm:ss"
            date_fmt_collected = "MMM DD, YYYY HH:mm A"
            use_format = date_fmt_collected

            clinical_date = lab_report["result_report"].get("specimen", {}).get("collection_date")
            if not clinical_date:
                clinical_date = lab_report["result_report"].get("specimen", {}).get("recevied_date") # misspelled in data
                use_format = date_fmt
            if not clinical_date:
                clinical_date = lab_report["result_report"]["reported_date"]
                use_format = date_fmt

            clinical_date_formatted = arrow.get(clinical_date, use_format).replace(tzinfo="US/Central").isoformat()

            base64_file_str = ""
            report_file_path = f"{self.labresults_files_dir}/{lab_report["result_report"]["group_id"]}.pdf"
            if os.path.exists(report_file_path):
                base64_file_str = self.base64_encode_file(report_file_path)
            else:
                base64_file_str = ""

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
                                    "data": base64_file_str,
                                    "contentType": "application/pdf"
                                }
                            ],
                            "effectiveDateTime": clinical_date_formatted,
                            "code": {
                                "coding": []
                            }
                        }
                    }
                ]
            }


            lab_test_loinc_code = ""
            lab_test_loinc_display = ""
            for lab_test in lab_report["result_report"]["tests"]:
                test_entry_id = lab_test["test_entry_id"]
                lab_test_codings = self.lab_test_loinc_mapping.get(test_entry_id)
                if lab_test_codings:
                    loinc_coding_list = [c for c in lab_test_codings.get("coding", []) if c["system"] == "http://loinc.org"]
                    if loinc_coding_list:
                        loinc_dict = loinc_coding_list[0]
                        lab_test_loinc_code = loinc_dict.get("code", "")
                        lab_test_loinc_display = loinc_dict.get("display", "")

                lab_test_status = status_dict.get(lab_test.get("status"), "final")

                lab_test_name = lab_test.get("name")

                lab_test_collection = {
                    "name": "labTestCollection",
                    "part": [
                        {
                            "name": "labTest",
                            "resource": {
                                "resourceType": "Observation",
                                "code": {
                                    "text": lab_test_name,
                                    "coding": [
                                        {
                                            "system": "http://loinc.org",
                                            "code": lab_test_loinc_code,
                                            "display": lab_test_loinc_display
                                        }
                                    ]
                                },
                                "effectiveDateTime": clinical_date_formatted,
                                "status": lab_test_status
                            }
                        }
                    ]
                }

                for lab_value in lab_test["parameters"]:
                    loinc_code = lab_value.get("loinc_code", "")
                    loinc_display = lab_value["name"]

                    value_dict_key = ""
                    value_dict = {}
                    val = lab_value.get("value", "")
                    if lab_value.get("unit"):
                        value_dict_key = "valueQuantity"
                        value_dict = {
                            "value": val,
                            "unit": lab_value["unit"],
                            "system": "http://unitsofmeasure.org"
                        }

                        if  any(
                            [
                                val.startswith(">"),
                                val.startswith("<"),
                                val.startswith(">="),
                                val.startswith("<="),
                            ]
                        ):
                            comparator, l_val = self.strip_comparator(val)
                            value_dict["value"] = l_val
                            value_dict["comparator"] = comparator
                    else:
                        value_dict_key = "valueString"
                        value_dict = val # actually a string

                    # if a valueQuantity value doesn't convert to a float, make it a valueString instead
                    if value_dict_key == "valueQuantity":
                        try:
                            float(val)
                        except ValueError:
                            value_dict_key = "valueString"
                            value_dict = f"{val} {lab_value.get("unit", '')}".strip()

                    ref_range_dict = {}
                    if ref_low := lab_value.get("ref_min"):
                        ref_range_dict["low"] = {"value": str(ref_low)}
                    if ref_high := lab_value.get("ref_max"):
                        ref_range_dict["high"] = {"value": str(ref_high)}
                    if ref_text := lab_value.get("ref_range"):
                        ref_range_dict["text"] = str(ref_text)

                    lab_value_status = lab_value.get("status")
                    if not lab_value_status:
                        lab_value_status = "Final"

                    lab_value_dict = {
                        "name": "labValue",
                        "resource": {
                            "resourceType": "Observation",
                            "status": status_dict[lab_value_status],
                            "code": {
                                "coding": [
                                    {
                                        "system": "http://loinc.org",
                                        "code": loinc_code,
                                        "display": loinc_display
                                    }
                                ]
                            },
                            "effectiveDateTime": clinical_date_formatted,
                            value_dict_key: value_dict,
                        }
                    }

                    if ref_range_dict:
                        lab_value_dict["resource"]["referenceRange"] = [ref_range_dict]


                    interpretation = lab_value.get("interpretation")

                    if interpretation and interpretation.lower() != "normal":
                        lab_value_dict["resource"]["interpretation"] = [
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

                    lab_test_collection["part"].append(lab_value_dict)
                payload["parameter"].append(lab_test_collection)


            # Remove any tests or values that are missing codings

            payload = self.remove_items_with_missing_codings_or_values(payload)

            payloads.append(
                {
                    "payload": payload,
                    "unique_attribute": lab_report["result_report"]["group_id"],
                    "patient_id": patient_id,
                    "canvas_patient_key": patient_key
                }
            )

        return payloads


    def validate_payloads(self, payloads):
        missing_file = 0
        missing_codes = 0
        missing_values = 0
        valid_reports = 0
        total_count = 0

        valid_payloads = []

        for payload in payloads:
            total_count += 1
            is_missing_file = False
            missing_lab_test_codes = []
            missing_lab_value_codes = []
            missing_lab_value_values = []

            lab_payload = payload["payload"]
            presented_form_str = lab_payload["parameter"][0]["resource"]["presentedForm"][0]["data"]
            if not presented_form_str:
                is_missing_file = True

            for lab_test_collection in lab_payload["parameter"][1:]:
                lab_test_coding = lab_test_collection["part"][0]["resource"]["code"]["coding"][0]
                if not lab_test_coding["code"]:
                    print("Missing lab test code")
                    missing_lab_test_codes.append(True)
                for lab_value in lab_test_collection["part"][1:]:
                    lab_value_coding = lab_value["resource"]["code"]["coding"][0]
                    if not lab_value_coding["code"]:
                        print("Missing lab value code")
                        missing_lab_value_codes.append(True)
                    if "valueString" in lab_value["resource"] and not lab_value["resource"]["valueString"] or "valueQuanity" in lab_value["resource"] and not lab_value["resource"]["valueQuantity"]["value"]:
                        missing_lab_value_values.append(True)

            valid = True
            if is_missing_file:
                missing_file += 1
                valid = False
            if (any(missing_lab_test_codes) or any(missing_lab_value_codes)):
                missing_codes += 1
                valid = False
            if any(missing_lab_value_values):
                missing_values += 1
                valid = False

            if valid:
                valid_reports += 1
                valid_payloads.append(payload)

        print(f"Missing file: {missing_file}")
        print(f"Missing codes: {missing_codes}")
        print(f"Missing values: {missing_values}")
        print(f"Fully valid: {valid_reports}")
        return valid_payloads


if __name__ == "__main__":
    lab_report_loader = LabReportLoader("ways2well")
    # lab_report_loader.make_patient_api_json()
    # lab_report_loader.retrieve_files()
    # lab_report_loader.retrieve_expanded_lab_values()
    # lab_report_loader.look_up_lab_test_loinc_codes()
    payloads = lab_report_loader.create_lab_report_payloads()
    valid_payloads = lab_report_loader.validate_payloads(payloads)

    # lab_report_loader.load(valid_payloads)
