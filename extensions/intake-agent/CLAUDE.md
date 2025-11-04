Read ../../coding_agent_context.txt to get up to speed on the Canvas SDK, a Python SDK for developing plogins for the Canvas EMR. It is going to be the main package you use.

Update the plugin_version attribute in the CANVAS_MANIFEST.json file every time you make a change.

Every time you update the manifest file in a material way (other than simply updating the plugin_version attribute) you need to run `uv run canvas validate-manifest`.

Do not use any imports that are not allowed. The allowed imports are described here: https://raw.githubusercontent.com/canvas-medical/canvas-plugins/refs/heads/main/plugin_runner/sandbox.py. Read that file and familiarize yourself with what's allowed — the plugin environment is sandboxed for security, and there are many restrictions you must abide by.

There should be no more than one class defined per file.

When you are instructed to write tests, be sure that you follow the exact same directory structure as the code under test. The test file names should be identical to the name of the file under test, but prefixed with `test_`.

Use mocks to keep tests isolated. Always check mock calls as part of the test assertions.