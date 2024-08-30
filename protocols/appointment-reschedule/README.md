### Target Population
Patients who have an open task labeled `Appointment Reschedule`

### How to Satisfy
- **Patient Reached:** A response in the **Phone Call Disposition Questionnaire** indicates that the patient was successfully reached (PhoneResponses.REACHED).
- **Sufficient Attempts:** There have been at least two phone call attempts recorded in the **Phone Call Disposition Questionnaire** where the responses indicate no answer but either a message was left or no message was left (PhoneResponses.NO_ANSWER_MESSAGE or PhoneResponses.NO_ANSWER_NO_MESSAGE).
- **Task Updates:** The protocol will be satisfied if the task is marked as `done` or `complete`, or if the label is removed. 

### Importance
This protocol helps streamline the process of managing appointment rescheduling, ensuring that patients who need to reschedule are contacted appropriately. It reduces the risk of missed appointments and improves patient engagement by ensuring follow-ups are conducted based on the response status.
