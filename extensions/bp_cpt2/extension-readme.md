# Blood Pressure CPT-II and HCPCS Claim Coding Agent

## Overview

This AI agent automatically adds appropriate CPT and HCPCS billing codes based on blood pressure measurements recorded in Canvas. It responds to two types of events: when vitals are committed and when notes are locked.

## Functionality

### Billing Codes

The plugin determines which codes to add based on blood pressure values:

#### Systolic Measurement Codes
- 3074F: < 130 mm Hg
- 3075F: 130-139 mm Hg
- 3077F: >= 140 mm Hg

#### Diastolic Measurement Codes
- 3078F: < 80 mm Hg
- 3079F: 80-89 mm Hg
- 3080F: >= 90 mm Hg

#### Control Status Codes
- G8783: BP documented and controlled (< 140/90 mm Hg)
- G8784: BP documented but not controlled (>= 140/90 mm Hg)
- G8950: BP not documented, reason not given
- G8951: BP not documented, documented reason
- G8752: Most recent BP < 140/90 mm Hg

#### Treatment Plan Codes (Uncontrolled BP)
- G8753: Most recent BP >= 140/90 and treatment plan documented
- G8754: Most recent BP >= 140/90 and no treatment plan, reason not given
- G8755: Most recent BP >= 140/90 and no treatment plan, documented reason

## Example Note with Claim Coding

  <img width="1200" height="1428" alt="image" src="https://github.com/user-attachments/assets/f11d1a2e-8ce8-4493-a63d-51a2545edf12" />
