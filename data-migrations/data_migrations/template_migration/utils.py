import arrow, base64, pytz, os, re, uuid
from PIL import Image, ImageSequence
import pdfkit

def validate_date(value, field_name):
    if not value:
        return True, ""
    try:
        return True, arrow.get(value).format("YYYY-MM-DD")
    except:
        for format in ["YYYY-M-DD", "YYYY-M-D", "YYYY/MM/DD", "YYYY/M/DD", "YYYY/M/D", "MM/DD/YYYY", "M/D/YYYY", "M/DD/YYYY", "MM-DD-YYYY", "M-D-YYYY", "M-DD-YYYY", "MM.DD.YYYY", "M.D.YYYY", "M.DD.YYYY", "MMMM DD, YYYY", "MMM DD, YYYY", "MMMM D, YYYY", "MMM D, YYYY", "MMMM Do, YYYY", "MMM Do, YYYY", "M/D/YY", "MM/DD/YY"]:
            try:
                return True, arrow.get(value, format).format("YYYY-MM-DD")
            except:
                pass

    return False, f"Invalid {field_name} format: {value}"

def validate_datetime(value, field_name):
    if not value:
        return True, ""
    try:
        return True, arrow.get(value).isoformat()
    except:
        return False, f"Invalid {field_name} format: {value}"

def validate_required(value, field_name):
    """ validates a required field is not empty """
    if not value:
        return False, f"Data is missing {field_name}"
    return True, value

def validate_header(headers, accepted_headers):
    # confirms the csv's headers are the expected list
    if missing_headers := [h for h in accepted_headers if h not in headers]:
        raise ValueError(f"Incorrect headers! These headers were missing {missing_headers} from the supplied csv with headers: {headers}")

def validate_state_code(value, field_name):
    """ accept only the 2 character state codes """
    if not value:
        return True, value

    accepted_states = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "GU", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "PR", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "VI", "WA", "WV", "WI", "WY", "AE", "AP",  "AA", "ZZ"] # ZZ for international
    if value in accepted_states:
        return True, value
    return False, f"Invalid {field_name}: {value}"

def validate_postal_code(value, field_name):
    """ finds the first 5 digits for postal code """
    if not value:
        return True, value

    first_five_digits = [i for i in value if i.isdigit()][:5]
    if len(first_five_digits) == 5:
        return True, "".join(first_five_digits)
    return False, f"Invalid {field_name}: {value}"

def validate_phone_number(value, field_name):
    """ removes any non digits and validates the length is 10 """
    if not value:
        return True, value

    if value.startswith('+1'):
        value = value[2:]

    number = [i for i in value if i.isdigit()]
    if len(number) == 10:
        return True, "".join(number)
    if len(number) == 11 and number[0] == '1':
        return True, "".join(number[1:])
    return False, f"Invalid {field_name}: {value}"

def validate_boolean(value, field_name):
    """ Validates a boolean field

        accept TRUE, FALSE, true, false, T, F, t, f
    """

    if not value:
        return True, False

    mapping = {
        "TRUE": True,
        "T": True,
        "FALSE": False,
        "F": False,
        "Y": True,
        "N": False,
        "YES": True,
        "NO": False
    }
    try:
        return True, mapping[value.upper()]
    except KeyError:
        return False, f"Invalid boolean {field_name} given: {value}"


def validate_email(value, field_name):
    """ Validate an email format """
    if not value:
        return True, value

    match = re.match(r"^(?!\.)[\w!#$%&'*+/=?^`{|}~.-]+(?<!\.)@[a-zA-Z\d.-]+\.[a-zA-Z]{2,}$", value.lower())

    if not match:
      return False, f"Invalid {field_name}: {value}"
    return True, value

def validate_timezone(value, field_name):
    """ Validate a timezone value """
    if not value:
        return True, value

    # accept EST, EDT, ET, America/New_York, CST, CDT, CT, America/Chicago, MST, MDT, MT, America/Denver, PDT, PST, PT
    mapping = {
        "EST": 'America/New_York',
        "EDT": 'America/New_York',
        "ET": 'America/New_York',
        "CST": 'America/Chicago',
        "CDT": 'America/Chicago',
        "CT": 'America/Chicago',
        "MST": 'America/Denver',
        "MDT": 'America/Denver',
        "MT": 'America/Denver',
        "PST": 'America/Los_Angeles',
        "PDT": 'America/Los_Angeles',
        "PT": 'America/Los_Angeles'
    }

    try:
        return True, mapping[value.upper()]
    except KeyError:
        pass

    # if its not part of the expected values, just make sure it is a valid timezone with the pytz library
    if value in pytz.all_timezones:
        return True, value
    return False, f"Invalid {field_name} given: {value}"

def validate_address(row):
    """ Validate address elements """

    # if at least one address field is supplied, we need all
    required_fields = ["Address Line 1", "City", "State", "Postal Code"]
    if any([row[i] for i in ["Address Line 1",
                            "Address Line 2",
                            "City",
                            "State",
                            "Postal Code"]]):
        if missing_fields := [f for f in ["Address Line 1", "City", "State", "Postal Code"] if not row[f]]:
            return f"Address detected for row but missing some required fields ({missing_fields})"

def validate_enum(value, field, **kwargs):
    possible_options = kwargs.get("possible_options")
    if not value:
        return True, value

    value = value.lower()

    return value in possible_options, value

class MappingMixin:

    def map_patient(self, patient):
        # make sure patient is in the mapped patients
        patient_key = self.patient_map.get(patient)
        if not patient_key:
            raise Exception(f'    Ignoring due no patient map with {patient}')

        return patient_key

    def map_provider(self, provider):
        # map the provider if needed
        if not provider:
            return

        if provider == 'canvas-bot':
            return "5eede137ecfe4124b8b773040e33be14"

        if hasattr(self, "doctor_map"):
            practitioner_key = self.doctor_map.get(str(provider))

            if not practitioner_key:
                raise Exception(f'    Ignoring due no doctor map with {provider}')

            return practitioner_key
        return provider

    def map_location(self, location):
        # map the location if needed
        if hasattr(self, "location_map"):
            location_key = self.location_map.get(str(location))

            if not location_key:
                raise Exception(f'    Ignoring due no location map with {location}')

            return location_key
        return location

class FileWriterMixin:

    def ignore_row(self, _id, ignore_reason):
        if not os.path.isfile(self.ignore_file):
            with open(self.ignore_file, 'w') as f:
                f.write('id|ignored_reason\n')

        ignore_reason = str(ignore_reason).replace('\n', '')
        with open(self.ignore_file, 'a') as file:
            print(f' Ignoring row due to "{ignore_reason}')
            file.write(f"{_id}|{ignore_reason}\n")

    def error_row(self, data, error, file=None):
        """If anything fails, output to file to go back and fix"""
        if not os.path.isfile(self.error_file):
            with open(self.error_file, 'w') as f:
                f.write('id|patient_id|patient_key|error_message\n')

        error = str(error).replace('\n', '')
        with open(file or self.error_file, 'a') as file:
            print(f' Errored row outputing error message to file...{error}')
            file.write(f"{data}|{error}\n")

    def done_row(self, data, file=None):
        if not os.path.isfile(self.done_file):
            with open(self.done_file, 'w') as f:
                f.write('id|patient_id|patient_key|canvas_externally_exposable_id\n')

        with open(file or self.done_file, 'a') as done:
            print(' Complete')
            done.write(f"{data}\n")


class DocumentEncoderMixin:
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

        output_path = f'{self.temp_pdf_dir}/{tiff_path.split("/")[-1]}'.replace(".tiff", ".pdf").replace(".tif", ".pdf")
        if len(images) == 1:
            images[0].save(output_path)
        else:
            images[0].save(output_path, save_all=True, append_images=images[1:])
        return output_path

    def convert_and_base64_encode(self, documents, custom_name=None):
        images = [Image.open(img) for img in documents]
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

    def convert_html_to_pdf(self, input_file):
        input_path = str(input_file)  # Make sure it's a string path
        output_path = input_path.replace(".html", ".pdf")

        config = pdfkit.configuration(wkhtmltopdf="/usr/local/bin/wkhtmltopdf")  # adjust as needed
        pdfkit.from_file(input_path, output_path, configuration=config)

        return output_path

    def get_b64_document_string(self, file_list):
        b64_document_string = None
        if len(file_list) == 1:
            file_path = file_list[0]
            input_file = f"{self.documents_files_dir}{file_path}"
            if file_path.endswith(".tiff") or file_path.endswith(".tif"):
                pdf_output = self.tiff_to_pdf(input_file)
                b64_document_string = self.base64_encode_file(pdf_output)
                # clean up the file
                os.remove(pdf_output)
            elif file_path.lower().endswith(".pdf"):
                b64_document_string = self.base64_encode_file(input_file)
            elif file_path.endswith(".png"):
                b64_document_string = self.convert_and_base64_encode([input_file])
            elif file_path.endswith(".jpeg") or file_path.endswith(".jpg"):
                b64_document_string = self.convert_and_base64_encode([input_file])
            elif file_path.endswith('.html'):
                pdf_file = self.convert_html_to_pdf(input_file)
                b64_document_string = self.base64_encode_file(pdf_file)
        elif len(file_list) > 1:
            b64_document_string = self.convert_and_base64_encode([f"{self.documents_files_dir}{p}" for p in file_list])


        return b64_document_string
