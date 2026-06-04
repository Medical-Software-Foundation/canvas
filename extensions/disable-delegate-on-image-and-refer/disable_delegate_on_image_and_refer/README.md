# disable_delegate_on_image_and_refer

A Canvas SDK plugin that disables the **Delegate** action on the **Image** (Imaging Order) and **Refer** commands, leaving **Sign** as the only available action.

## Why

Some practices want their providers to take personal responsibility for every imaging order and referral they place — no handing the order off to another staff member to sign. By default the Image and Refer commands offer both a **Sign** and a **Delegate** action. This plugin disables Delegate so the only way to complete the command is to Sign it.

## What it does

When a clinician opens an Image or Refer command, the platform asks plugins which actions should be available. This plugin returns the action list with **Delegate** stripped out, so the command UI shows only **Sign**. Every other action the platform offers (e.g. enter-in-error) is passed through untouched.

The change is purely UI/affordance level — it does not alter the command schema, permissions, or any stored data, and it is fully reversible by disabling the plugin.

## How it works

Two `BaseHandler` subclasses, both registered in `CANVAS_MANIFEST.json`:

### `DisableImagingOrderDelegate`

Subscribes to `EventType.IMAGING_ORDER_COMMAND__AVAILABLE_ACTIONS`. On each event it reads the platform-supplied action list from `self.event.context["actions"]`, drops any action whose `name` is `delegate_action`, and returns a single `Effect(type=EffectType.COMMAND_AVAILABLE_ACTIONS_RESULTS, ...)` carrying the filtered list as JSON.

### `DisableReferDelegate`

Identical logic, subscribed to `EventType.REFER_COMMAND__AVAILABLE_ACTIONS` for the Refer command.

Both handlers delegate to a shared pure helper, `actions_without_delegate`, which makes the filtering trivial to unit-test in isolation.

## Project layout

```
disable-delegate-on-image-and-refer/            # extension root
├── pyproject.toml
├── mypy.ini
├── tests/
│   └── test_disable_delegate_actions.py
└── disable_delegate_on_image_and_refer/        # plugin package
    ├── CANVAS_MANIFEST.json
    ├── README.md
    ├── __init__.py
    └── handlers/
        ├── __init__.py
        └── disable_delegate_actions.py         # both handlers live here
```

## Installation

Install the plugin onto a Canvas instance using the Canvas CLI:

```bash
uv run canvas install --host <your-instance> disable_delegate_on_image_and_refer
```

`<your-instance>` is the section header from your `~/.canvas/credentials.ini`. The CLI reuploads on subsequent runs and the platform hot-reloads the plugin.

## Configuration

None. The plugin declares no secrets, no environment variables, and no scope — it consumes only the platform-supplied event context and returns a filtered action list.

## Development

```bash
# install dev dependencies
uv sync

# run tests with coverage
uv run pytest --cov=disable_delegate_on_image_and_refer --cov-report=term-missing --cov-branch

# type-check
uv run mypy --config-file=mypy.ini disable_delegate_on_image_and_refer tests
```

## References

- [Command Available Actions Effect](https://docs.canvasmedical.com/sdk/effect-command-available-actions/)
- [Canvas SDK overview](https://docs.canvasmedical.com/sdk/)
