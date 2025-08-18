import json
import requests


class CommandMixin:
    def get_command_base_url(self) -> None:
        uri = "/core/api/v1/commands/"
        if self.environment == "localhost":
            return f"http://localhost:8000{uri}"
        return f"https://{self.environment}.canvasmedical.com{uri}"

    def create_command(self, payload) -> str:
        """
        Create a command via Canvas Commands API
        """
        command_base_url = self.get_command_base_url()
        response = requests.request("POST", command_base_url, headers=self.fumage_helper.headers, data=json.dumps(payload))

        if response.status_code != 201:
            raise Exception(f"Failed to perform {response.url}. \n {response.text}")

        response_json = response.json()

        return response_json['uuid']

    def commit_command(self, uuid):
        """
        Commit a command via Canvas Command API
        """
        command_base_url = self.get_command_base_url()
        response = requests.request("POST", f"{command_base_url}{uuid}/commit/", headers=self.fumage_helper.headers)

        if response.status_code != 200:
            raise Exception(f"Failed to perform {response.url}. \n {response.text}")

        return