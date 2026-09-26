# Attendance Policy Tracker

Counts the visits a patient missed, cancelled too close to the appointment, or
moved so late that moving amounted to a cancellation. Attributes each one to the
patient or the clinic, and raises a task at a warning line and again at a
review line. It never discharges anybody.

## Where policy lives

Policy is stored by the plugin itself and edited from the Configuration tab on
the plugin's own screen. Every setting ships with a working default, so the
plugin runs a coherent policy from the moment it is installed and before anybody
opens that tab. Clearing a field returns it to its default rather than storing a
blank.

One setting is different. The list of staff who may open the Configuration tab
lives in Canvas administration as the `config_access_staff_ids` variable, and it
stays there because a plugin cannot write its own variables. That is the property
wanted here, since the list of people allowed to change policy should not be
editable from the screen it guards.

## Granting the first person access

The variable is empty on a fresh install, which means nobody can open the
Configuration tab yet. Granting access needs the staff key, a thirty two
character hexadecimal string, and not the integer shown beside a user in the
administration user list. Copying that integer is the common mistake and it fails
quietly, the tab simply never appears.

The plugin shows every member of staff their own key at the bottom of its screen
whether or not they have access, so the sequence is straightforward.

1. The person who needs access opens the plugin and reads the identifier printed
   at the bottom of the page.
2. An administrator pastes that value into `config_access_staff_ids` in Canvas
   administration. Several people are separated by whitespace, newlines, or
   commas, whichever is convenient.
3. That person reloads the plugin and the Configuration tab is there.

A refused attempt is logged with the key that was presented, so a wrong value is
discoverable rather than mysterious.

## Installing

    canvas install attendance_policy_tracker --host <host>

The plugin declares a `read_write` custom data namespace. On a first install
Canvas creates that namespace and stores its two access keys in the plugin's own
secrets automatically, so there is nothing to configure.

Reinstalling is where care is needed. Uninstalling deletes the plugin's secrets
while deliberately leaving the namespace and its data in place, and Canvas never
regenerates the keys for a namespace that already exists. The stored keys are
hashed, so a lost key cannot be recovered. Copy
`namespace_read_write_access_key` somewhere safe before uninstalling, and restore
the same value afterwards.

If the key is already lost, the namespace has to be dropped and recreated, which
destroys the stored policy.

    canvas namespace drop <namespace>

## The periodic sweep

A cron handler recomputes recently active patients every five minutes and raises
whichever tasks they have earned. The same computation is reachable on demand
from the screen, which is the only way to exercise it on an instance whose
scheduler is not running.

The sweep remembers when it last finished and asks only for what has changed
since, falling back to a full three hour lookback whenever that record is
missing or cannot be trusted. So a run costs the same whether it is the first
one after an install or the three hundredth of the day, and nothing is skipped
when a run fails.

## Limits you may see on a busy instance

Two ceilings exist so one screen cannot ask the instance for an unbounded amount
of work. The patient list returns at most three hundred people, ordered so the
highest counts arrive first, and the on demand recompute emits at most two
hundred actions in one response. In both cases the response says plainly that it
was truncated rather than looking complete, and the screen shows that. Nothing
is lost when the recompute truncates, because the five minute sweep is not
capped and issues whatever the on demand run left behind.

The three hundred is a limit on what the patient list returns, not on the work
it does to decide the order. Every patient whose visits moved in the last ninety
days is recomputed before the list is sorted and cut, because the highest counts
cannot be known without counting. That costs roughly four queries per such
patient, so a practice with a thousand of them pays about four thousand queries
on a load of that screen. Cutting before sorting would make it cheap and would
return an arbitrary three hundred people rather than the three hundred nearest a
line, which is the opposite of what the screen is for. If that cost becomes a
problem the honest fix is a narrower window rather than a smaller list.

## Info

*This plugin was developed and contributed by [Vicert](https://vicert.com).*
Contact: engineering@vicert.com
