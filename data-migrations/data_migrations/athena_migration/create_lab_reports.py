import base64
import os
import uuid

from PIL import Image, ImageSequence
from data_migrations.utils import fetch_from_json


class ValidationError(Exception):
    pass


class LabReportLoader:
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/labresults/labresults.json"
        self.labresults_files_dir = "PHI/labresults"
        self.temp_pdf_dir = "PHI/pdf_temp"


    def base64_encode_file(self, file_path):
        with open(file_path, "rb") as fhandle:
            contents = fhandle.read()
            encoded_contents = base64.b64encode(contents)
            return encoded_contents.decode("utf-8")

    def tiff_to_pdf(self, tiff_path):
        image = Image.open(tiff_path)
        images = []
        for page in ImageSequence.Iterator(image):
            page = page.convert("RGB")
            images.append(page)

        output_path = f"{self.temp_pdf_dir}/{tiff_path.split("/")[-1]}".replace(".tiff", ".pdf")

        if len(images) == 1:
            print("single page output")
            images[0].save(output_path)
        else:
            print("multiple page output")
            images[0].save(output_path, save_all=True, append_images=images[1:])
        return output_path

    def convert_and_base64_encode(self, documents, custom_name=None):
        images = [Image.open(f"{self.labresults_files_dir}{img}") for img in documents]
        if custom_name:
            output_path = f"{self.temp_pdf_dir}/{custom_name}.pdf"
        else:
            temp_uuid = str(uuid.uuid4())
            output_path = f"{self.temp_pdf_dir}/{temp_uuid}.pdf"
        images[0].save(output_path, "PDF", resolution=100.0, save_all=True, append_images=images[1:])
        base64_encoded_string = self.base64_encode_file(output_path)
        # clean up the temp file
        os.remove(output_path)
        return base64_encoded_string

    def create_fhir_payload(self, labresult, patient_enterprise_id):
        api_payload = {
            "resourceType": "Parameters",
            "parameter": []
        }

        observation_date_val = labresult.get("observationdatetime")
        if not observation_date_val:
            observation_date_val = labresult.get("observationdate")
            if not observation_date_val:
                observation_date_val = labresult.get("encounterdate")

            # TODO - convert to midnight America/New York time if it is a date value;

        if not observation_date_val:
            raise ValidationError("Missing observation date")

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
                b64_document_string = self.convert_and_base64_encode([file_path], custom_name=labresult["labresultid"])
            elif file_path.endswith(".jpeg") or file_path.endswith(".jpg"):
                b64_document_string = self.convert_and_base64_encode([file_path], custom_name=labresult["labresultid"])
            else:
                # This shouldn't ever be raised with the current file set we have.
                raise ValidationError("Unsupported file format")
        elif labresult.get("pages"):
            documents = [(page["pageordering"], page["reference"]) for page in labresult["pages"]]
            # sort to get the correct page ordering
            documents.sort()
            documents = [doc[1] for doc in documents]
            # pages either all have file references or none have file references; there aren't any that are partial;
            # If they are all missing, raise a validation error since we can't produce a file
            if not any(documents):
                raise ValidationError("No references for file locations")
            # TODO - check to see if any files are tiffs and not png; These may need to be processed differently;
            b64_document_string = self.convert_and_base64_encode(documents, custom_name=labresult["labresultid"])
        else:
            raise ValidationError("No file present in data")

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
                    "reference": "Patient/xxx", # map to patient from patientdetails
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
        if not lab_test_result_loinc:
            raise ValidationError("Missing LOINC code for lab test results")

        lab_test_result_display = labresult.get("description")
        if not lab_test_result_display:
            raise ValidationError("Missing display for lab test results")

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

            observation_status = observation.get("resultstatus", "final")
            if observation_status not in ["amended", "cancelled", "corrected", "entered-in-error", "final", "preliminary", "registered", "unknown"]:
                raise ValidationError(f"Unsupported observation status - {observation_status}")

            observation_loinc = observation.get("loinc")
            if not observation_loinc:
                raise ValidationError("Missing observation loinc code")

            observation_loinc_display = observation.get("analytename")
            if not observation_loinc_display:
                raise ValidationError("Missing observation loinc display")

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
                    "valueQuantity": {
                        "value": observation.get("value", ""),
                        "unit": observation.get("units", ""),
                        "system": "http://unitsofmeasure.org"
                    }
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
            # should we mark as abnormal for anything that is not 'normal'?

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
        if lab_values:
            breakpoint()
        return api_payload


    def load(self):
        data = fetch_from_json(self.json_file)

        for obj in data:
            patient_enterprise_id = obj["patientdetails"]["enterpriseid"]
            for result in obj["labresults"]:
                try:
                    payload = self.create_fhir_payload(result, patient_enterprise_id)
                except ValidationError as e:
                    print(str(e))


if __name__ == "__main__":
    loader = LabReportLoader(environment="localhost")
    loader.load()
