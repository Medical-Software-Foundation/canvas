# Experimental Claim Coding Agent

## What it does

This plugin watches Perform commands in a note and adds billing line items for the encounter as they are entered. It sets the charge (CPT or internal code), links the diagnosis codes already on the note, sets units, and applies modifiers, using LLM inference to inform the coding. It is intended to be chained with Hyperscribe so charges build up alongside the documentation.

## Problem it solves

Coding a claim by hand after a visit is slow and easy to get wrong: someone has to read the note, match charges to the diagnoses, pick units, and add modifiers, often well after the encounter when context has faded. This plugin moves that work into the visit itself, drafting the billing line items as commands are performed so the claim is closer to complete by the time the note is done.

## Who it's for

Billing and coding staff, and the prescribers and clinicians who document encounters in Canvas, at practices that want claim coding drafted in real time rather than reconciled later. It is an experimental example, best suited to teams piloting LLM-assisted coding alongside Hyperscribe.

## How to install

```
canvas install claim_coding_agent
```

This plugin requires the `OPENAI_SECRET_KEY` secret to be set before it will function. See Configuration options.

## Configuration options

| Secret | Description |
|---|---|
| `OPENAI_SECRET_KEY` | OpenAI API key used for the LLM inference that informs claim coding. Required. |

## Description
Uses the new billing line item effects along with LLM inference to manage billing line items for an encounter, intended for chaining with Hyperscribe. It manages:
- Charges (CPT or internal codes)
- Diagnosis codes (linked to charge codes)
- Units
- Modifiers

## Limitations
The master fee schedule for a practice is not yet available programmatically.
