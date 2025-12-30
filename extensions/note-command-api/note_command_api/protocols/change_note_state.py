from http import HTTPStatus
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPIRoute
from canvas_sdk.v1.data.note import Note
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.note.appointment import Appointment as AppointmentEffect
from canvas_sdk.v1.data.appointment import Appointment
from logger import log

class NoteStateChangeAPI(APIKeyAuthMixin, SimpleAPIRoute):
    """
    SimpleAPI endpoint that changes the state of a note.
    POST /note/<note_id>/state - Changes the state of a note.
    """
    PATH = "/note/<note_id>/state"
    def post(self) -> list[Response | Effect]:
        """
        Changes the state of a note.
        """
        note_id = self.request.path_params.get("note_id")
        if not note_id:
            return [
                JSONResponse(
                    {"error": "Note ID is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        note = Note.objects.filter(id=note_id).first()
        if not note:
            return [
                JSONResponse(
                    {"error": "Note not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        current_appointment_id = Appointment.objects.filter(note=note).order_by('dbid').values_list('id', flat=True).last()

        note_state = self.request.query_params.get("state")
        if not note_state:
            return [
                JSONResponse(
                    {"error": "Note state is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        
        note_state_func_map = {
            "lock": NoteEffect(instance_id=note_id).lock,
            "unlock": NoteEffect(instance_id=note_id).unlock,
            "sign": NoteEffect(instance_id=note_id).sign,
            "push_charges": NoteEffect(instance_id=note_id).push_charges,
            "check_in": NoteEffect(instance_id=note_id).check_in,
            "no_show": NoteEffect(instance_id=note_id).no_show,
            "cancel": AppointmentEffect(instance_id=current_appointment_id).cancel,
        }

        log.info(f"Attempting to {note_state} note {note_id} with appointment {current_appointment_id}")

        if note_state_func_map.get(note_state):
            try: 
                return [
                    note_state_func_map.get(note_state)(), 
                    JSONResponse({'message': f"Note {note_id} state changed to {note_state}"}, status_code=HTTPStatus.OK)
                ]
            except Exception as e:
                log.error(f"Error changing note state: {e}")
                return [
                    JSONResponse({'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
                ]
        else:
            return [
                JSONResponse(
                    {"error": "Invalid note state"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]