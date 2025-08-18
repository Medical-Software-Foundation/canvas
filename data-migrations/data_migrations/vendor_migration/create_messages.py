import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.message import MessageLoaderMixin
from utils import VendorHelper

class MessageLoader(MessageLoaderMixin):
    """
    Load Messages from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'messages'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'
        self.ignore_file = f'results/ignored_{self.data_type}.csv'

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        # If you are extracting data from your vendors API, you can make a 
        # helper class to perform the extraction
        self.vendor_helper = VendorHelper(environment)

        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")

        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|'):
        """Fetch and transform message data"""

        headers = {
            "ID",
            "Timestamp",
            "Recipient",
            "Sender",
            "Text",
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_messages()

            # If your data is in a JSON file, you can load it from the file
            # data = fetch_from_json(self.json_file)

            # If your data is already in a CSV file then loop through the 
            # file and map the data to the template format
            # data = []
            # with open(self.csv_file, 'r') as file:
            #     reader = csv.DictReader(file, delimiter=delimiter)
            #     for row in reader:
            #         data.append(row)

            # Below is mapping the data to the template format but you will need to 
            # address each column
            for message in data:
                # Example of how to ignore rows that don't meet criteria:
                # if not message.get("text"):
                #     self.ignore_row(message.get("id", "unknown"), "Missing message text")
                #     continue
                # 
                # if not message.get("timestamp"):
                #     self.ignore_row(message.get("id", "unknown"), "Missing timestamp - skipping")
                #     continue

                # The sender and recipient must be mapped to a patient or staff member
                # in Canvas.
                recipient = message.get("recipient", "")
                sender = message.get("sender", "")
                if recipient not in self.patient_map and recipient not in self.doctor_map:
                    self.ignore_row(message.get("id", "unknown"), f"Recipient {recipient} not found in patient or doctor map")
                    continue
                if sender not in self.patient_map and sender not in self.doctor_map:
                    self.ignore_row(message.get("id", "unknown"), f"Sender {sender} not found in patient or doctor map")
                    continue

                writer.writerow({
                    "ID": message.get("id", ""),
                    "Timestamp": message.get("timestamp", ""),
                    "Recipient": recipient,
                    "Sender": sender,
                    "Text": message.get("text", "")
                })

        print("CSV successfully made")

if __name__ == '__main__':
    loader = MessageLoader(environment='your-vendor-env')
    delimiter = ','
    
    # loader.make_csv(delimiter=delimiter)
    # valid_rows = loader.validate(delimiter=delimiter)
    # loader.load(valid_rows)
