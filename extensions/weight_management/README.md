weight_management
=================

## Description

Streamline weight management workflows. 

Includes:

1. Protocol to display a banner on the patient's time line that displays:
	- patient’s highest weight before starting a GLP-1 (captured in a questionnaire, use the secret STARTING_WEIGHT_QUESTION_CODE to store the code value of the indivual question where this weight will be found) <br>
    - calculate the patient’s starting BMI with the weight from the questionnaire and the patient's first height recording in a vitals command. <br>
    - dynamically calculate and display the amount of weight loss from the starting weight from the questionnaire and the last updated weight records in a vitals command.

### Important Note!

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it
gets updated if you add, remove, or rename protocols.
