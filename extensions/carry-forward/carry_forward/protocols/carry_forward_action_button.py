import arrow
import re
import uuid

from canvas_sdk.commands import *
from canvas_sdk.commands.commands.change_medication import ChangeMedicationCommand
from canvas_sdk.commands.commands.task import TaskAssigner, AssigneeType
from canvas_sdk.commands.constants import ClinicalQuantity, CodeSystems, Coding, ServiceProvider

from canvas_sdk.effects import Effect
from canvas_sdk.effects.batch_originate import BatchOriginateCommandEffect

from canvas_sdk.handlers.action_button import ActionButton

from canvas_sdk.v1.data import ReasonForVisitSettingCoding
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.condition import Condition, ConditionCoding
from canvas_sdk.v1.data.goal import Goal
from canvas_sdk.v1.data.medication import MedicationCoding
from canvas_sdk.v1.data.note import Note, NoteType, NoteStates
from canvas_sdk.v1.data.questionnaire import Questionnaire
from canvas_sdk.v1.data.staff import Staff


from logger import log


class CarryForwardActionButton(ActionButton):
    """
        Adds a Carry Forward Last Note action button to the note header
        that appears in specific empty note types. 

        When pressed it will find the commands committed in a previous note 
        and originate them in the current note
    """


    BUTTON_TITLE = "Carry Forward Last Note"
    BUTTON_KEY = "CARRY_FORWARD_LAST_NOTE"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    VISIBLE_NOTE_TYPE_NAMES = (
        'Office visit',
        'Telehealth',
        'Phone call',
        'Home visit'
    )

    GOAL_STATUS_MAP = {
        "in-progress": GoalCommand.AchievementStatus.IN_PROGRESS,
        "improving": GoalCommand.AchievementStatus.IMPROVING,
        "worsening": GoalCommand.AchievementStatus.WORSENING,
        "no-change": GoalCommand.AchievementStatus.NO_CHANGE,
        "achieved": GoalCommand.AchievementStatus.ACHIEVED,
        "sustaining": GoalCommand.AchievementStatus.SUSTAINING,
        "not-achieved": GoalCommand.AchievementStatus.NOT_ACHIEVED,
        "no-progress": GoalCommand.AchievementStatus.NO_PROGRESS,
        "not-attainable": GoalCommand.AchievementStatus.NOT_ATTAINABLE,
    }
    GOAL_PRIORITY_MAP = {
        "high-priority": GoalCommand.Priority.HIGH,
        "medium-priority": GoalCommand.Priority.MEDIUM,
        "low-priority": GoalCommand.Priority.LOW,
    }

    def note_body_is_empty(self, note):
        """
            Loop through the Note Body to see if the note is completely empty of commands
        """
        return all([b == {'type': 'text', 'value': ''} for b in note.body])

    def find_previous_note(self, note):
        # find a previous note type to carry forward from
        previous_notes = Note.objects.filter(
            patient=note.patient,
            note_type_version__name__in=self.VISIBLE_NOTE_TYPE_NAMES,
            datetime_of_service__lt=note.datetime_of_service,
            current_state__state__in=(
                NoteStates.SIGNED,
                NoteStates.LOCKED,
                NoteStates.DISCHARGED,
                NoteStates.UNDELETED,
                NoteStates.PUSHED,
                NoteStates.UNLOCKED,
                NoteStates.NEW,
                NoteStates.CONVERTED,
            )
        ).order_by('-datetime_of_service')
        for prev_note in previous_notes:
            if not self.note_body_is_empty(prev_note):
                return prev_note

        return None

    def visible(self) -> bool:
        """
            Only show button if we are in a specific note type 
            and no commands are already in the note
            and a previous note exists to carry forward commands from
        """
        note_id = self.event.context['note_id']
        note = Note.objects.get(dbid=note_id)

        log.info(f"{note.note_type_version.name} Note Loaded")
        return (
            note.note_type_version.name in self.VISIBLE_NOTE_TYPE_NAMES
            and self.note_body_is_empty(note)
            and self.find_previous_note(note) is not None
        )

    def _carry_forward_plan(self, effect, data, command=None):
        """Carry forward plan command data"""
        effect.narrative = data.get('narrative') or ""
        return effect

    def _carry_forward_hpi(self, effect, data, command=None):
        """Carry forward history of present illness command data"""
        effect.narrative = data.get('narrative') or ""
        return effect

    def _carry_forward_reason_for_visit(self, effect, data, command=None):
        """Carry forward reason for visit command data"""
        if coding := data.get('coding'):
            rfv_coding = ReasonForVisitSettingCoding.objects.filter(code=coding['value']).order_by('id').last()
            if rfv_coding:
                effect.coding = str(rfv_coding.id)
                effect.structured = True
        effect.comment = data.get('comment') or ''
        return effect

    def _carry_forward_questionnaire_ros_sa_exam(self, effect, data, command=None):
        """Carry forward questionnaire, review of systems, structured assessment, and exam command data"""
        q = Questionnaire.objects.filter(dbid=data['questionnaire']['extra']['pk']).first()
        if q:
            effect.questionnaire_id = str(q.id)
            effect.command_uuid = str(uuid.uuid4())
            for ques in effect.questions:
                ques_id = ques.name.split('-')[1]
                log.info(f"Question {ques_id} data: {data.get(ques.name)} and skip: {data.get(f'skip-{ques_id}')}")
                if response := data.get(ques.name):
                    if ques.type in ['TXT', 'INT']:
                        ques.add_response(text=response)
                    elif ques.type == 'SING':
                        selected_option = next((o for o in ques.options if o.dbid == response), None)
                        if selected_option:
                            ques.add_response(option=selected_option)
                    elif ques.type == 'MULT':
                        for r in response:
                            selected_option = next((o for o in ques.options if o.dbid == r['value']), None)
                            if selected_option:
                                ques.add_response(option=selected_option, selected=r['selected'], comment=r['comment'])
                if f"skip-{ques_id}" in data:
                    effect.set_question_enabled(ques_id, data[f'skip-{ques_id}'])
        return effect

    def _carry_forward_diagnose(self, effect, data, command=None):
        """Carry forward diagnose command data"""
        effect.icd10_code = data['diagnose']['value']
        effect.background = data.get('background') or ""
        effect.today_assessment = data.get('today_assessment') or ""
        date = data.get('approximate_date_of_onset')
        if date:
            effect.approximate_date_of_onset = arrow.get(date['date']).date()
        return effect

    def _carry_forward_assess(self, effect, data, command=None):
        """Carry forward assess command data"""
        assess_status_map = {
            "improved": AssessCommand.Status.IMPROVED,
            "stable": AssessCommand.Status.STABLE,
            "deteriorated": AssessCommand.Status.DETERIORATED,
        }
        effect.condition_id = str(Condition.objects.filter(dbid=data['condition']['value']).first().id) if data.get('condition') else None
        effect.background = data.get('background')
        effect.status = assess_status_map.get(data.get('status'))
        effect.narrative = data.get('narrative')
        return effect

    def _carry_forward_diagnose_to_assess(self, effect, data, command=None):
        """Carry forward diagnose command data to assess command data"""
        anchor_object = command.anchor_object if command else None
        effect.condition_id = str(anchor_object.id) if anchor_object else str(Condition.objects.filter(codings__code=data['diagnose']['value']).order_by('dbid').last().id) if data.get('diagnose') else None
        effect.background = data.get('background') or ""
        effect.narrative = data.get('today_assessment') or ""
        return effect

    def _carry_forward_update_diagnosis_to_assess(self, effect, data, command=None):
        """Carry forward update diagnosis command data to assess command data"""
        anchor_object = command.anchor_object if command else None
        effect.condition_id = str(anchor_object.id) if anchor_object else (str(Condition.objects.filter(codings__code=data['new_condition']['value']).order_by('dbid').last().id) if data.get('new_condition') else None)
        effect.background = data.get('background') or ""
        effect.narrative = data.get('narrative') or ""
        return effect

    def _carry_forward_perform(self, effect, data, command=None):
        """Carry forward perform command data"""
        effect.notes = data.get('notes') or ""
        effect.cpt_code = data['perform']['value']
        return effect

    def _carry_forward_vitals(self, effect, data, command=None):
        """Carry forward vitals command data"""
        effect.height = int(data['height']) if data['height'] else None
        effect.weight_lbs = int(data['weight_lbs']) if data['weight_lbs'] else None
        effect.weight_oz = int(data['weight_oz']) if data['weight_oz'] else None
        effect.waist_circumference = int(data['waist_circumference']) if data['waist_circumference'] else None
        effect.body_temperature = int(data['body_temperature']) if data['body_temperature'] else None
        effect.blood_pressure_systole = int(data['blood_pressure_systole']) if data['blood_pressure_systole'] else None
        effect.blood_pressure_diastole = int(data['blood_pressure_diastole']) if data['blood_pressure_diastole'] else None
        effect.pulse = int(data['pulse']) if data['pulse'] else None
        effect.respiration_rate = int(data['respiration_rate']) if data['respiration_rate'] else None
        effect.oxygen_saturation = int(data['oxygen_saturation']) if data['oxygen_saturation'] else None

        body_temp_site_map = {
            "0": VitalsCommand.BodyTemperatureSite.AXILLARY,
            "1": VitalsCommand.BodyTemperatureSite.ORAL,
            "2": VitalsCommand.BodyTemperatureSite.RECTAL,
            "3": VitalsCommand.BodyTemperatureSite.TEMPORAL,
            "4": VitalsCommand.BodyTemperatureSite.TYMPANIC,
        }
        effect.body_temperature_site = body_temp_site_map.get(data['body_temperature_site'])
        bp_map = {
            "0": VitalsCommand.BloodPressureSite.SITTING_RIGHT_UPPER,
            "1": VitalsCommand.BloodPressureSite.SITTING_LEFT_UPPER,
            "2": VitalsCommand.BloodPressureSite.SITTING_RIGHT_LOWER,
            "3": VitalsCommand.BloodPressureSite.SITTING_LEFT_LOWER,
            "4": VitalsCommand.BloodPressureSite.STANDING_RIGHT_UPPER,
            "5": VitalsCommand.BloodPressureSite.STANDING_LEFT_UPPER,
            "6": VitalsCommand.BloodPressureSite.STANDING_RIGHT_LOWER,
            "7": VitalsCommand.BloodPressureSite.STANDING_LEFT_LOWER,
            "8": VitalsCommand.BloodPressureSite.SUPINE_RIGHT_UPPER,
            "9": VitalsCommand.BloodPressureSite.SUPINE_LEFT_UPPER,
            "10": VitalsCommand.BloodPressureSite.SUPINE_RIGHT_LOWER,
            "11": VitalsCommand.BloodPressureSite.SUPINE_LEFT_LOWER,
        }
        effect.blood_pressure_position_and_site = bp_map.get(data['blood_pressure_position_and_site'])
        pulse_rhythm_map = {
            '0': VitalsCommand.PulseRhythm.REGULAR,
            '1': VitalsCommand.PulseRhythm.IRREGULARLY_IRREGULAR,
            '2': VitalsCommand.PulseRhythm.REGULARLY_IRREGULAR,
        }
        effect.pulse_rhythm = pulse_rhythm_map.get(data['pulse_rhythm'])
        effect.note = data.get('note')
        return effect

    def _carry_forward_goal(self, effect, data, command=None):
        """Carry forward goal command data"""
        effect.goal_statement = data.get('goal_statement')
        effect.start_date = arrow.get(data.get('start_date')).date() if data.get('start_date') else None
        effect.due_date = arrow.get(data.get('due_date')).datetime if data.get('due_date') else None
        effect.achievement_status = self.GOAL_STATUS_MAP.get(data.get('achievement_status'))
        effect.priority = self.GOAL_PRIORITY_MAP.get(data.get('priority'))
        effect.progress = data.get('progress')
        return effect

    def _carry_forward_update_goal(self, effect, data, command=None):
        """Carry forward update goal command data"""
        GOAL_STATUS_MAP = {
            "in-progress": UpdateGoalCommand.AchievementStatus.IN_PROGRESS,
            "improving": UpdateGoalCommand.AchievementStatus.IMPROVING,
            "worsening": UpdateGoalCommand.AchievementStatus.WORSENING,
            "no-change": UpdateGoalCommand.AchievementStatus.NO_CHANGE,
            "achieved": UpdateGoalCommand.AchievementStatus.ACHIEVED,
            "sustaining": UpdateGoalCommand.AchievementStatus.SUSTAINING,
            "not-achieved": UpdateGoalCommand.AchievementStatus.NOT_ACHIEVED,
            "no-progress": UpdateGoalCommand.AchievementStatus.NO_PROGRESS,
            "not-attainable": UpdateGoalCommand.AchievementStatus.NOT_ATTAINABLE,
        }
        GOAL_PRIORITY_MAP = {
            "high-priority": UpdateGoalCommand.Priority.HIGH,
            "medium-priority": UpdateGoalCommand.Priority.MEDIUM,
            "low-priority": UpdateGoalCommand.Priority.LOW,
        }

        if not effect.goal_id:
            effect.goal_id = str(Goal.objects.filter(dbid=data['goal_statement']['value']).first().id) if data.get('goal_statement') else None
        effect.due_date = arrow.get(data.get('due_date')).datetime if data.get('due_date') else None
        effect.achievement_status = GOAL_STATUS_MAP.get(data.get('achievement_status'))
        effect.priority = GOAL_PRIORITY_MAP.get(data.get('priority'))
        effect.progress = data.get('progress')
        return effect

    def _carry_forward_goal_as_update_goal(self, effect, data, command=None):
        """Carry forward goal command data as update goal command data"""
        anchor_object = command.anchor_object if command else None
        effect.goal_id = str(anchor_object.id) if anchor_object else None
        effect = self._carry_forward_update_goal(effect, data, command=command)
        return effect

    def _carry_forward_follow_up(self, effect, data, command=None):
        """Carry forward follow up command data"""
        if coding := data.get('coding'):
            effect.structured = True
            effect.reason_for_visit = str(ReasonForVisitSettingCoding.objects.filter(code=coding['value']).order_by('id').last().id)
        else:
            effect.structured = False
            effect.reason_for_visit = data.get('reason_for_visit')
        effect.requested_date = arrow.get(data['requested_date']['date']).date() if data.get('requested_date') else None
        effect.note_type_id = str(NoteType.objects.filter(dbid=data['note_type']['value']).first().id) if data.get('note_type') else None
        effect.comment = data.get('comment') or ''
        return effect

    def _carry_forward_instruct(self, effect, data, command=None):
        """Carry forward instruct command data"""

        if instruct := data.get('instruct'):
            coding = instruct['extra']['coding'][0]
            if coding['system'] == CodeSystems.SNOMED:
                effect.coding = Coding(
                    system=coding['system'],
                    code=str(coding['code']),
                    display=coding['display'],
                )
            elif coding['system'] == CodeSystems.UNSTRUCTURED:
                effect.coding = Coding(
                    system=coding['system'],
                    code=coding['display'],
                )

        effect.comment = data.get('narrative')
        return effect

    def _carry_forward_imaging_order(self, effect, data, command=None):
        """Carry forward imaging order command data"""

        priority_map = {
            "Routine": ImagingOrderCommand.Priority.ROUTINE,
            "Urgent": ImagingOrderCommand.Priority.URGENT,
        }
        
        # Extract CPT code from image text like 'CT, abdomen and pelvis; w/o contrast (CPT: 74176)'
        image_data = data.get('image', {}).get('value')
        # Extract CPT code using regex pattern (CPT: 74176) or (CPT:74176)
        cpt_match = re.search(r'\(CPT:\s*(\d+)\)', image_data, re.IGNORECASE)
        effect.image_code = cpt_match.group(1) if cpt_match else None
        
        effect.diagnosis_codes = [i['value'] for i in (data['indications'] or [])] if data.get('indications') else []
        effect.priority = priority_map.get(data.get('priority'))
        effect.additional_details = data.get('additional_details')

        if imaging_center := data.get('imaging_center'):
            details = imaging_center['extra']['contact']
            effect.service_provider = ServiceProvider(
                first_name=details['firstName'] or "",
                last_name=details['lastName'] or "",
                practice_name=details['practiceName'] or "",
                specialty=details['specialty'] or "",
                business_address=details['businessAddress'] or "",
                business_phone=details['businessPhone'] or "",
                business_fax=details['businessFax'] or "",
                notes=details['notes'] or "",
            )
 
        effect.comment = data.get('comment')
        effect.ordering_provider_key = str(Staff.objects.filter(dbid=data['ordering_provider']['value']).first().id) if data.get('ordering_provider') else None
        effect.linked_items_urns = [str(i['value']) for i in (data['linked_items'] or [])] if data.get('linked_items') else []
        return effect

    def _carry_forward_lab_order(self, effect, data, command=None):
        """Carry forward lab order command data"""
        effect.lab_partner = data['lab_partner']['value'] if data.get('lab_partner') else None
        effect.tests_order_codes = [i['value'] for i in (data['tests'] or [])]
        effect.ordering_provider_key = str(Staff.objects.filter(dbid=data['ordering_provider']['value']).first().id) if data.get('ordering_provider') else None
        effect.diagnosis_codes = [i['value'] for i in (data['diagnosis'] or [])] if data.get('diagnosis') else []
        effect.fasting_required = data.get('fasting_status') is True
        effect.comment = data.get('comment') or ""
        return effect

    def _carry_forward_refer(self, effect, data, command=None):
        """Carry forward refer command data"""

        priority_map = {
            "Routine": ReferCommand.Priority.ROUTINE,
            "Urgent": ReferCommand.Priority.URGENT,
        }

        clinical_question_map = {
            "Cognitive Assistance (Advice/Guidance)": ReferCommand.ClinicalQuestion.COGNITIVE_ASSISTANCE,
            "Assistance with Ongoing Management": ReferCommand.ClinicalQuestion.ASSISTANCE_WITH_ONGOING_MANAGEMENT,
            "Specialized intervention": ReferCommand.ClinicalQuestion.SPECIALIZED_INTERVENTION,
            "Diagnostic Uncertainty": ReferCommand.ClinicalQuestion.DIAGNOSTIC_UNCERTAINTY,
        }

        if service_provider := data.get('refer_to'):
            details = service_provider['extra']['contact']
            effect.service_provider = ServiceProvider(
                    first_name=details['firstName'] or "",
                    last_name=details['lastName'] or "",
                    practice_name=details['practiceName'] or "",
                    specialty=details['specialty'] or "",
                    business_address=details['businessAddress'] or "",
                    business_phone=details['businessPhone'] or "",
                    business_fax=details['businessFax'] or "",
                    notes=details['notes'] or "",
                )
        effect.diagnosis_codes = [i['value'] for i in (data['indications'] or [])] if data.get('indications') else []
        effect.clinical_question = clinical_question_map.get(data.get('clinical_question'))
        effect.priority = priority_map.get(data.get('priority'))
        effect.notes_to_specialist = data.get('notes_to_specialist')
        effect.include_visit_note = data.get('include_visit_note') is True
        effect.comment = data.get('internal_comment') or ""
        effect.linked_items_urns = [str(i['value']) for i in (data['linked_items'] or [])] if data.get('linked_items') else []
        return effect

    def _carry_forward_prescribe(self, effect, data, command=None):
        """Carry forward prescribe command data"""
        effect.fdb_code = str(data.get('prescribe', {}).get('value'))
        effect.icd10_codes = [
            ConditionCoding.objects.filter(condition_id=i['value'], system=CodeSystems.ICD10).first().code 
            for i in (data['indications'] or [])
        ]
        effect.sig = data.get('sig')
        effect.days_supply = data.get('days_supply')
        effect.quantity_to_dispense = float(data['quantity_to_dispense']) if data.get('quantity_to_dispense') else None
        effect.type_to_dispense = ClinicalQuantity(
            representative_ndc=data['type_to_dispense']['extra']['representative_ndc'],
            ncpdp_quantity_qualifier_code=data['type_to_dispense']['extra']['erx_ncpdp_script_quantity_qualifier_code']
        ) if data.get('type_to_dispense') else None
        effect.refills = data.get('refills')
        effect.substitutions = PrescribeCommand.Substitutions.ALLOWED if data.get('substitutions') == 'allowed' else PrescribeCommand.Substitutions.NOT_ALLOWED
        effect.pharmacy = data['pharmacy']['value'] if data.get('pharmacy') else None
        effect.prescriber_id = str(Staff.objects.filter(dbid=data['prescriber']['value']).first().id) if data.get('prescriber') else None
        effect.supervising_provider_id = str(Staff.objects.filter(dbid=data['supervising_provider']['value']).first().id) if data.get('supervising_provider') else None
        effect.note_to_pharmacist = data.get('note_to_pharmacist')
        return effect

    def _carry_forward_refill(self, effect, data, command=None):
        """Carry forward refill command data"""
        effect = self._carry_forward_prescribe(effect, data)  
        effect.fdb_code = str(MedicationCoding.objects.filter(medication_id=data['prescribe']['value']).first().code) if data.get('prescribe') else None
        return effect

    def _carry_forward_prescribe_as_refill(self, effect, data, command=None):
        """Carry forward prescribe command data as refill command data"""
        return self._carry_forward_prescribe(effect, data)

    def _carry_forward_adjust_prescription_as_refill(self, effect, data, command=None):
        """Carry forward adjust prescription command data as refill command data"""
        effect = self._carry_forward_prescribe(effect, data)
        effect.fdb_code = str(data['change_medication_to']['value']) if data['change_medication_to'] else None
        return effect

    def _carry_forward_change_medication_as_refill(self, effect, data, command=None):
        """Carry forward change medication command data as refill command data"""
        
        medication_id = data['medication']['value'] if data['medication'] else None
        if medication_id:
            fdb_code = str(MedicationCoding.objects.filter(medication_id=medication_id).first().code)

            # find out if the medication came from a adjust prescription, refill, or prescribe command
            adjust_prescription_command = Command.objects.filter(schema_key='adjustPrescription', patient=self.note.patient, data__change_medication_to__value=int(fdb_code)).order_by('modified').last()
            refill_command = Command.objects.filter(schema_key='refill', patient=self.note.patient, data__prescribe__value=medication_id).order_by('modified').last()
            prescribe_command = Command.objects.filter(schema_key='prescribe', patient=self.note.patient, data__prescribe__value=int(fdb_code)).order_by('modified').last()
            
            # Get whichever command has the latest modified date
            commands = [cmd for cmd in [adjust_prescription_command, refill_command, prescribe_command] if cmd is not None]
            log.info(f"Commands: {commands}")
            last_command = max(commands, key=lambda cmd: cmd.modified) if commands else None
            log.info(f"Last command: {last_command}")
            if last_command:
                if last_command.schema_key == 'adjustPrescription':
                    effect = self._carry_forward_adjust_prescription_as_refill(effect, last_command.data)
                elif last_command.schema_key == 'refill':
                    effect = self._carry_forward_refill(effect, last_command.data)
                elif last_command.schema_key == 'prescribe':
                    effect = self._carry_forward_prescribe_as_refill(effect, last_command.data)

        effect.sig = data.get('sig')
        return effect

    def _carry_forward_task(self, effect, data, command=None):
        """Carry forward task command data"""
        task_assigner_map = {
            "assignee": AssigneeType.STAFF,
            "team": AssigneeType.TEAM,
            "unassigned": AssigneeType.UNASSIGNED,
            "role": AssigneeType.ROLE,
        }
        effect.title = data.get('title') or ""
        if assign_to := data.get('assign_to'):
            type_and_id = assign_to['value'].split('-')
            assign_to_kwargs = {
                'to': task_assigner_map.get(type_and_id[0]),
            }
            if len(type_and_id) > 1:
                assign_to_kwargs['id'] = int(type_and_id[1])
            effect.assign_to = TaskAssigner(**assign_to_kwargs)
        effect.due_date = arrow.get(data.get('due_date')).date() if data.get('due_date') else None
        effect.comment = data.get('comment') or ""
        effect.labels = [i['text'] for i in (data['labels'] or [])] if data.get('labels') else []
        effect.linked_items_urns = [str(i['value']) for i in (data['linked_items'] or [])] if data.get('linked_items') else []
        return effect
    
    def handle(self) -> list[Effect]:
        """
            Function is kicked of when the button in the note is clicked. 

            It will insert empty commands of:
                Reason For Visit
                History of Present Illness
                Review of Systems
                Physical Exam
                Diagnose
                Plan
        """

        note_id = self.event.context['note_id']
        self.note = Note.objects.get(dbid=note_id)
        note_uuid = str(self.note.id)
        previous_note = self.find_previous_note(self.note)

        log.info(f"Carry Forward Action Button has been clicked in note {note_id},"
                 f" finding commands to carry forward from note {previous_note.dbid}")

        schema_map = {
            AssessCommand.Meta.key: (AssessCommand, self._carry_forward_assess, False),
            FollowUpCommand.Meta.key: (FollowUpCommand, self._carry_forward_follow_up, False),
            HistoryOfPresentIllnessCommand.Meta.key: (HistoryOfPresentIllnessCommand, self._carry_forward_hpi, False),
            ImagingOrderCommand.Meta.key: (ImagingOrderCommand, self._carry_forward_imaging_order, False),
            InstructCommand.Meta.key: (InstructCommand, self._carry_forward_instruct, False),
            PerformCommand.Meta.key: (PerformCommand, self._carry_forward_perform, False),
            PlanCommand.Meta.key: (PlanCommand, self._carry_forward_plan, False),
            QuestionnaireCommand.Meta.key: (QuestionnaireCommand, self._carry_forward_questionnaire_ros_sa_exam, True),
            ReviewOfSystemsCommand.Meta.key: (ReviewOfSystemsCommand, self._carry_forward_questionnaire_ros_sa_exam, True),
            StructuredAssessmentCommand.Meta.key: (StructuredAssessmentCommand, self._carry_forward_questionnaire_ros_sa_exam, True),
            PhysicalExamCommand.Meta.key: (PhysicalExamCommand, self._carry_forward_questionnaire_ros_sa_exam, True),
            ReasonForVisitCommand.Meta.key: (ReasonForVisitCommand, self._carry_forward_reason_for_visit, False),
            UpdateGoalCommand.Meta.key: (UpdateGoalCommand, self._carry_forward_update_goal, False),
            VitalsCommand.Meta.key: (VitalsCommand, self._carry_forward_vitals, False),
            RefillCommand.Meta.key: (RefillCommand, self._carry_forward_refill, False),
            LabOrderCommand.Meta.key: (LabOrderCommand, self._carry_forward_lab_order, False),
            ReferCommand.Meta.key: (ReferCommand, self._carry_forward_refer, False),
            TaskCommand.Meta.key: (TaskCommand, self._carry_forward_task, False),


            # These are commands that we identified as smart carry forward commands
            # For example: If a previous note diagnosed a conditions, we actually want to assess it this time
            DiagnoseCommand.Meta.key: (AssessCommand, self._carry_forward_diagnose_to_assess, False),
            UpdateDiagnosisCommand.Meta.key: (AssessCommand, self._carry_forward_update_diagnosis_to_assess, False),
            # If a previous note did medication related commands, we probably just want to refill the medication
            AdjustPrescriptionCommand.Meta.key: (RefillCommand, self._carry_forward_adjust_prescription_as_refill, False),
            ChangeMedicationCommand.Meta.key: (RefillCommand, self._carry_forward_change_medication_as_refill, False),
            PrescribeCommand.Meta.key: (RefillCommand, self._carry_forward_prescribe_as_refill, False),
            # If a previous note had a goal, we probably just want to update it this time
            GoalCommand.Meta.key: (UpdateGoalCommand, self._carry_forward_goal_as_update_goal, False),



            # These are commented out commmands that we believe wouldn't need to be carried forward
            # but if you want to build them out, uncomment them and create the handler functions
            # MedicalHistoryCommand.Meta.key: (MedicalHistoryCommand, None, False),
            # RefillCommand.Meta.key: (RefillCommand, None, False),
            # CloseGoalCommand.Meta.key: (CloseGoalCommand, None, False),
            # AllergyCommand.Meta.key: (AllergyCommand, None, False),
            # FamilyHistoryCommand.Meta.key: (FamilyHistoryCommand, None, False),
            # RemoveAllergyCommand.Meta.key: (RemoveAllergyCommand, None, False),
            # ImmunizationStatementCommand.Meta.key: (ImmunizationStatementCommand, None, False),
            # ResolveConditionCommand.Meta.key: (ResolveConditionCommand, None, False),
            # StopMedicationCommand.Meta.key: (StopMedicationCommand, None, False),
            # SurgicalHistoryCommand.Meta.key: (SurgicalHistoryCommand, None, False),
            # ConsultReportReviewCommand.Meta.key: (ConsultReportReviewCommand, None, False),
            # UncategorizedDocumentReviewCommand.Meta.key: (UncategorizedDocumentReviewCommand, None, False),
            # ImagingReviewCommand.Meta.key: (ImagingReviewCommand, None, False),
            # LabReviewCommand.Meta.key: (LabReviewCommand, None, False),

        }

        originating_effects = []
        editing_effects = []
        for command in Command.objects.filter(
                note=previous_note,
                committer__isnull=False,
                entered_in_error__isnull=True
            ).order_by('created'):
            log.info(f'Found {command.schema_key} to carry forward')

            schema_config = schema_map.get(command.schema_key)
            if schema_config:
                CommandModel, handler, should_edit = schema_config
                effect = CommandModel(
                    note_uuid=note_uuid,
                ) 
                data = command.data

                try:
                    effect = handler(effect, data, command)
                except Exception as e:
                    log.error(f"Error carrying forward {command.schema_key} {command.id}: {e}")
                    continue

                if should_edit:
                    effect.command_uuid = str(uuid.uuid4())
                    editing_effects.append(effect.edit())

                originating_effects.append(effect)
                log.info(f"Originating command with {effect.__dict__}")

        if not originating_effects:
            log.warning(f"No commands to carry forward found for note {note_id}")
            return []
        
        return [BatchOriginateCommandEffect(commands=originating_effects).apply()] + editing_effects
