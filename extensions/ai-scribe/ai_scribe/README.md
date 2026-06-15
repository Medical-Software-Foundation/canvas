# AI Scribe Plugin

## What it does

When an AI medical scribe's transcript is pasted into a note through a Clipboard command, this plugin reads that text, breaks it into structured clinical entries, and turns each one into a Canvas command placed in the note. The clinician gets draft commands to review instead of a wall of text.

## Problem it solves

AI scribes produce a block of narrative text, and someone still has to read it and hand-enter each diagnosis, medication, and plan item as a discrete chart command. That manual transcription is slow and error-prone. This plugin does the parsing and command creation automatically when the transcript lands in the note.

## Who it's for

Prescribers and clinicians who dictate visits through an AI scribe and want the output converted into reviewable Canvas commands rather than copying entries by hand.

## How to install

```
canvas install ai_scribe
```

## Configuration options

No configuration required.

## Description

This plugin is used to interpret the output of an AI medical scribe.

### Important Note!

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it
gets updated if you add, remove, or rename protocols.
