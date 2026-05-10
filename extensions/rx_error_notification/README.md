# rx-error-notification

Automatically creates a task for the prescriber when a prescription returns an error status, ensuring providers are immediately aware of prescription failures.

## How It Works

- **Event:** Listens for `PRESCRIPTION_ERRORED` events
- **Action:** Creates an `AddTask` assigned to the prescribing provider with an `AddTaskComment` containing prescription details

## Task Format

- **Title:** `RX ERROR {Patient Name} - {Medication Name}`
- **Due:** Immediately
- **Label:** `RX-ERROR`
- **Comment:** Medication name, sig, dose/dispense quantities, refills, pharmacy, and error message

## Configuration

No secrets or configuration required. The plugin works automatically once installed and enabled.

## Data Access

- **Read:** Prescription, Patient, Staff, Medication

## Installation

```bash
canvas install rx_error_notification
```

## Running Tests

```bash
uv run pytest tests/
```
