from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from logger import log


class LogNoteLocksAndUnlocks(BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    def compute(self) -> list[Effect]:
        # NEW            = "NEW"
        # PUSHED         = "PSH"
        # LOCKED         = "LKD"
        # UNLOCKED       = "ULK"
        # DELETED        = "DLT"
        # RELOCKED       = "RLK"
        # RESTORED       = "RST"
        # RECALLED       = "RCL"
        # UNDELETED      = "UND"
        # DISCHARGED     = "DSC"
        # SCHEDULING     = "SCH"
        # BOOKED         = "BKD"
        # CONVERTED      = "CVD"
        # CANCELLED      = "CLD"
        # NOSHOW         = "NSW"
        # REVERTED       = "RVT"
        # CONFIRM_IMPORT = "CNF"
        new_note_state = self.context['state']
        note_id = self.context['note_id']
        if new_note_state == 'LKD':
            log.info(f"Note {note_id} was just locked!")
        elif new_note_state == 'ULK':
            log.info(f"Note {note_id} was just unlocked!")
        else:
            log.info(f"Note {note_id} just entered state {new_note_state}!")

        return []
