import configparser
import json
import requests
import time


class OntologiesDataFetcher:
    def __init__(self) -> None:
        config = configparser.ConfigParser()
        config.read("../config.ini")
        self.ontologies_url = config["ontologies-staging"]["url"]
        self.ontologies_pre_shared_key = config["ontologies-staging"]["pre_shared_key"]

    def fetch_from_api(self, page):
        return requests.get(
            f"{self.ontologies_url}icd/condition/",
            params={"limit": "100", "page": page},
            headers={
                "Authorization": self.ontologies_pre_shared_key,
                "X-Trace": "NO-TRACE"
            }
        )

    def add_results_to_map(self, icd_results, code_display_map) -> None:
        for result in icd_results:
            code_display_map[result['icd10_code']] = result['icd10_text']

    def generate_map(self):
        code_display_map = {}
        page = 1
        initial_request = self.fetch_from_api(page=page)
        if initial_request.status_code != 200:
            raise Exception(f"Unsuccessful request - status code {initial_request.status_code}")
        print(f"Fetched Page {page}")

        response_body = initial_request.json()
        self.add_results_to_map(response_body['results'], code_display_map)

        more_data_available = response_body.get('next')
        while more_data_available:
            page += 1
            response = self.fetch_from_api(page=page)
            if response.status_code != 200:
                raise Exception(f"Unsuccessful request - status code {initial_request.status_code}")

            print(f"Fetched Page {page}")

            response_body = response.json()
            self.add_results_to_map(response_body['results'], code_display_map)
            more_data_available = response_body.get('next')

            # Pause to avoid hammering the API
            time.sleep(2)

        return code_display_map

    def write_to_file(self, data):
        with open('./mappings/icd10_map.json', 'w') as f:
            json.dump(data, f, indent=4)

    def run(self):
        data = ontologies_data_fetcher.generate_map()
        self.write_to_file(data)

    def look_up_single_code(self, code):
        response = requests.get(
            f"{self.ontologies_url}icd/condition/",
            params={"icd10_code": code.strip().replace(".", "")},
            headers={
                "Authorization": self.ontologies_pre_shared_key,
                "X-Trace": "NO-TRACE"
            }
        )
        return response.json()

    def search_snomed(self, snomed_code):
        response = requests.get(
            f"{self.ontologies_url}snomed/complete-concept/",
            params={"concept_id": snomed_code},
            headers={
                "Authorization": self.ontologies_pre_shared_key,
                "X-Trace": "NO-TRACE"
            }
        )
        return response.json()


if __name__ == "__main__":
    ontologies_data_fetcher = OntologiesDataFetcher()
    ontologies_data_fetcher.run()
