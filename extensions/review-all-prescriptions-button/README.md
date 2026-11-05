Review All Prescriptions Button
===============================

## Description

Adds a **Review all prescriptions** button to the note header. One click puts every staged Prescribe command in the note into review. Refill and Adjust Prescription commands are not included: the SDK's review effect supports Prescribe only, so the prescriber reviews those as usual.

**Problem it solves:** a prescriber with many medications in one note has to move each order forward one at a time. This button does the review step for all of them at once.

**Who it's for:** practices where prescribers routinely write several new prescriptions in a single visit.

**What it does not do:** it never signs or sends a prescription. The prescriber still signs and sends each order in the note. The Canvas SDK has no sign effect for prescribing commands, so a plugin cannot sign them.

## Install

```bash
canvas install review-all-prescriptions-button/review_all_prescriptions_button --host <instance>
```

## Configuration

The button is **off by default**. To turn it on, set the plugin variable to `true`:

```bash
canvas config set review_all_prescriptions_button REVIEW_ALL_PRESCRIPTIONS_ENABLED=true --instance <instance>
```

Any other value (or no value) keeps the button hidden.

## How it works

- The button shows only when the variable is `true` and the note is not locked.
- On click, it finds the note's commands that are `staged`, not entered in error, and of type Prescribe. It returns one review effect per command.
- **Controlled substances:**
  - Compound medications are checked against their schedule. A compound with any schedule other than "None", or one whose record can't be found, is skipped and left for the prescriber.
  - FDB-coded (catalog) medications **cannot** be checked. The SDK exposes no DEA schedule for them on a staged command, so they are put into review like any other prescription. EPCS rules still apply when the prescriber signs and sends.

## Access

- Anyone who can open the note sees the button once it is turned on.
- It reads the note's commands, the note's lock state, and compound medication schedules. It writes nothing except the review effects for that note's own staged prescriptions.
- There are no API routes and no outside calls.

## Screenshot

Not yet captured.
