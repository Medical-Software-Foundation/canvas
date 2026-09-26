# Medication Follow Up Protocol

A practice defines a medication class as a list of timed steps. A provider enrols a
patient onto one class from the note. A daily scheduled walk runs whatever is due.

## What it adds

- A configuration page in the left sidebar, where a practice builds its medication
  classes and the steps inside them.
- A panel on the patient chart, beside the other panel buttons, showing every
  programme that patient is on, every step, its due date and its status.
- A control in the note header that enrols a patient onto a class in one action, shown only when a committed prescription on that note matches a class.
- A questionnaire offered in the patient portal when a questionnaire step is live.

A step is a day offset, one of three kinds, its content, and optionally a condition.
The three kinds are a message to the patient, a questionnaire in the portal, and a
task for a team or a named person. The one condition is whether the recheck
appointment is still unbooked, and it is evaluated on the morning the step is due
rather than remembered from when the programme started.

## What an enrolment copies and what it reads live

An enrolment copies the timing and the shape of every step at the moment it is
created, and it reads the content of a step live. So correcting the wording of a
step reaches every patient already running on that class, while reordering the steps
or moving a day offset applies to the next patient enrolled and never moves under
somebody part way through. The two edits look like one edit on the same screen and
they behave differently on purpose.

## Secrets

| Secret | What it is for |
|---|---|
| `namespace_read_access_key` | Reads against this plugin's custom data namespace |
| `namespace_read_write_access_key` | Writes against the same namespace |

Both are system owned. Canvas generates them when the namespace is first created.

## The namespace key trap, read this before uninstalling

Canvas generates the two keys above exactly once, when the namespace is created, and
never regenerates them while the namespace still exists. Uninstalling the plugin
deletes its secrets, including both keys, and leaves the namespace and all of its
data in place, which is deliberate so that an uninstall never destroys clinical data.

The consequence is a silent failure on reinstall. The namespace is already there, so
the keys are not regenerated, setting the secrets again reports success with values
that do not match the originals, and the plugin then raises a namespace access error
the first time it touches its own data.

Save both key values somewhere outside the instance before any uninstall, and restore
exactly the same values afterwards. Removing a key from the manifest does not delete
its stored value, only an uninstall does that.

---

*This plugin was developed by [Vicert](https://vicert.com).*
Contact: engineering@vicert.com
