import csv, arrow, os
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.visual_exam_findings import VisualExamFindingsMixin

class VisualExamFindingsLoader(VisualExamFindingsMixin):
    """
    Load Visual Exam Findings from Vendor EMR to Canvas.
    
    Visual exam findings include visual acuity, eye pressure, pupil response,
    fundoscopy findings, visual fields, and other ophthalmologic assessments.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'visual_exam_findings'

        self.patient_map_file = 'PHI/patient_ids_map.json'
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f'PHI/images_{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'
        self.ignore_file = f'results/ignored_{self.data_type}.csv'

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.notes_map_file = f"mappings/notes_map.json"
        self.note_map = fetch_from_json(self.notes_map_file)

        self.images_dir = "PHI/images/"

        # any defaults needed for mapping/creation
        self.default_location = "29e0cff2-fbd8-4add-8a9a-7aa2d9e43594"
        self.default_note_type_name = "Historical Data Migration"
        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|', convert_image=False):
        """Fetch and transform visual exam findings data"""

        headers = {
            "ID",
            "Patient Identifier",
            "Title",
            "Image",
            "Comment"
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(self.customer_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)
                for row in reader:
                    title = row['Title']
                    date = row['Uploaded At']
                    if date:
                        title += f' ({arrow.get(date).format("YYYY-MM-DD hh:mm:ss [UTC]")})'

                    file = row.get("JPEG/PNG Image", "").replace("canvas_export/20250915_211439/patient_symptoms_images/", "")  # path to the image file
                    if convert_image:
                        file = f'{self.images_dir}{file}'

                        if not os.path.exists(file):
                            self.ignore_row(row['ID'], f"File(s) {file} not found in supplied files.")
                            continue

                        file = self.base64_encode_file(file)
                        if not file:
                            # This shouldn't ever happen with the current file set we have.
                            print(row["Unique ID"])
                            self.error_row(row["Unique ID"], "Error converting document")
                            continue

                    writer.writerow({
                        "ID": row["Unique ID"],
                        "Patient Identifier": row.get("Patient ID", ""),
                        "Title": title,
                        "Image": file,
                        "Comment": row.get("Comment", "")
                    })

        print("CSV successfully made")

if __name__ == '__main__':
    loader = VisualExamFindingsLoader(environment='hellowisp')
    delimiter = ','
    
    loader.make_csv(delimiter=delimiter, convert_image=True)
    #valid_rows = loader.validate(delimiter=delimiter)
    #loader.load(valid_rows, note_kwargs={"encounter_start_time": "2025-09-30T09:00:00-04:00"})
