import csv, requests, os
from decouple import Config, RepositoryIni
from data_migrations.utils import fetch_from_json, write_to_json

class AvonHelper:
    """
        Helper mixin for accessing the Avon API

        settings need to be correctly set up in the config.ini file
    """

    def __init__(self, environment):
        self.environment = environment
        self.get_config_settings()
        self.base_url = f"https://{self.avon_base_subdomain}.avonhealth.com/"
        self.avon_header = self.get_avon_headers()

    def fetch_records(self, data_type, json_file, param_string=''):
        """ Performs an Avon API Call to fetch data with a certain
        URL and search parameters

        In the docs there is no mention of pagination, so their List API
        is an all or nothing response.
        """
        print(f'Fetching records for {data_type}')

        if json_file and os.path.isfile(json_file):
            return fetch_from_json(json_file)

        url = f'{self.base_url}{data_type}?{param_string}'
        response = requests.get(url, headers=self.avon_header)
        try:
            data = response.json()['data']
            if json_file:
                write_to_json(json_file, data)
            return data
        except:
            raise Exception(f"{response.status_code}: {response.text}")


    def fetch_resource(self, uri):
        url = f'{self.base_url}{uri}'
        response = requests.get(url, headers=self.avon_header)
        return response.json()


    def get_config_settings(self):
        """ Load the config.ini file that contains avon auth variables """
        ini = RepositoryIni('../config.ini')
        ini.SECTION = self.environment
        config = Config(ini)

        self.avon_client_id = config("avon_client_id", cast=str)
        self.avon_client_secret = config("avon_client_secret", cast=str)
        self.avon_base_subdomain = config("avon_base_subdomain", cast=str)
        self.avon_user_id = config("avon_user_id", cast=str)

    def get_avon_headers(self):
        """ Fetch the Avon API Headers to use for API calls """

        token_response = requests.post(f'{self.base_url}v2/auth/token', data={
            'client_id': self.avon_client_id,
            'client_secret': self.avon_client_secret
        })
        token_response.raise_for_status()

        jwt_response = requests.post(f'{self.base_url}v2/auth/get-jwt', data={
            "id": self.avon_user_id
        })
        jwt_response.raise_for_status()

        return {
            'Authorization': f'Bearer {token_response.json()["access_token"]}',
            'x-jwt': jwt_response.json()['jwt']
        }

class CalComHelper:
    """
        Helper mixin for accessing the cal.com API

        settings need to be correctly set up in the config.ini file
    """

    def __init__(self, environment):
        self.environment = environment
        self.get_config_settings()
        self.base_url = "https://api.cal.com/"
        self.headers = {
            "cal-api-version": "2024-08-13",
            "Authorization": f"Bearer {self.cal_api_key}"
        }

    def get_config_settings(self):
        """ Load the config.ini file that contains avon auth variables """
        ini = RepositoryIni('../config.ini')
        ini.SECTION = self.environment
        config = Config(ini)

        self.cal_api_key = config("cal_api_key", cast=str)

    def fetch_records(self, data_type, json_file, param_string=''):
        """ Performs an Cal.com API Call to fetch data with a certain
        URL and search parameters
        """
        print(f'Fetching records for {data_type}')

        if json_file and os.path.isfile(json_file):
            return fetch_from_json(json_file)

        url = f'{self.base_url}{data_type}?{param_string}'
        response = requests.get(url, headers=self.headers)
        try:
            data = response.json()['data']
            if json_file:
                write_to_json(json_file, data)
            return data
        except:
            raise Exception(f"{response.status_code}: {response.text}")