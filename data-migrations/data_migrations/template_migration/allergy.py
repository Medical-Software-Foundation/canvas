import re, pytz, arrow, csv, json
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from data_migrations.template_migration.utils import (
    validate_header,
    validate_required,
    validate_date,
    validate_enum,
    MappingMixin,
    FileWriterMixin
)
from data_migrations.template_migration.note import NoteMixin


class AllergyLoaderMixin(MappingMixin, NoteMixin, FileWriterMixin):
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow.
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect:

        Required Formats/Values (Case Insensitive):
            Patient Identifier: Canvas key, unique identifier defined on the demographics page
            Clinical Status: Active, Resolved
            Type: Allergy, Intolerance
            Onset Date: MM/DD/YYYY or YYYY-MM-DD
            Recorded Provider: Staff Canvas key.  If omitted, defaults to Canvas Bot
    """

    def map(self):
        _map = fetch_from_json(self.allergy_mapping_file)
        total = len(_map)
        for i, (key, item) in enumerate(_map.items()):
            name, code = key.split('|')
            print()
            print(f'{key} ({i+1}/{total})')
            if item:
                print('already done skipping')
                continue

            options = []
            name_list = name.split(' ')
            found_coding = None

            if code:
                search_parameters = {
                    'code': f'http://www.nlm.nih.gov/research/umls/rxnorm|{code}'
                }

                response = self.fumage_helper.search("Allergen", search_parameters)

                if response.status_code != 200:
                    raise Exception(f"Failed to perform {response.url}. \n Fumage Correlation ID: {response.headers['fumage-correlation-id']} \n {response.text}")

                response_json = response.json()
                if response_json.get('total') == 1:
                    _map[key] = response_json['entry'][0]['resource']['code']['coding']
                    print('1', _map[key])
                    continue
                elif response_json.get('total') != 0:
                    found = False
                    for entry in response_json['entry']:
                        coding = entry['resource']['code']['coding']
                        if coding[0]['display'].split(' ')[0].lower() == name_list[0].lower():
                            _map[key] = coding
                            print('2', coding)
                            found = True
                            found_coding = True
                            break
                    if not found:
                        for e in response_json.get('entry', []):
                            c = e['resource']['code']['coding']
                            if c not in options:
                                options.append(c)

                    else:
                        continue

            for i in reversed(range(len(name_list))):
                text = " ".join(name_list[:i+1]).strip()
                if text:
                    search_parameters = {
                        '_text': " ".join(name_list[:i+1])
                    }

                    response = self.fumage_helper.search("Allergen", search_parameters)
                    if response.status_code != 200:
                        raise Exception(f"Failed to perform {response.url}. \n Fumage Correlation ID: {response.headers['fumage-correlation-id']} \n {response.text}")

                    response_json = response.json()
                    if response_json.get('total') == 1:
                        coding = response_json['entry'][0]['resource']['code']['coding']
                        if any([c['code'] == code or c['display'].lower() == name.lower() for c in coding]):
                            _map[key] = coding
                            print(coding)
                            found_coding = True
                            break
                    elif response_json.get('total') > 1:
                        for entry in response_json['entry']:
                            coding = entry['resource']['code']['coding']
                            if coding[0]['display'].lower() == name.lower():
                                _map[key] = coding
                                print(coding)
                                found_coding = True
                                break
                    if not found_coding:
                        for e in response_json.get('entry', []):
                            c = e['resource']['code']['coding']
                            if c not in options:
                                options.append(c)

            if not _map[key]:
                print(f'Giving all options, {options}')
                _map[key] = options

        sorted_items = sorted(_map.items(), key=lambda kv: kv[0].lower())
        ordered = dict(sorted_items)
        write_to_json(self.med_mapping_file, ordered)


    def validate(self, delimiter='|'):
        """
            Loop throw the CSV file to validate each row has the correct columns and values
            Append validated rows to a list to use to load.
            Export errors to a file/console

        """
        validated_rows = []
        errors = defaultdict(list)
        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            validate_header(reader.fieldnames,
                accepted_headers = {
                    "ID",
                    "Patient Identifier",
                    "Clinical Status",
                    "Type",
                    "FDB Code",
                    "Name",
                    "Onset Date",
                    "Free Text Note",
                    "Reaction",
                    "Recorded Provider",
                    "Severity",
                    "Original Name",
                }
            )

            validations = {
                "ID": [validate_required],
                "Patient Identifier": [validate_required],
                "Clinical Status": [validate_required, (validate_enum, {"possible_options": ['active', 'inactive']})],
                "Type": [validate_required, (validate_enum, {'possible_options': ['allergy', 'intolerance']})],
                "FDB Code": [validate_required],
                "Name": [validate_required],
                "Onset Date": [validate_date],
                "Severity": [(validate_enum, {'possible_options': ['mild', 'moderate', 'severe']})]
            }

            for row in reader:
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

    def load(self, validated_rows, note_kwargs={}):
        """
            Takes the validated rows from self.validate() and
            loops through to send them off the FHIR Create

            Outputs to CSV to keep track of records
            If any  error, the error message will output to the errored file
        """

        self.patient_map = fetch_from_json(self.patient_map_file)

        total_count = len(validated_rows)
        print(f'      Found {len(validated_rows)} records')
        ids = set()
        for i, row in enumerate(validated_rows):
            print(f'Ingesting ({i+1}/{total_count})')

            if row['ID'] in ids or row['ID'] in self.done_records:
                print(' Already did record')
                continue

            practitioner_key = ""
            try:
                practitioner_key = self.map_provider(row['Recorded Provider'])
            except BaseException:
                practitioner_key = "5eede137ecfe4124b8b773040e33be14" # canvas-bot

            patient = row['Patient Identifier']
            patient_key = ""
            try:
                patient_key = self.map_patient(patient)
                note_id = row.get("Note ID") or self.get_or_create_historical_data_input_note(patient_key, **note_kwargs)
            except BaseException as e:
                self.ignore_row(row['ID'], e)
                continue

            # If an FDB code is delimited with "```", then we need to make 2 records - one for each code;
            fdb_codes = row["FDB Code"].split("```")
            for fdb in fdb_codes:
                payload = {
                    "resourceType": "AllergyIntolerance",
                    "extension": [
                        {
                            "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                            "valueId": note_id,
                        }
                    ],
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                                "code": row['Clinical Status']
                            }
                        ],
                    },
                    "verificationStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                                "code": "confirmed",
                                "display": "Confirmed"
                            }
                        ],
                        "text": "Confirmed"
                    },
                    "type": row['Type'],
                    "code": {
                        "coding": [
                            {
                                "system": "http://www.fdbhealth.com/",
                                "code": fdb,
                                "display": row["Name"] if fdb != '1-143' else "No Allergy Information Available"
                            }
                        ]
                    },
                    "patient": {
                        "reference": f"Patient/{patient_key}"
                    },
                    "note": (
                        ([{"text": row['Original Name']}] if row['Original Name'] else []) +
                        ([{"text": row['Reaction']}] if row['Reaction'] else []) +
                        ([{"text": f"Notes: {row['Free Text Note']}"}] if row['Free Text Note'] else [])
                    )
                }

                if onset := row['Onset Date']:
                    payload['onsetDateTime'] = onset
                if practitioner_key:
                    payload['recorder'] = {
                        "reference": f"Practitioner/{practitioner_key}"
                    }
                if severity := row.get('Severity'):
                    payload["reaction"] = [
                        {
                            "manifestation": [
                                {
                                    "coding": [
                                        {
                                            "system": "http://terminology.hl7.org/CodeSystem/data-absent-reason",
                                            "code": "unknown",
                                            "display": "Unknown"
                                        }
                                    ],
                                    "text": "Unknown"
                                }
                            ],
                            "severity": severity
                        }
                    ]

                # print(json.dumps(payload, indent=2))
                # return

                try:
                    canvas_id = self.fumage_helper.perform_create(payload)
                    self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}|{fdb}")
                    ids.add(row['ID'])
                except BaseException as e:
                    self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)
