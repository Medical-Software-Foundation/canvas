# The Canvas plugin sandbox

Canvas runs plugin code under [RestrictedPython]. Several things that are
perfectly legal Python fail there — and the ones that cost the most time fail
**only at runtime on a real instance**. They pass `canvas validate`, they pass a
full unit-test suite, and then a route returns an empty 500 in production.

Each restriction below was found that way. If you are writing a Canvas plugin,
reading this will save you an afternoon.

[RestrictedPython]: https://restrictedpython.readthedocs.io/

## Where each one is caught

| Restriction | `canvas validate` | Unit tests | Runtime |
|---|---|---|---|
| Attribute access on your own modules | ✗ | ✗ | ✓ |
| Reverse managers on CustomModels | ✗ | ✗ | ✓ |
| `object` builtin | ✓ | ✗ | ✓ |

`canvas validate` proves handlers *import*. That is all. Two of these three
survive it.

---

## 1. No attribute access on your own plugin's modules

```python
# FAILS at runtime
from canvas_theme_kit import store
store.get_theme(slug)
# AttributeError: "canvas_theme_kit.store.get_theme" is an invalid attribute
#                 name (not in ALLOWED_MODULES)
```

```python
# Works
from canvas_theme_kit.store import get_theme
get_theme(slug)
```

Import the names, never the module. This applies to the standard library too, so
prefer `from json import dumps` over `import json` + `json.dumps`.

The symptom is an empty response body and a 500. The traceback naming the exact
line is in `canvas logs`.

**Guard:** `tests/test_sandbox_compatibility.py` AST-scans every source file and
fails on `from <package> import <submodule>` or `import <package>`. Copy it into
any Canvas plugin; it needs one constant changed.

## 2. No reverse related managers on CustomModels

```python
# FAILS at runtime
theme.revisions.filter(is_active=True)
# TypeError: 'NoneType' object is not callable
```

```python
# Works
ThemeRevision.objects.filter(theme=theme, is_active=True)
```

The reverse accessor resolves to `None` inside the sandbox, so the failure
surfaces as a confusing `TypeError` on the *next* call rather than an
`AttributeError` on the accessor.

Reverse accessors on **SDK** models are fine — `staff.roles.all()` works. It is
specifically your own CustomModels. Forward FK access (`revision.theme`) is also
fine; it is the reverse direction that breaks.

No structural guard for this one. Query through the model manager as a habit.

## 3. No `object` builtin

```python
# FAILS at import
_SENTINEL = object()
# NameError: name 'object' is not defined
```

```python
# Works
_SENTINEL = ...   # Ellipsis is a literal; no builtin lookup
```

This one `canvas validate` does catch, because it fails at import rather than at
call time. Assume other builtins are missing too and reach for literals.

## 4. No filesystem access

A handler cannot `open()` a file in its own package. Read packaged files through
the template engine instead:

```python
from canvas_sdk.templates import render_to_string
data = json.loads(render_to_string("static/default_tokens.json"))
```

Binary files have to be base64-encoded into text first, since `render_to_string`
returns `str`. That is how the reference design-system plugin ships webfonts.

## 5. Templates cannot cross the plugin boundary

`render_to_string` builds its engine as `Engine(dirs=[plugin_dir])` and raises
`PermissionError` on any path that escapes. A consuming plugin cannot
`{% extends %}` a template from another plugin.

Share CSS, data and HTTP endpoints. Not templates. `canvas-theme-kit/templates/base.html`
is a reference copy meant to be *copied into* a consumer, not extended across the
boundary.

---

## Why the tests do not catch these

The suites here mock the ORM. That is the right call — there is no database in
CI, and mocking keeps the tests fast and hermetic. But it means:

- No test resolves a real field name.
- No test runs under RestrictedPython.
- Coverage percentage says nothing about whether a query works.

This repo sits at 96% branch coverage on the publisher and **every one of the
bugs above shipped past it.** Treat coverage as a measure of logic, not of
correctness against the platform.

The practical workflow:

1. `canvas validate <plugin>` — catches import-time problems.
2. `canvas logs --host <instance>` — **start this before installing.**
3. Deploy, then exercise the actual route.
4. When something returns an empty body, go straight to the log. The traceback
   names the line.

## Debugging checklist

**Route returns an empty body or a 500**
Read `canvas logs`. Almost always restriction 1 or 2. The traceback is precise.

**Handler never runs**
Check the log for `Successfully loaded plugin "<name>" (N/N handlers loaded)`.
`canvas list` showing `enabled` does **not** mean it loaded — see
[operations.md](operations.md).

**Install seems to work but the plugin does not**
`canvas install` exits 0 even when the server-side install fails. Only the log
is truthful.

**Everything passes locally and fails on the instance**
That is this document. Work down the list.
