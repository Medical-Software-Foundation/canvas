import base64
import csv
import json
import logging
import threading
import traceback
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO, StringIO
from threading import Lock
from typing import Any

import arrow
from canvas_common.current_thread import thread_storage
from canvas_core.commands.models import Command as CommandModel
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from api.models.external_mapping import ExternalMapping
from api.models.note import Note
from api.models.note_type import NoteType
from api.models.organization import PracticeLocation
from api.models.patient import Patient, PatientExternalIdentifier, PatientAddress, PatientContactPoint
from api.serializers.note import NoteSerializer
from app.models.user import CanvasUser
from canvas_generated.messages.effects_pb2 import Effect
from data_integration.messages.consumers.medicationstatement import (
    MedicationStatementMessageConsumer,
)
from data_integration.messages.consumers.patient import PatientMessageConsumer
from data_integration.messages.consumers.visual_exam_finding import (
    VisualExamFindingMessageConsumer,
)
from data_integration.utils import s3_get_object
from plugin_io.interpreters.commands.plan import CommitPlanCommand, OriginatePlanCommand

COMMAND_MAP = {"plan_command": ("plan", OriginatePlanCommand, CommitPlanCommand)}


class Command(BaseCommand):
    """
    Data migration command with shared threaded processing infrastructure.

    This command supports processing different types of data (plan_command, patients)
    using a shared threading framework that eliminates code duplication.

    Key components:
    - process_data_threaded(): Generic threaded processing method
    - process_chunk(): Handles individual chunk processing with provided processor function
    - Utility methods for logging and error handling
    - Specific chunk processors for each data type (handle_*_chunk methods)

    Usage:
    - Each data type maps directly to its chunk processor function
    - No intermediate handler methods needed
    - Easy to add new data types by adding new chunk processor functions
    """

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "data_type",
            choices=[
                "plan_command",
                "patients",
                "medication_statement_command",
                "visual_exam_finding_command",
            ],
        )
        parser.add_argument("--s3-file", type=str, required=True)
        parser.add_argument(
            "--chunk-size", type=int, default=1000, help="Number of records to process per chunk"
        )
        parser.add_argument(
            "--max-workers", type=int, default=5, help="Maximum number of worker threads"
        )
        parser.add_argument(
            "--quiet", action="store_true", help="Only show ignore and error messages"
        )
        parser.add_argument(
            "--update", action="store_true", help="Update existing records instead of skipping them"
        )

    def log(self, message, msg_type="info"):
        """
        Log a message with optional type filtering.

        Args:
            message: The message to log
            msg_type: Type of message ('info', 'error', 'ignore', 'success')
                     Only 'error' and 'ignore' messages are shown in quiet mode
        """
        if hasattr(self, "quiet") and self.quiet and msg_type not in ["error", "ignore"]:
            return
        self.stdout.write(f"\tData Migration: {message}")

    def create_chunks(self, data, chunk_size):
        """Split data into chunks for parallel processing"""
        if isinstance(data, dict):
            # For plan_command data (dict of patient_id -> rows)
            items = list(data.items())
            for i in range(0, len(items), chunk_size):
                yield dict(items[i : i + chunk_size])
        else:
            # For patients data (list of rows)
            for i in range(0, len(data), chunk_size):
                yield data[i : i + chunk_size]

    def process_chunk(self, chunk_data, chunk_index, total_chunks, chunk_processor_func):
        """Process a single chunk of data using the provided processor function"""
        thread_id = threading.current_thread().ident
        chunk_display = f"[Chunk-{chunk_index + 1}/{total_chunks}]"
        self.log(f"Thread {thread_id}: Processing {chunk_display}")

        try:
            chunk_processor_func(chunk_data, chunk_index, total_chunks, chunk_display)
            self.log(f"Thread {thread_id}: Completed {chunk_display}")
            return True, chunk_index, None
        except Exception as e:
            error_msg = f"Thread {thread_id}: Error in {chunk_display}: {str(e)}"
            self.log(error_msg)
            return False, chunk_index, str(e)

    def process_data_threaded(self, data, chunk_processor_func):
        """Generic threaded processing method that eliminates code duplication"""
        total_count = len(data)
        self.log(f"\tFound {total_count} records - processing with threading")

        chunks = list(self.create_chunks(data, self.chunk_size))
        total_chunks = len(chunks)
        self.log(f"\tSplit into {total_chunks} chunks of size {self.chunk_size}")

        successful_chunks = 0
        failed_chunks = 0
        failed_errors = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all chunks for processing
            future_to_chunk = {
                executor.submit(self.process_chunk, chunk, i, total_chunks, chunk_processor_func): i
                for i, chunk in enumerate(chunks)
            }

            # Process completed chunks
            for future in as_completed(future_to_chunk):
                chunk_index = future_to_chunk[future]
                try:
                    success, _, error = future.result()
                    if success:
                        successful_chunks += 1
                    else:
                        failed_chunks += 1
                        failed_errors.append(error)
                        self.log(f"\tChunk {chunk_index + 1} failed: {error}", "error")
                except Exception as e:
                    failed_chunks += 1
                    failed_errors.append(str(e))
                    self.log(f"\tChunk {chunk_index + 1} failed with exception: {str(e)}", "error")

        self.log(
            f"\tThreading complete: {successful_chunks} successful, {failed_chunks} failed chunks"
        )
        if failed_errors:
            self.log(f"\tFailed errors: {failed_errors}", "error")

        return successful_chunks, failed_chunks

    def log_chunk_progress(self, chunk_display, current, total, operation="Processing"):
        """Log progress for chunk processing"""
        self.log(f"\t{chunk_display} - {operation} ({current}/{total})")

    def log_chunk_success(self, chunk_display, item_id, success_message, action='created'):
        """Log successful processing of an item and increment counter"""
        # Increment done counter (thread-safe)
        if action == 'created':
            with self.done_count_lock:
                self.done_count += 1
        else:
            with self.update_count_lock:
                self.update_count += 1

        self.log(f"\t\tSuccessful: {item_id} {success_message}")

    def log_chunk_error(self, chunk_display, item_id, error_message):
        """Log error during processing of an item"""
        self.log(f"\t\tError processing {item_id}: {error_message}", "error")

    def suppress_staff_identification_warning(self):
        """Suppress the 'Unknown identification strategy for staff: None' warning during migration"""
        integration_logger = logging.getLogger("app.loggers")
        integration_logger.setLevel(logging.ERROR)  # Only show ERROR and above, suppress WARNING
        return integration_logger

    def get_s3_file(self, filename, convert_csv=False, return_empty=False):
        file_path = f"{settings.CUSTOMER_IDENTIFIER}/data_migration/{filename}"
        file_type = filename.split(".")[-1]
        try:
            response = s3_get_object(file_path)
            if file_type in ["jpg", "jpeg", "png", "heic", "webp"]:
                content = response["Body"].read()
                return base64.b64encode(content).decode("utf-8")

            content = response["Body"].read().decode("utf-8")

            if file_type == "json":
                return json.loads(content)
            
            if convert_csv:
                csvfile = StringIO(content)
                return list(csv.DictReader(csvfile))

            return content
        except Exception as e:
            if return_empty:
                return {}
            raise Exception(f"Unable to fetch {file_path} from s3: {e}")

    def save_s3_file(self, file, filename):
        file_path = f"data_migration/{filename}"

        # ✅ Explicitly delete existing file (if it exists)
        if default_storage.exists(file_path):
            default_storage.delete(file_path)

        # ✅ Now save cleanly
        default_storage.save(file_path, file)

    def append_s3_file(self, content, filename):
        """Append content to an S3 file (thread-safe)"""
        file_path = f"data_migration/{filename}"

        try:
            # Get existing content
            if default_storage.exists(file_path):
                existing_content = self.get_s3_file(filename, convert_csv=False, return_empty=True)
                if existing_content and len(existing_content.strip()) > 0:
                    updated_content = existing_content.rstrip("\n") + "\n" + content
                else:
                    updated_content = content
            else:
                updated_content = content
        except Exception:
            updated_content = content

        # Save the updated content
        self.save_s3_file(BytesIO(updated_content.encode("utf-8")), filename)

    def ignore_row(self, _id, ignore_reason):
        """Thread-safe method to log ignored rows"""
        with self.ignore_lock:
            filename = f"ignore_{self.data_type}.csv"
            reason_clean = str(ignore_reason).replace("\n", "")
            new_line = f"{_id}|{reason_clean}"

            # Check if file exists to determine if we need headers
            file_path = f"data_migration/{filename}"
            if not default_storage.exists(file_path):
                new_line = "id|ignored_reason\n" + new_line

            # Append to S3 file
            self.append_s3_file(new_line, filename)

            # Track ignore message with ID
            with self.ignore_count_lock:
                self.ignore_count += 1
                if reason_clean in self.ignore_messages:
                    self.ignore_messages[reason_clean].append(_id)
                else:
                    self.ignore_messages[reason_clean] = [_id]

        self.log(f"\t\t📤 Ignored row {_id} due to: {reason_clean}", "ignore")

    def error_row(self, data, error):
        """Thread-safe method to log error rows"""
        with self.error_lock:
            filename = f"error_{self.data_type}.csv"
            reason_clean = str(error).replace("\n", "")
            new_line = f"{data}|{error}"

            # Check if file exists to determine if we need headers
            file_path = f"data_migration/{filename}"
            if not default_storage.exists(file_path):
                new_line = "id|patient_id|patient_key|error_message\n" + new_line

            # Append to S3 file
            self.append_s3_file(new_line, filename)

            # Track error message with ID
            with self.error_count_lock:
                self.error_count += 1
                if reason_clean in self.error_messages:
                    self.error_messages[reason_clean].append(data)
                else:
                    self.error_messages[reason_clean] = [data]

        self.log(f"\t\t📤 Errored row {data} due to: {reason_clean}", "error")

    def done_row(self, data):
        """Thread-safe method to log completed rows"""
        with self.done_lock:
            filename = f"done_{self.s3_file.replace('.json', '.csv')}"
            new_line = f"{data}"

            # Check if file exists to determine if we need headers
            file_path = f"data_migration/{filename}"
            if not default_storage.exists(file_path):
                new_line = "id|patient_id|patient_key|canvas_externally_exposable_id\n" + new_line

            # Append to S3 file
            self.append_s3_file(new_line, filename)

        # self.log(f"\t\t📤 Finished row {data}")

    def already_done_row(self, record_id, source):
        """Thread-safe method to count already processed records"""
        with self.already_done_count_lock:
            self.already_done_count += 1
        self.log(f"\t\t⏭️  Already processed record {record_id} from {source}")

    def display_breakdown(self, messages_dict, title, icon):
        """Display breakdown of messages with IDs"""
        if not messages_dict:
            return

        self.log(f"\n{icon} {title}:")
        for message, ids in sorted(messages_dict.items(), key=lambda x: len(x[1]), reverse=True):
            count = len(ids)
            # Show first 10 IDs, then "and X more" if there are more
            if count <= 10:
                ids_display = ", ".join(ids)
            else:
                ids_display = ", ".join(ids[:10]) + f" and {count - 10} more"
            self.log(f"\t{count}x: {message}")
            self.log(f"\t    IDs: {ids_display}")

    def map_patient(self, external_patient_id):
        if patient_found := self.patient_map.get(external_patient_id):
            return patient_found[0], patient_found[1], "from mapping"

        canvas_patient = (
            PatientExternalIdentifier.objects.filter(value=external_patient_id)
            .values_list("patient__key", "patient_id")
            .first()
        )

        if not canvas_patient:
            raise Exception(f"Unable to find patient with external_id of {external_patient_id}")

        return canvas_patient[0], canvas_patient[1], "from db"

    def get_data_migration_note(self, canvas_patient_id):
        if note_found := self.note_map.get(str(canvas_patient_id)):
            self.log(f"\t\tFound note {note_found[0]} for {canvas_patient_id} from mapping")
            return note_found[0], note_found[1]

        note, created = Note.objects.get_or_create(
            patient_id=canvas_patient_id,
            note_type_version=self.NOTE_TYPE,
            provider=self.CANVAS_BOT.person_subclass,
            datetime_of_service=self.START_TIME,
            location=self.LOCATION,
            originator=self.CANVAS_BOT,
        )

        if created:
            NoteSerializer.create_note_dependencies(note, start_time=self.START_TIME)

        self.log(
            f"\t\t{'Created' if created else 'Found'} note {note.id} for {canvas_patient_id} from db"
        )
        return note.id, str(note.externally_exposable_id)

    def originate_and_commit_command(self, note_uuid, input_values):
        try:
            command_key, OriginateCommandInterpreterClass, CommitCommandInterpreterClass = (
                COMMAND_MAP[self.data_type]
            )

            originate_effect = Effect(
                type=f"ORIGINATE_{command_key.upper()}_COMMAND",
                payload=json.dumps(
                    {
                        "command": None,
                        "note": note_uuid,
                        "data": input_values,
                        "line_number": -1,
                    }
                ),
            )

            originate_interpreter = OriginateCommandInterpreterClass(originate_effect)
            command_uuid = originate_interpreter.handle()

            commit_effect = Effect(
                type=f"COMMIT_{command_key.upper()}_COMMAND",
                payload=json.dumps(
                    {
                        "command": command_uuid,
                    }
                ),
            )

            commit_interpreter = CommitCommandInterpreterClass(commit_effect)
            commit_interpreter.handle()

            return (
                CommandModel.objects.filter(uuid=command_uuid).values_list("id", flat=True).first()
            )

        except Exception as e:
            raise Exception(f"Failed to create command {e}")

    def handle_visual_exam_finding_command_chunk(
        self, chunk_data, chunk_index, total_chunks, chunk_display
    ):
        """Process a single chunk of visual exam finding command data"""
        total_in_chunk = len(chunk_data)

        consumer = VisualExamFindingMessageConsumer()

        for i, row in enumerate(chunk_data):
            self.log_chunk_progress(chunk_display, i, total_in_chunk, "Ingesting")

            if row["ID"] in self.done_records:
                self.already_done_row(row["ID"], "from done records")
                continue
            if ExternalMapping.objects.filter(
                canvas_type=self.data_type, source_system_identifier=row["ID"]
            ).exists():
                self.already_done_row(row["ID"], "from db")
                continue

            patient_id = row["Patient Identifier"]
            patient_key = ""
            try:
                patient_key, canvas_patient_id, patient_source = self.map_patient(patient_id)
            except Exception as e:
                self.ignore_row(patient_id, e)
                continue

            self.log(
                f"\t\tLooking at patient {patient_key}/{canvas_patient_id} from {patient_source} to ingest {row['ID']} {self.data_type}"
            )

            try:
                note_id, note_uuid = self.get_data_migration_note(canvas_patient_id)
            except Exception as e:
                self.error_row(
                    f"{row['ID']}|{patient_id}|{patient_key}", f"Unable to create note: {e}"
                )
                continue

            try:
                file = self.get_s3_file(
                    f"images/patient_symptoms_images/{row['Image']}",
                    convert_csv=False,
                    return_empty=False,
                )

                result = consumer.consume(
                    {
                        "integration_payload": {
                            "status": "completed",
                            "note_id": note_uuid,
                            "title": row["Title"],
                            "narrative": "\n".join(item["text"] for item in row["Comment"]),
                            "media": {"content_type": "image/jpeg", "content": file},
                        },
                        "patient_identifier": {
                            "identifier_type": "key",
                            "identifier": {"key": patient_key},
                        },
                    }
                )
                record_id = result.model_object.id

            except Exception as e:
                self.error_row(f"{row['ID']}|{patient_id}|{patient_key}", e)
                continue

            ExternalMapping.objects.create(
                patient_id=canvas_patient_id,
                source_system_type="images",
                source_system_identifier=row["ID"],
                canvas_type=self.data_type,
                canvas_id=record_id,
            )
            url = f"https://{settings.CUSTOMER_IDENTIFIER}.canvasmedical.com/patient/{patient_key}#commandId={record_id}&commandType=visualExamFinding&noteId={note_id}"
            self.log_chunk_success(chunk_display, row["ID"], f"created in {url}")

    def handle_medication_statement_command_chunk(
        self, chunk_data, chunk_index, total_chunks, chunk_display
    ):
        """Process a single chunk of medication statement command data"""
        count = 1
        total_in_chunk = len(chunk_data)

        consumer = MedicationStatementMessageConsumer()

        for patient_id, rows in chunk_data.items():
            self.log_chunk_progress(chunk_display, count, total_in_chunk, "Ingesting")

            # patient_key = ""
            # try:
            #     patient_key, canvas_patient_id = self.map_patient(patient_id)
            # except Exception as e:
            #     self.ignore_row(patient_id, e)
            #     continue

            self.log(f"\t\tLooking at patient {patient_id} to ingest {len(rows)} {self.data_type}")

            note_id = None
            note_uuid = None

            for row in rows:
                if row["ID"] in self.done_records:
                    self.already_done_row(row["ID"], "from done records")
                    continue
                if ExternalMapping.objects.filter(
                    canvas_type=self.data_type, source_system_identifier=row["ID"]
                ).exists():
                    self.already_done_row(row["ID"], "from db")
                    continue

                patient_key = row["Canvas Patient Key"]
                canvas_patient_id = row["Canvas Patient ID"]

                if not note_id:
                    try:
                        note_id, note_uuid = self.get_data_migration_note(canvas_patient_id)
                    except Exception as e:
                        self.error_row(
                            f"{row['ID']}|{patient_id}|{patient_key}", f"Unable to create note: {e}"
                        )
                        continue

                try:
                    coding = (
                        row["Coding"]
                        if isinstance(row["Coding"], list)
                        else [
                            {
                                "code": "",
                                "system": "UNSTRUCTURED",
                                "display": row["Coding"]["display"],
                            }
                        ]
                    )
                    coding = [{**c, "code_system": c["system"]} for c in coding]

                    # Format the sig string with proper length handling
                    sig_text = row["SIG"]
                    created_dates = row["Created"]

                    # Create original sig with dates
                    if created_dates:
                        dates_str = "\n".join(created_dates)
                        original_sig = f"{sig_text}\n{dates_str}"
                    else:
                        original_sig = sig_text

                    # Only apply formatting if original is over 255 characters
                    if len(original_sig) > 255:
                        # Remove "Directions:" prefix if present
                        sig_text = sig_text.replace("Directions:", "").strip()

                        # Format created dates
                        if created_dates:
                            if len(created_dates) == 1:
                                formatted_dates = f"Created on {created_dates[0]}"
                            else:
                                # Extract just the dates (remove "Created on " prefix)
                                dates_only = [
                                    date.replace("Created on ", "") for date in created_dates
                                ]
                                dates_joined = ",\n".join(dates_only)
                                formatted_dates = f"Created on:\n{dates_joined}"
                        else:
                            formatted_dates = ""

                        # Combine sig and dates
                        full_sig = f"{sig_text}\n{formatted_dates}" if formatted_dates else sig_text

                        # Truncate if over 255 characters
                        if len(full_sig) > 255:
                            self.error_row(
                                f"{row['ID']}|{patient_id}|{patient_key}",
                                f"Sig is too long {len(full_sig)}: {full_sig}",
                            )
                            continue
                    else:
                        # Use original formatting if under 255 characters
                        full_sig = original_sig

                    result = consumer.consume(
                        {
                            "integration_payload": {
                                "note_id": note_uuid,
                                "status": row["Status"],
                                "coding": coding,
                                "sig": full_sig,
                            },
                            "patient_identifier": {
                                "identifier_type": "key",
                                "identifier": {"key": patient_key},
                            },
                        }
                    )
                    medication = result.model_object
                    medication_statement_id = medication.medication_statements.first().id

                except Exception as e:
                    self.error_row(f"{row['ID']}|{patient_id}|{patient_key}", e)
                    continue

                ExternalMapping.objects.create(
                    patient_id=canvas_patient_id,
                    source_system_type="prescriptions",
                    source_system_identifier=row["ID"],
                    canvas_type=self.data_type,
                    canvas_id=medication_statement_id,
                )
                url = f"https://{settings.CUSTOMER_IDENTIFIER}.canvasmedical.com/patient/{patient_key}#commandId={medication_statement_id}&commandType=medicationStatement&noteId={note_id}"
                self.log_chunk_success(chunk_display, row["ID"], f"created in {url}")

            count += 1

    def handle_plan_commands_chunk(self, chunk_data, chunk_index, total_chunks, chunk_display):
        """Process a single chunk of plan command data"""
        count = 1
        total_in_chunk = len(chunk_data)

        for patient_id, rows in chunk_data.items():
            self.log_chunk_progress(chunk_display, count, total_in_chunk, "Ingesting")

            patient_key = ""
            try:
                patient_key, canvas_patient_id, patient_source = self.map_patient(patient_id)
            except Exception as e:
                self.ignore_row(patient_id, e)
                continue

            self.log(
                f"\t\tLooking at patient {patient_key}/{canvas_patient_id} from {patient_source} to ingest {len(rows)} {self.data_type}"
            )

            note_id = None
            note_uuid = None

            for row in rows:
                if row["ID"] in self.done_records:
                    self.already_done_row(row["ID"], "from done records")
                    continue
                if ExternalMapping.objects.filter(
                    canvas_type=self.data_type, source_system_identifier=row["ID"]
                ).exists():
                    self.already_done_row(row["ID"], "from db")
                    continue

                if not note_id:
                    try:
                        note_id, note_uuid = self.get_data_migration_note(canvas_patient_id)
                    except Exception as e:
                        self.error_row(
                            f"{row['ID']}|{patient_id}|{patient_key}", f"Unable to create note: {e}"
                        )
                        continue

                provider_name = ""
                try:
                    provider_name = self.DOCTOR_MAP[row["Provider"]]
                except Exception as e:
                    self.ignore_row(f"{patient_id}-{row['ID']}", e)
                    continue

                try:
                    date = arrow.get(row["Date"]).format("M/D/YY [at] h:mm A")
                except Exception as e:
                    self.error_row(f"{row['ID']}|{patient_id}|{patient_key}", e)
                    continue

                try:
                    command_id = self.originate_and_commit_command(
                        note_uuid=note_uuid, 
                        input_values={
                            "narrative": f"Provider: {provider_name}\nDate: {date} UTC\n{row['Text']}"
                        },
                    )
                except Exception as e:
                    self.error_row(f"{row['ID']}|{patient_id}|{patient_key}", e)
                    continue

                ExternalMapping.objects.create(
                    patient_id=canvas_patient_id,
                    source_system_type="internal_note",
                    source_system_identifier=row["ID"],
                    canvas_type=self.data_type,
                    canvas_id=command_id,
                )
                self.log_chunk_success(chunk_display, row["ID"], f"created as {command_id}")

            count += 1

    def handle_patients_chunk(self, chunk_data, chunk_index, total_chunks, chunk_display):
        """Process a single chunk of patient data"""
        sex_mapping = {
            "M": "M",
            "MALE": "M",
            "F": "F",
            "FEMALE": "F",
            "OTH": "O",
            "OTHER": "O",
            "UNK": "UNK",
            "UNKNOWN": "UNK",
        }

        total_in_chunk = len(chunk_data)
        self.log(f"\t{chunk_display} - Processing {total_in_chunk} patients")

        for i, row in enumerate(chunk_data):
            self.log_chunk_progress(chunk_display, i + 1, total_in_chunk, "Ingesting")

            # Check if patient already exists using map_patient function
            patient = None
            patient_key = None
            patient_id = None
            
            try:
                # Try to map the patient - this will raise an exception if not found
                patient_key, patient_id, source = self.map_patient(row["Identifier Value 1"])
            except Exception:
                # Patient doesn't exist, will create new one
                if self.update_mode:
                    self.log(f"\t\t⚠️  Patient {row['Identifier Value 1']} not found for update - will create new")
                else:
                    self.log(f"\t\t➕ Creating new patient {row['Identifier Value 1']}")
            else:
                # Patient was found
                if self.update_mode:
                    # In update mode, use the existing patient for updating
                    self.log(f"\t\t🔄 Updating existing patient {row['Identifier Value 1']} found from {source} as {patient_key}/{patient_id}")
                    patient = Patient.objects.prefetch_related(
                        'external_identifiers',
                        'addresses',
                        'telecom'
                    ).get(id=patient_id)
                else:
                    # In normal mode, skip existing patients
                    self.already_done_row(row["Identifier Value 1"], f"patient from {source} as {patient_key}/{patient_id}")
                    continue

            patient_data = {
                "first_name": row["First Name"],
                "middle_name": row["Middle Name"],
                "last_name": row["Last Name"],
                "birthdate": row["Date of Birth"],
                "sex_at_birth": sex_mapping[row["Sex at Birth"]],
                "nickname": row["Preferred Name"],
                "contact_points": {
                    "mode": "sync",
                    "entries": [],
                },
                "timezone": row["Timezone"],
                "clinical_note": row["Clinical Note"],
                "administrative_note": row["Administrative Note"],
                "external_identifiers": [
                    {
                        "use": "usual",
                        "value": row["Identifier Value 1"],
                        "issuer": row["Identifier System 1"],
                        "identifier_type": row["Identifier System 1"],
                    }
                ],
            }

            if self.update_mode and patient:
                external_identifier_id = patient.external_identifiers.filter(system=row["Identifier System 1"], value=row["Identifier Value 1"]).values_list("externally_exposable_id", flat=True).first()
                if external_identifier_id:
                    patient_data["external_identifiers"][0]["external_identifier"] = str(external_identifier_id)

            if row["Address Line 1"]:
                patient_data["addresses"] = [
                    {
                    "address1": row["Address Line 1"],
                    "address2": row["Address Line 2"],
                    "city": row["City"],
                    "state": row["State"],
                    "postal_code": row["Postal Code"],
                    "country": row["Country"],
                    "type": "both",
                        "use": "home",
                    }
                ]
                if self.update_mode and patient:
                    address_id = patient.addresses.values_list("externally_exposable_id", flat=True).first()
                    if address_id:
                        patient_data["addresses"][0]["address_identifier"] = str(address_id)

            if row["Mobile Phone Number"]:
                mobile_contact_point = {
                    "value": row["Mobile Phone Number"],
                    "system": "phone",
                    "use": "mobile",
                        "rank": "0",
                        "has_consent": row["Mobile Text Consent"] == "T",
                    }
                
                if self.update_mode and patient:
                    contact_point_id = patient.telecom.filter(system="phone", use="mobile").values_list("externally_exposable_id", flat=True).first()
                    if contact_point_id:
                        mobile_contact_point["contact_point_identifier"] = str(contact_point_id)

                patient_data["contact_points"]["entries"].append(mobile_contact_point)

            if row["Home Phone Number"]:
                home_contact_point = {
                    "value": row["Home Phone Number"],
                    "system": "phone",
                    "use": "home",
                        "rank": "1",
                    "has_consent": False,
                }
                if self.update_mode and patient:
                    contact_point_id = patient.telecom.filter(system="phone", use="home").values_list("externally_exposable_id", flat=True).first()
                    if contact_point_id:
                        home_contact_point["contact_point_identifier"] = str(contact_point_id)
                patient_data["contact_points"]["entries"].append(home_contact_point)

            if row["Email"]:
                email_contact_point = {
                    "value": row["Email"],
                    "system": "email",
                    "use": "home",
                        "rank": "0",
                        "has_consent": row["Email Consent"] == "T",
                }
                if self.update_mode and patient:
                    contact_point_id = patient.telecom.filter(system="email", use="home").values_list("externally_exposable_id", flat=True).first()
                    if contact_point_id:
                        email_contact_point["contact_point_identifier"] = str(contact_point_id)
                patient_data["contact_points"]["entries"].append(email_contact_point)

            # print(json.dumps(patient_data, indent=4))

            patient_fields = PatientMessageConsumer.process_patient_message(patient_data)

            if patient is None:
                patient = Patient.objects.create(**patient_fields)
                action = "created"
            else:
                for name, value in patient_fields.items():
                    setattr(patient, name, value)
                patient.save()
                action = "updated"

            PatientMessageConsumer.create_patient_related_records(patient, patient_data)

            # Use patient_key from map_patient if available, otherwise use patient.key
            display_key = patient_key if patient_key else patient.key
            self.log_chunk_success(
                chunk_display,
                row["Identifier Value 1"],
                f"{action} as https://{settings.CUSTOMER_IDENTIFIER}.canvasmedical.com/patient/{display_key}",
                action
            )

    def handle(self, data_type, *args: Any, **options: Any) -> None:
        self.data_type = data_type
        self.s3_file = options.get("s3_file")
        self.chunk_size = options.get("chunk_size")
        self.max_workers = options.get("max_workers")
        self.quiet = options.get("quiet", False)
        self.update_mode = options.get("update", False)

        self.log(f"Migrating data from file: {self.s3_file}")
        self.log(f"Using chunk size: {self.chunk_size}, max workers: {self.max_workers}")
        if self.update_mode:
            self.log("🔄 UPDATE MODE ENABLED: Existing records will be updated instead of skipped")

        data = self.get_s3_file(self.s3_file, convert_csv=True)

        # self.done_records = self.get_s3_file(f"done_{self.data_type}.json", return_empty=True)
        self.patient_map = self.get_s3_file("patient_ids_map.json", return_empty=True)
        # self.note_map = self.get_s3_file("historical_note_map.json", return_empty=True)

        handlers = {
            "plan_command": lambda data: self.process_data_threaded(
                data, self.handle_plan_commands_chunk
            ),
            "patients": lambda data: self.process_data_threaded(data, self.handle_patients_chunk),
            "medication_statement_command": lambda data: self.process_data_threaded(
                data, self.handle_medication_statement_command_chunk
            ),
            "visual_exam_finding_command": lambda data: self.process_data_threaded(
                data, self.handle_visual_exam_finding_command_chunk
            ),
        }

        # Validate data type
        if data_type not in handlers:
            raise ValueError(
                f"Unsupported data type: {data_type}. Supported types: {list(handlers.keys())}"
            )

        # Initialize thread locks for file operations
        self.error_lock = Lock()
        self.ignore_lock = Lock()
        self.done_lock = Lock()
        self.update_lock = Lock()

        # Initialize thread locks for counter operations
        self.error_count_lock = Lock()
        self.ignore_count_lock = Lock()
        self.done_count_lock = Lock()
        self.already_done_count_lock = Lock()
        self.update_count_lock = Lock()

        # Initialize counters for tracking processed records
        self.error_count = 0
        self.ignore_count = 0
        self.done_count = 0
        self.already_done_count = 0
        self.update_count = 0

        # Initialize error message tracking
        self.error_messages = {}  # {error_msg: [list of IDs]}
        self.ignore_messages = {}  # {ignore_msg: [list of IDs]}

        thread_storage.set("no_protocol_computations", True, immutable=False)

        # Suppress staff identification warnings during migration
        original_log_level = self.suppress_staff_identification_warning()

        # Instantiate varibales for this customer specifically
        self.CANVAS_BOT = CanvasUser.objects.get(id=1)
        self.LOCATION = PracticeLocation.objects.get(
            externally_exposable_id="29e0cff2-fbd8-4add-8a9a-7aa2d9e43594"
        )
        self.NOTE_TYPE = NoteType.objects.get(name="Historical Data Migration", is_active=True)
        self.START_TIME = "2025-09-30T09:00:00-04:00"  # 9am on go live date
        self.DOCTOR_MAP = self.get_s3_file("doctor_map.json")

        try:
            handlers[self.data_type](data)

        except Exception:
            self.log(f"Error ingesting: {traceback.format_exc()}", "error")
        finally:
            # Restore original log level
            original_log_level.setLevel(logging.WARNING)

            # Display final counts
            self.log("\n📊 Migration Summary:")
            self.log(f"\t✅ Successfully processed: {self.done_count} records")
            self.log(f"\t❌ Errors encountered: {self.error_count} records", "error")
            self.log(f"\t⚠️  Ignored records: {self.ignore_count} records", "ignore")
            self.log(f"\t⏭️  Already processed: {self.already_done_count} records")
            self.log(f"\t🔄  Updated records: {self.update_count} records")
            self.log(
                f"\t📈 Total processed: {self.done_count + self.error_count + self.ignore_count + self.already_done_count + self.update_count} records"
            )

            # Ask user if they want to see detailed breakdowns
            if self.error_messages or self.ignore_messages:
                self.log("\n💡 Detailed breakdowns available:")
                if self.error_messages:
                    unique_errors = len(self.error_messages)
                    self.log(f"\t❌ {unique_errors} different error types", "error")
                if self.ignore_messages:
                    unique_ignores = len(self.ignore_messages)
                    self.log(f"\t⚠️  {unique_ignores} different ignore reasons", "ignore")

                # Interactive prompt
                try:
                    show_details = input("\n🔍 Show detailed breakdown? (y/N): ").strip().lower()
                    if show_details in ["y", "yes"]:
                        # Display error and ignore breakdowns
                        self.display_breakdown(self.error_messages, "Error Breakdown", "❌")
                        self.display_breakdown(self.ignore_messages, "Ignore Breakdown", "⚠️")
                    else:
                        self.log(
                            '\n✅ Skipping detailed breakdown. Run again and choose "y" to see details.'
                        )
                except (EOFError, KeyboardInterrupt):
                    self.log("\n✅ Skipping detailed breakdown.")

        thread_storage.unset("no_protocol_computations")


cmd = Command()
cmd.handle("patients", s3_file="patients_diff_oct_update.csv", chunk_size=1000, max_workers=5, update=True)
