# Default Pharmacy
================

## Description

Streamline prescribing by automatically updating a patient's default preferred pharmacy directly from the `Prescribe`, `Refill`, and `Adjust Prescription` commands.

**How it works:**
1. When a patient has a [default preferred pharmacy set](https://canvas-medical.help.usepylon.com/articles/8802451810-patient-demographics#preferred-pharmacies-18), this pharmacy will pre-populated in prescribing workflows.
2. If a provider changes the pharmacy for one of the prescribing workflows, the new pharmacy will automatically be saved as the default preferred pharmacy to the patient profile.
3. The next time a provider prescribes for the patient, the new pharmacy will pre-propulate.

By automatically updating the default preferred pharmacy directly in the Prescribe/Refill/Adjust command, users will no longer need to update this value in the patient profile.


### Important Note

The `prescribe`, `refill` and `adjustPrescription` command switches must be on for this protocol.
