import csv, requests
from decouple import Config, RepositoryIni

class DrChronoHelper:
    """
        A mixin to help authenticate and make API calls to DrChrono

        Credentials need to be set up in the config.ini to use

    """

    def __init__(self, environment):
        self.environment = environment
        self.drchrono_header = get_drchrono_headers()

    def fetch_drchrono_records(self, data_type, param_string=''):
        """ Given a data type and list of parameters, perform a DrChrono GET request
            returns a list of the records from DrChrono
        """
        records = []
        
        url = f'https://drchrono.com/api/{data_type}?{param_string}'
        while url:
            response = requests.get(url, headers=self.drchrono_header)
            try:
                data = response.json()
                records = records + data['results']
            except:
                print(response.status_code, response.text)
                if response.status_code == 429: 
                    # drchrono throttled the request
                    seconds = float(data['detail'].replace('Request was throttled. Expected available in ', '').replace(' seconds.', ''))
                    time.sleep(seconds+10)
                    return self.fetch_drchrono_records(data_type, parameters)

                if response.status_code == 401:
                    self.drchrono_header = get_drchrono_headers(self.environment)
                
                if response.status_code in (500, 401):
                    time.sleep(60*15) # wait 15 minutes to give DrChrono time 
                    return self.fetch_drchrono_records(data_type, parameters)
                else:
                    raise Exception(response.text)
        
            url = data['next'] # A JSON null on the last page

        return records


    def fetch_drchrono_records_from_file(self, data_type, filename, param_string='', delimiter='|', key='patient'):
        """ Given a data type and list of parameters, perform a DrChrono GET request
            If the CSV file already exists, return and avoid more API calls, if not then make sure 
            to output to CSV
            returns a dict of the records from DrChrono organized with the unique identifier as the key
        """

        print(f'Fetching records for {data_type}')
        
        if os.path.isfile(filename):
            return fetch_from_csv(filename, key, delimiter)
        
        with open(filename, 'w') as f:
            fieldnames = None
            url = f'https://drchrono.com/api/{data_type}?{param_string}'
            while url:
                response = requests.get(url, headers=self.drchrono_header)
                try:
                    data = response.json()
            
                    for r in data['results']:
                        if not fieldnames:
                            fieldnames = list(r.keys())
                            for key in (verbose_keys or []):
                                fieldnames.append(key)
                            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=delimiter)
                            writer.writeheader()
                        writer.writerow(r)
                except:
                    print(response.status_code, response.text)
                    if response.status_code == 429: 
                        # drchrono throttled the request
                        seconds = float(data['detail'].replace('Request was throttled. Expected available in ', '').replace(' seconds.', ''))
                        time.sleep(seconds+10)
                        return self.fetch_drchrono_records(data_type, parameters)

                    if response.status_code == 401:
                        self.drchrono_header = get_drchrono_headers(self.environment)
                    
                    if response.status_code in (500, 401):
                        time.sleep(60*15) # wait 15 minutes to give DrChrono time 
                        return self.fetch_drchrono_records(data_type, parameters)
                    else:
                        raise Exception(response.text)
            
                url = data['next'] # A JSON null on the last page
                print(url)

        return self.fetch_from_csv(filename, key, delimiter)

    def fetch_single_drchrono_record(self, data_type, record_id):
        """
        Grab single dr chrono record
        """     
        url = f'https://drchrono.com/api/{data_type}/{record_id}?verbose=True'
        if response.status_code == 200:
            return response.json()

        print(response.status_code, response.text)
        if response.status_code == 429: 
            # drchrono throttled the request
            seconds = float(response.json()['detail'].replace('Request was throttled. Expected available in ', '').replace(' seconds.', ''))
            time.sleep(seconds+10)
            return self.fetch_single_drchrono_record(data_type, record_id)

        if response.status_code == 401:
            self.drchrono_header = get_drchrono_headers(self.environment)
        
        if response.status_code in (500, 401):
            time.sleep(60*15) # wait 15 minutes to give DrChrono time 
            return self.fetch_single_drchrono_record(data_type, record_id)
        else:
            raise Exception(response.text)

    def get_drchrono_headers(self):
        """ Create the DrChrono Authentication Headers needed for all API calls"""
        ini = RepositoryIni('config.ini')
        ini.SECTION = self.environment
        config = Config(ini)

        response = requests.post('https://drchrono.com/o/token/', data={
            'refresh_token': config("drchrono_refresh_token", cast=str),
            'grant_type': 'refresh_token',
            'client_id': config("drchrono_client_id", cast=str),
            'client_secret': config("drchrono_client_secret", cast=str),
        })
        response.raise_for_status()
        data = response.json()

        return {'Authorization': f'Bearer {data["access_token"]}'}
