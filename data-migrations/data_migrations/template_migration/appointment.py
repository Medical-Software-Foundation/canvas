import re, pytz, arrow, csv, json
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from data_migrations.template_migration.utils import validate_enum, validate_header, validate_required, validate_datetime, MappingMixin, FileWriterMixin
from data_migrations.template_migration.note import NoteMixin


class AppointmentLoaderMixin(MappingMixin, NoteMixin, FileWriterMixin):
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow.
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect:

        Required Formats/Values (Case Insensitive):
            Patient Identifier: Canvas key, unique identifier defined on the demographics page
            Appointment Type: Active, Resolved
            Location:  Location ID configured in Canvas.
            Start / End Date/time: YYYY-MM-DDTHH:mm:ssZZ
            Duration: Time in minutes
            Recorded Provider: Staff Canvas key.
    """

    def validate_end_time(self, row):
        """ Confirm there is an end date set for the appointment,
        It is confirmed that Start Datetime is already there.
        Need to ensure duration or End Date Time is there
        """

        if end_date := row['End Datetime']:
            return validate_datetime(end_date, 'End Datetime')

        if duration := row['Duration']:
            try:
                return True, arrow.get(row['Start Datetime']).shift(minutes=int(duration)).isoformat()
            except:
                pass

        return False, "Unable to calculate appointment end date/time"

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
                    "Appointment Type",
                    "Appointment Type System",
                    "Reason for Visit Code",
                    "Reason for Visit Text",
                    "Location",
                    "Meeting Link",
                    "Start Datetime",
                    "End Datetime",
                    "Duration",
                    "Provider",
                    "Status"
                }
            )

            validations = {
                "Patient Identifier": [validate_required],
                "Location": [validate_required],
                "Provider": [validate_required],
                "Start Datetime": [validate_datetime],
                "End Datetime": [validate_datetime],
                "Status": [(validate_enum, {'possible_options': ['booked', 'fulfilled']})],
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

                valid, field_or_error_msg = self.validate_end_time(row)
                if not valid:
                    errors[key].append(field_or_error_msg)
                    error = True
                else:
                    row['End Datetime'] = field_or_error_msg

                if not error:
                    validated_rows.append(row)

        if errors:
            print(f"Some rows contained errors, please see {self.validation_error_file}.")
            write_to_json(self.validation_error_file, errors)
        else:
            print('All rows have passed validation!')

        return validated_rows

    def map_rfv(self, row):
        """ Create the FHIR reasonCode object. Since Canvas supports both
        structured RFV and free text
        """
        rfv_code = row['Reason for Visit Code']
        free_text = row['Reason for Visit Text']
        reason_code = {}

        if hasattr(self, "rfv_map"):
            rfv = self.rfv_map.get(str(rfv_code))
        else:
            rfv = f'INTERNAL|{rfv_code}'

        if rfv_code:
            system, code = rfv.split('|')
            reason_code['coding'] = [{
                "system": system,
                "code": code
            }]

        if free_text:
            reason_code['text'] = free_text

        if not rfv_code and not free_text:
            reason_code['text'] = "No Reason Given"

        return reason_code


    def load(self, validated_rows, system_unique_identifier, end_date_time_frame=None):
        """
            Takes the validated rows from self.validate() and
            loops through to send them off the FHIR Create

            Outputs to CSV to keep track of records
            If any  error, the error message will output to the errored file
        """

        end_date_time_frame = arrow.get(end_date_time_frame) if end_date_time_frame else None

        total_count = len(validated_rows)
        print(f'      Found {len(validated_rows)} records')
        ids = set()
        for i, row in enumerate(validated_rows):
            print(f'Ingesting ({i+1}/{total_count})')

            if row['ID'] in ids or row['ID'] in self.done_records or row['ID'] in self.ignore_records:
                print(' Already looked at record')
                continue

            start_time = arrow.get(row["Start Datetime"])
            if end_date_time_frame and start_time > end_date_time_frame:
                self.ignore_row(row['ID'], f"Ignoring due to start time of {start_time.isoformat()}")
                continue

            patient = row['Patient Identifier']
            patient_key = ""

            location = row['Location']
            if hasattr(self, "location_map"):
                location = self.location_map.get(row['Location'])

            if location is None:
                location = self.default_location

            try:
                # try mapping required Canvas identifiers
                patient_key = self.map_patient(patient)
                practitioner_key = self.map_provider(row['Provider'])
            except BaseException as e:
                self.ignore_row(row['ID'], e)
                continue

            payload = {
                "resourceType": "Appointment",
                "identifier": [
                    {
                        "system": system_unique_identifier,
                        "value": row['ID'],
                    }
                ],
                "status": row.get('Status') or "fulfilled",
                "appointmentType": {
                    "coding": [{
                            "system": row.get('Appointment Type System') or "INTERNAL",
                            "code": row['Appointment Type'] or f"{system_unique_identifier}_historical_note",
                    }]
                },
                "reasonCode":[self.map_rfv(row)],
                "supportingInformation":[
                    {
                        "reference": f"Location/{location}"
                    }
                ],
                "start": start_time.isoformat(),
                "end": arrow.get(row["End Datetime"]).isoformat(),
                "participant":[
                    {
                        "actor": {"reference": f"Patient/{patient_key}"},
                        "status": "accepted"
                    },
                    {
                        "actor": {"reference": f"Practitioner/{practitioner_key}"},
                        "status": "accepted"
                    }
                ]
            }


            # Add meeting link if provided
            if meeting_link := row['Meeting Link']:
                payload['supportingInformation'].append({
                    "reference": "#appointment-meeting-endpoint",
                    "type": "Endpoint"
                })
                payload['contained'] = [
                    {
                        "resourceType": "Endpoint",
                        "id": "appointment-meeting-endpoint",
                        "address": meeting_link,
                        "status": "fulfilled",
                        "connectionType": {
                            "code": "https"
                        },
                        "payloadType":
                        [
                            {
                                "coding":
                                [
                                    {
                                        "code": "video-call"
                                    }
                                ]
                            }
                        ]
                    }
                ]

            # print(json.dumps(payload, indent=2))
            # return

            try:
                canvas_id = self.fumage_helper.perform_create(payload)
                self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}")
                ids.add(row['ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)
                continue


            # need to check in and lock the appointment if appointment is historical
            if payload['status'] == 'fulfilled':
                try:
                    self.fumage_helper.check_in_and_lock_appointment(canvas_id)
                except BaseException as e:
                    self.error_row(f"{row['ID']}|{patient}|{patient_key}", e, file=self.errored_note_state_event_file)

            # return
