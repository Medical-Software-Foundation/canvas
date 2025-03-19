# Experimental Claim Coding Agent

## Description
Uses the new billing line item effects along with LLM inference to manage billing line items for an encounter, intended for chaining with Hyperscribe. It manages:
- Charges (CPT or internal codes)
- Diagnosis codes (linked to charge codes)
- Units
- Modifiers

## Limitations
The master fee schedule for a practice is not yet available programmatically.
