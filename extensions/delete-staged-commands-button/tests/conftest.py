"""Shared test fixtures for delete_staged_commands_button plugin."""
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
sys.modules['canvas_sdk.effects'] = MagicMock()
sys.modules['canvas_sdk.effects.Effect'] = MagicMock
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
sys.modules['canvas_sdk.v1.data.note'] = note_mock

immunization_mock = MagicMock()
immunization_mock.Immunization = MagicMock()
sys.modules['canvas_sdk.v1.data.immunization'] = immunization_mock

# Mock command classes
class MockCommand:
    """Base mock command class."""
    def __init__(self, command_uuid=None, **kwargs):
        self.command_uuid = command_uuid
        for key, value in kwargs.items():
            setattr(self, key, value)

    def delete(self):
        """Mock delete method."""
        return MagicMock()

def create_command_class(name, schema_key):
    """Create a mock command class with Meta.key attribute."""
    class Meta:
        key = schema_key

    return type(name, (MockCommand,), {'Meta': Meta})

# Create mock command classes with Meta.key
commands_mock = MagicMock()
commands_mock.AdjustPrescriptionCommand = create_command_class('AdjustPrescriptionCommand', 'adjustPrescription')
commands_mock.AllergyCommand = create_command_class('AllergyCommand', 'allergy')
commands_mock.AssessCommand = create_command_class('AssessCommand', 'assess')
commands_mock.CloseGoalCommand = create_command_class('CloseGoalCommand', 'closeGoal')
commands_mock.DiagnoseCommand = create_command_class('DiagnoseCommand', 'diagnose')
commands_mock.PhysicalExamCommand = create_command_class('PhysicalExamCommand', 'exam')
commands_mock.FamilyHistoryCommand = create_command_class('FamilyHistoryCommand', 'familyHistory')
commands_mock.FollowUpCommand = create_command_class('FollowUpCommand', 'followUp')
commands_mock.GoalCommand = create_command_class('GoalCommand', 'goal')
commands_mock.HistoryOfPresentIllnessCommand = create_command_class('HistoryOfPresentIllnessCommand', 'hpi')
commands_mock.ImagingOrderCommand = create_command_class('ImagingOrderCommand', 'imagingOrder')
commands_mock.ImagingReviewCommand = create_command_class('ImagingReviewCommand', 'imagingReview')
commands_mock.ImmunizationStatementCommand = create_command_class('ImmunizationStatementCommand', 'immunizationStatement')
commands_mock.InstructCommand = create_command_class('InstructCommand', 'instruct')
commands_mock.LabOrderCommand = create_command_class('LabOrderCommand', 'labOrder')
commands_mock.LabReviewCommand = create_command_class('LabReviewCommand', 'labReview')
commands_mock.MedicalHistoryCommand = create_command_class('MedicalHistoryCommand', 'medicalHistory')
commands_mock.MedicationStatementCommand = create_command_class('MedicationStatementCommand', 'medicationStatement')
commands_mock.PerformCommand = create_command_class('PerformCommand', 'perform')
commands_mock.PlanCommand = create_command_class('PlanCommand', 'plan')
commands_mock.PrescribeCommand = create_command_class('PrescribeCommand', 'prescribe')
commands_mock.QuestionnaireCommand = create_command_class('QuestionnaireCommand', 'questionnaire')
commands_mock.ReasonForVisitCommand = create_command_class('ReasonForVisitCommand', 'reasonForVisit')
commands_mock.ReferCommand = create_command_class('ReferCommand', 'refer')
commands_mock.ReferralReviewCommand = create_command_class('ReferralReviewCommand', 'referralReview')
commands_mock.RefillCommand = create_command_class('RefillCommand', 'refill')
commands_mock.RemoveAllergyCommand = create_command_class('RemoveAllergyCommand', 'removeAllergy')
commands_mock.ResolveConditionCommand = create_command_class('ResolveConditionCommand', 'resolveCondition')
commands_mock.ReviewOfSystemsCommand = create_command_class('ReviewOfSystemsCommand', 'ros')
commands_mock.StopMedicationCommand = create_command_class('StopMedicationCommand', 'stopMedication')
commands_mock.StructuredAssessmentCommand = create_command_class('StructuredAssessmentCommand', 'structuredAssessment')
commands_mock.PastSurgicalHistoryCommand = create_command_class('PastSurgicalHistoryCommand', 'surgicalHistory')
commands_mock.TaskCommand = create_command_class('TaskCommand', 'task')
commands_mock.UncategorizedDocumentReviewCommand = create_command_class('UncategorizedDocumentReviewCommand', 'uncategorizedDocumentReview')
commands_mock.UpdateDiagnosisCommand = create_command_class('UpdateDiagnosisCommand', 'updateDiagnosis')
commands_mock.UpdateGoalCommand = create_command_class('UpdateGoalCommand', 'updateGoal')
commands_mock.VitalsCommand = create_command_class('VitalsCommand', 'vitals')

sys.modules['canvas_sdk.commands'] = commands_mock

# Mock change medication command
change_medication_mock = MagicMock()
change_medication_mock.ChangeMedicationCommand = create_command_class('ChangeMedicationCommand', 'changeMedication')
sys.modules['canvas_sdk.commands.commands'] = MagicMock()
sys.modules['canvas_sdk.commands.commands.change_medication'] = change_medication_mock

# Mock immunization statement command
immunization_statement_mock = MagicMock()
immunization_statement_mock.ImmunizationStatementCommand = create_command_class('ImmunizationStatementCommand', 'immunizationStatement')
sys.modules['canvas_sdk.commands.commands.immunization_statement'] = immunization_statement_mock

# Mock logger
logger_mock = MagicMock()
logger_mock.log = MagicMock()
sys.modules['logger'] = logger_mock


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
    return note


@pytest.fixture
def mock_staged_command():
    """Create a mock staged command."""
    command = MagicMock()
    command.id = "cmd-uuid-123"
    command.schema_key = "diagnose"
    command.state = "staged"
    return command
