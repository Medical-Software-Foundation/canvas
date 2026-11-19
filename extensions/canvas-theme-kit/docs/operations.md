# Operations

Installing, deploying, and working out what actually happened when something
goes wrong.

## The most important thing on this page

**`canvas install` and `canvas list` both lie about success.**

- `canvas install` prints `uploaded!` and **exits 0** even when the server-side
  install then fails. The upload succeeded; the install did not.
- `canvas list` shows a plugin as **`enabled`** even when the plugin runner
  refused to load it. Canvas registers and enables the row separately from
  loading the code.

A plugin can sit in `canvas list` as `enabled@0.0.1` for hours having never run
once. That is exactly how a missing namespace key presents.

The only trustworthy confirmation is in the logs:

```
Successfully loaded plugin "<name>", version X (N/N handlers loaded)
```

and, for a plugin joining a shared namespace:

```
Plugin '<name>' authorized for namespace '<ns>' with '<access>' access
```

**Start the log stream before you install**, so the install's own output is
captured:

```bash
canvas logs --host <instance>
```

## First install

The publisher creates the namespace. Supply both keys yourself:

```bash
canvas install canvas_theme_kit --host <instance> \
  --secret namespace_read_access_key=$(uuidgen) \
  --secret namespace_read_write_access_key=$(uuidgen)
```

**Why not let Canvas generate them:** the only supported way to read a generated
key back is the Django admin page for the plugin
(`/admin/plugin_io/plugin/`). Plenty of operator accounts cannot see that model —
they get a PLUGIN_IO section containing only "Logs". At that point the read key
is unreachable and **no consumer plugin can ever be installed**, and the only way
out is dropping the namespace and losing the data.

Rules:

- Both keys must be supplied together, or Canvas silently ignores them and
  generates its own. The install still succeeds, which makes the mistake quiet.
- Only applies to the install that **creates** the namespace.
- Store them outside Canvas. Uninstalling a plugin deletes its secrets while the
  namespace survives, so an external copy is the only way to regain access.

Then grant access — nobody is authorized until you do:

```bash
# Discover the codes: GET /plugin-io/api/canvas_theme_kit/admin/roles
canvas config set canvas_theme_kit DS_EDITOR_ROLES=<code>,<code>
canvas config set canvas_theme_kit DS_PUBLISHER_ROLES=<code>
```

## Installing a consumer

```bash
canvas install canvas_theme_kit_demo --host <instance> \
  --secret namespace_read_access_key=<the publisher's read key>
```

Without the key the install fails server-side with:

```
PluginInstallationError: declares read access to namespace
'canvas_theme_kit__themes' but 'namespace_read_access_key' secret is not configured
```

The CLI will still say `uploaded!` and exit 0.

## Routine deploys

```bash
canvas logs --host <instance>          # first, in another terminal
# bump plugin_version in CANVAS_MANIFEST.json
canvas validate <package>
canvas install <package> --host <instance>
# then confirm in the log:  Successfully loaded plugin ... (N/N handlers loaded)
```

## Inspecting the namespace

```bash
canvas namespace list --host <instance>
canvas namespace inspect canvas_theme_kit__themes --host <instance>
```

`inspect` prints tables, columns and approximate row counts. Useful for
confirming a migration landed, and for seeing whether data exists at all when a
page renders with fallback styling.

## Recovering from a lost namespace key

If the read key is unreachable and no consumer can be installed, the only way out
is destructive:

```bash
canvas namespace drop <namespace> --host <instance>            # dry run first
canvas namespace drop <namespace> --host <instance> --execute  # prompts for the name
# then reinstall the publisher supplying both keys
```

**This deletes every theme and revision.** The dry run lists exactly what goes.
The `--execute` form prompts for the full namespace name; pipe it in if you are
running non-interactively.

Avoid needing this by supplying keys at first install.

## Windows notes

Two rough edges, neither a problem with the plugins:

**`canvas validate` crashes on its own output.** It prints Unicode check marks
that a cp1252 console cannot encode:

```
UnicodeEncodeError: 'charmap' codec can't encode character '✓'
```

Prefix Canvas CLI commands with `PYTHONIOENCODING=utf-8`.

**A spurious "handler not in manifest" warning.** `canvas install` may report:

```
Warning: Found handler classes that are not referenced in the CANVAS_MANIFEST.json:
  - my_plugin.handlers\my_handler:MyHandler
```

Note the backslash. The CLI builds the module path from a filesystem path and
compares it against the manifest's dotted path, so it never matches on Windows.
Its own next line contradicts it (`✓ ...handlers.my_handler:MyHandler`). Ignore
it.

**If `canvas.exe` stops working** with `uv trampoline failed to canonicalize
script path`, the uv tools directory was wiped. The managed Python goes with it,
so reinstall in this order:

```bash
uv python install 3.12 --force
uv tool install canvas --python 3.12 --force
```

## Debugging a render that looks wrong

**Page renders with fallback colors.** Hit `/demo/tokens` on the demo plugin (or
the equivalent in your consumer). It reports whether it is genuinely reading the
namespace, how many tokens it sees, and the exact inline block. That separates
three causes that look identical on screen: missing namespace key, nothing
published, or genuinely empty tokens.

**Editor shows "not authorized".** `DS_EDITOR_ROLES` is unset or does not match.
Check `/admin/roles` — it reports `your_roles`, `you_can_edit` and
`you_can_publish` for the calling user.

**Published a change and nothing happened.** Give it a minute: the consumer token
cache is 60s and the browser cache is 300s. Confirm the publish landed by
fetching `/assets/<slug>/core.css` directly.

**Rolled back and the preview did not change.** Correct behavior. Rollback
changes what is *published*; the preview shows your *draft*. Check the "Live now"
line under the preview, or use **Load** to pull the revision into the draft.

**Route returns an empty body.** Almost always a sandbox restriction. Read
`canvas logs`; the traceback names the line. See
[canvas-sandbox.md](canvas-sandbox.md).
