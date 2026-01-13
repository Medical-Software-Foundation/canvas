"""Shared test fixtures for carry_forward plugin."""
import sys
from unittest.mock import MagicMock
import pytest
from datetime import datetime

# Create a proper base class for ActionButton
class MockActionButton:
    """Mock base class for ActionButton that allows inheritance."""
    class ButtonLocation:
        NOTE_HEADER = "note_header"

    BUTTON_TITLE = ""
    BUTTON_KEY = ""
    BUTTON_LOCATION = None

    def __init__(self):
        self.event = None

# Mock Canvas SDK and other dependencies before any imports
sys.modules['canvas_sdk'] = MagicMock()

# Mock effects module and submodules
effects_mock = MagicMock()
effects_mock.Effect = MagicMock
sys.modules['canvas_sdk.effects'] = effects_mock

batch_originate_mock = MagicMock()
batch_originate_mock.BatchOriginateCommandEffect = MagicMock
sys.modules['canvas_sdk.effects.batch_originate'] = batch_originate_mock

sys.modules['canvas_sdk.handlers'] = MagicMock()

# Create action_button module with MockActionButton
action_button_mock = MagicMock()
action_button_mock.ActionButton = MockActionButton
sys.modules['canvas_sdk.handlers.action_button'] = action_button_mock

sys.modules['canvas_sdk.v1'] = MagicMock()
sys.modules['canvas_sdk.v1.data'] = MagicMock()

# Mock data models
command_mock = MagicMock()
command_mock.Command = MagicMock()
sys.modules['canvas_sdk.v1.data.command'] = command_mock

note_mock = MagicMock()
note_mock.Note = MagicMock()
note_mock.NoteType = MagicMock()
note_mock.NoteStates = MagicMock()
sys.modules['canvas_sdk.v1.data.note'] = note_mock

questionnaire_mock = MagicMock()
questionnaire_mock.Questionnaire = MagicMock()
sys.modules['canvas_sdk.v1.data.questionnaire'] = questionnaire_mock

# Mock ReasonForVisitSettingCoding
data_mock = MagicMock()
data_mock.ReasonForVisitSettingCoding = MagicMock()
sys.modules['canvas_sdk.v1.data'] = data_mock

# Mock command classes
class MockCommand:
    """Base mock command class."""
    def __init__(self, note_uuid=None, **kwargs):
        self.note_uuid = note_uuid
        for key, value in kwargs.items():
            setattr(self, key, value)

    def originate(self):
        """Mock originate method."""
        return MagicMock()

# Create mock command classes
commands_mock = MagicMock()
commands_mock.DiagnoseCommand = type('DiagnoseCommand', (MockCommand,), {})
commands_mock.PhysicalExamCommand = type('PhysicalExamCommand', (MockCommand,), {})
commands_mock.HistoryOfPresentIllnessCommand = type('HistoryOfPresentIllnessCommand', (MockCommand,), {})
commands_mock.PlanCommand = type('PlanCommand', (MockCommand,), {})
commands_mock.PerformCommand = type('PerformCommand', (MockCommand,), {})
commands_mock.QuestionnaireCommand = type('QuestionnaireCommand', (MockCommand,), {})
commands_mock.ReasonForVisitCommand = type('ReasonForVisitCommand', (MockCommand,), {})
commands_mock.ReviewOfSystemsCommand = type('ReviewOfSystemsCommand', (MockCommand,), {})
commands_mock.StructuredAssessmentCommand = type('StructuredAssessmentCommand', (MockCommand,), {})

# Create VitalsCommand with special attributes
class MockVitalsCommand(MockCommand):
    class BodyTemperatureSite:
        AXILLARY = "axillary"
        ORAL = "oral"
        RECTAL = "rectal"
        TEMPORAL = "temporal"
        TYMPANIC = "tympanic"

    class BloodPressureSite:
        SITTING_RIGHT_UPPER = "sitting_right_upper"
        SITTING_LEFT_UPPER = "sitting_left_upper"
        SITTING_RIGHT_LOWER = "sitting_right_lower"
        SITTING_LEFT_LOWER = "sitting_left_lower"
        STANDING_RIGHT_UPPER = "standing_right_upper"
        STANDING_LEFT_UPPER = "standing_left_upper"
        STANDING_RIGHT_LOWER = "standing_right_lower"
        STANDING_LEFT_LOWER = "standing_left_lower"
        SUPINE_RIGHT_UPPER = "supine_right_upper"
        SUPINE_LEFT_UPPER = "supine_left_upper"
        SUPINE_RIGHT_LOWER = "supine_right_lower"
        SUPINE_LEFT_LOWER = "supine_left_lower"

    class PulseRhythm:
        REGULAR = "regular"
        IRREGULARLY_IRREGULAR = "irregularly_irregular"
        REGULARLY_IRREGULAR = "regularly_irregular"

commands_mock.VitalsCommand = MockVitalsCommand

# Create AssessCommand with Status enum
class MockAssessCommand(MockCommand):
    class Status:
        IMPROVED = "improved"
        STABLE = "stable"
        DETERIORATED = "deteriorated"

commands_mock.AssessCommand = MockAssessCommand

# Create FollowUpCommand
commands_mock.FollowUpCommand = type('FollowUpCommand', (MockCommand,), {})

# Create ImagingOrderCommand with Priority enum
class MockImagingOrderCommand(MockCommand):
    class Priority:
        ROUTINE = "routine"
        URGENT = "urgent"

commands_mock.ImagingOrderCommand = MockImagingOrderCommand

# Create InstructCommand
commands_mock.InstructCommand = type('InstructCommand', (MockCommand,), {})

# Create LabOrderCommand
commands_mock.LabOrderCommand = type('LabOrderCommand', (MockCommand,), {})

# Create ReferCommand with Priority and ClinicalQuestion enums
class MockReferCommand(MockCommand):
    class Priority:
        ROUTINE = "routine"
        URGENT = "urgent"

    class ClinicalQuestion:
        COGNITIVE_ASSISTANCE = "cognitive_assistance"
        ASSISTANCE_WITH_ONGOING_MANAGEMENT = "assistance_with_ongoing_management"
        SPECIALIZED_INTERVENTION = "specialized_intervention"
        DIAGNOSTIC_UNCERTAINTY = "diagnostic_uncertainty"

commands_mock.ReferCommand = MockReferCommand

# Create TaskCommand
commands_mock.TaskCommand = type('TaskCommand', (MockCommand,), {})

# Create RefillCommand
commands_mock.RefillCommand = type('RefillCommand', (MockCommand,), {})

# Create GoalCommand with AchievementStatus and Priority enums
class MockGoalCommand(MockCommand):
    class AchievementStatus:
        IN_PROGRESS = "in-progress"
        IMPROVING = "improving"
        WORSENING = "worsening"
        NO_CHANGE = "no-change"
        ACHIEVED = "achieved"
        SUSTAINING = "sustaining"
        NOT_ACHIEVED = "not-achieved"
        NO_PROGRESS = "no-progress"
        NOT_ATTAINABLE = "not-attainable"

    class Priority:
        HIGH = "high-priority"
        MEDIUM = "medium-priority"
        LOW = "low-priority"

commands_mock.GoalCommand = MockGoalCommand

# Create UpdateGoalCommand with AchievementStatus and Priority enums
class MockUpdateGoalCommand(MockCommand):
    class AchievementStatus:
        IN_PROGRESS = "in-progress"
        IMPROVING = "improving"
        WORSENING = "worsening"
        NO_CHANGE = "no-change"
        ACHIEVED = "achieved"
        SUSTAINING = "sustaining"
        NOT_ACHIEVED = "not-achieved"
        NO_PROGRESS = "no-progress"
        NOT_ATTAINABLE = "not-attainable"

    class Priority:
        HIGH = "high-priority"
        MEDIUM = "medium-priority"
        LOW = "low-priority"

commands_mock.UpdateGoalCommand = MockUpdateGoalCommand

# Create AllergyCommand with Severity enum
class MockAllergyCommand(MockCommand):
    class Severity:
        MILD = "mild"
        MODERATE = "moderate"
        SEVERE = "severe"

commands_mock.AllergyCommand = MockAllergyCommand

# Create FamilyHistoryCommand
commands_mock.FamilyHistoryCommand = type('FamilyHistoryCommand', (MockCommand,), {})

# Create PrescribeCommand with Substitutions enum
class MockPrescribeCommand(MockCommand):
    class Substitutions:
        ALLOWED = "allowed"
        NOT_ALLOWED = "not_allowed"

commands_mock.PrescribeCommand = MockPrescribeCommand

sys.modules['canvas_sdk.commands'] = commands_mock

# Mock command constants
constants_mock = MagicMock()
constants_mock.ClinicalQuantity = MagicMock
constants_mock.CodeSystems = MagicMock()
constants_mock.CodeSystems.SNOMED = "http://snomed.info/sct"
constants_mock.CodeSystems.UNSTRUCTURED = "unstructured"
constants_mock.CodeSystems.ICD10 = "http://hl7.org/fhir/sid/icd-10"
constants_mock.CodeSystems.FDB = "http://fdb.com"
constants_mock.Coding = MagicMock
constants_mock.ServiceProvider = MagicMock
sys.modules['canvas_sdk.commands.constants'] = constants_mock

# Mock allergy command
allergy_mock = MagicMock()
allergy_mock.AllergenType = MagicMock()
allergy_mock.AllergenType.ALLERGEN_GROUP = "allergen_group"
allergy_mock.AllergenType.MEDICATION = "medication"
allergy_mock.AllergenType.INGREDIENT = "ingredient"
allergy_mock.Allergen = MagicMock
sys.modules['canvas_sdk.commands.commands'] = MagicMock()
sys.modules['canvas_sdk.commands.commands.allergy'] = allergy_mock

# Mock task command
task_mock = MagicMock()
task_mock.TaskAssigner = MagicMock
task_mock.AssigneeType = MagicMock()
task_mock.AssigneeType.STAFF = "staff"
task_mock.AssigneeType.TEAM = "team"
task_mock.AssigneeType.UNASSIGNED = "unassigned"
task_mock.AssigneeType.ROLE = "role"
sys.modules['canvas_sdk.commands.commands.task'] = task_mock

# Mock change medication command
change_medication_mock = MagicMock()
change_medication_mock.ChangeMedicationCommand = MagicMock
sys.modules['canvas_sdk.commands.commands.change_medication'] = change_medication_mock

# Mock additional data models
staff_mock = MagicMock()
staff_mock.Staff = MagicMock()
sys.modules['canvas_sdk.v1.data.staff'] = staff_mock

medication_mock = MagicMock()
medication_mock.MedicationCoding = MagicMock()
medication_mock.Medication = MagicMock()
sys.modules['canvas_sdk.v1.data.medication'] = medication_mock

condition_mock = MagicMock()
condition_mock.Condition = MagicMock()
condition_mock.ConditionCoding = MagicMock()
sys.modules['canvas_sdk.v1.data.condition'] = condition_mock

goal_mock = MagicMock()
goal_mock.Goal = MagicMock()
sys.modules['canvas_sdk.v1.data.goal'] = goal_mock

sys.modules['canvas_sdk.value_set'] = MagicMock()
sys.modules['canvas_sdk.value_set.v2022'] = MagicMock()
sys.modules['canvas_sdk.value_set.v2022.condition'] = MagicMock()

# Mock logger
logger_mock = MagicMock()
logger_mock.log = MagicMock()
sys.modules['logger'] = logger_mock

# Mock arrow
class MockArrow:
    @staticmethod
    def get(date_string):
        """Mock arrow.get() to return an object with a .date() method."""
        from datetime import datetime
        mock_date = MagicMock()
        if isinstance(date_string, str):
            mock_date.date.return_value = datetime.strptime(date_string, "%Y-%m-%d").date()
        else:
            mock_date.date.return_value = datetime(2024, 1, 1).date()
        return mock_date

arrow_mock = MagicMock()
arrow_mock.get = MockArrow.get
sys.modules['arrow'] = arrow_mock

sys.modules['dateutil'] = MagicMock()
sys.modules['dateutil.relativedelta'] = MagicMock()


@pytest.fixture
def mock_event():
    """Create a mock event with note context."""
    event = MagicMock()
    event.context = {
        "note_id": "test-note-123"
    }
    return event


@pytest.fixture
def mock_note():
    """Create a mock note."""
    note = MagicMock()
    note.dbid = "test-note-123"
    note.id = "uuid-note-123"
    note.note_type_version.name = "Office visit"
    note.datetime_of_service = datetime(2024, 12, 9, 10, 0, 0)
    note.body = [{"type": "text", "value": ""}]
    note.patient = MagicMock()
    note.patient.id = "patient-123"
    return note


@pytest.fixture
def mock_previous_note():
    """Create a mock previous note with content."""
    note = MagicMock()
    note.dbid = "prev-note-456"
    note.id = "uuid-prev-note-456"
    note.note_type_version.name = "Office visit"
    note.datetime_of_service = datetime(2024, 12, 8, 10, 0, 0)
    note.body = [{"type": "command", "value": "some content"}]
    note.patient = MagicMock()
    note.patient.id = "patient-123"
    return note


@pytest.fixture
def mock_command():
    """Create a mock command."""
    command = MagicMock()
    command.schema_key = "diagnose"
    command.created = datetime(2024, 12, 8, 10, 30, 0)
    command.data = {
        "diagnose": {"value": "I10"},
        "background": "Patient has hypertension",
        "today_assessment": "BP elevated",
        "approximate_date_of_onset": {"date": "2024-01-01"}
    }
    return command
