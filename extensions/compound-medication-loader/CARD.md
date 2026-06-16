# Compound Medication Loader

Load your entire compound-medication formulary into Canvas from a single CSV, instead of adding each preparation one at a time.

## The problem

Adding compound medications through the Prescribe command one entry at a time is slow. A practice with a real compound formulary - hormone creams, magic mouthwashes, custom topical preparations - can have dozens or hundreds of entries, and re-doing that work by hand invites duplicates and mistakes.

## What it does

Gives staff two ways to load compound medications in bulk:

- **Upload page** - drag in a CSV, review the parsed rows with errors and duplicates flagged before you commit, then load them all at once.
- **Programmatic endpoint** - load from a script using a per-instance access token, for one-off migrations or syncing from another source.

Both paths validate every row, flag anything already in Canvas, and let you safely re-run the load without creating duplicates.

## Who it's for

Clinical and admin staff at practices that maintain a compound formulary - functional-medicine clinics, pain management, ketamine and psychedelic-medicine clinics, dermatology, or anywhere providers prescribe practice-specific custom compounds at scale.

## Good to know

- Duplicate detection runs before you load, so you see what already exists up front.
- Re-running a load is safe - existing entries are skipped by default.
- The programmatic endpoint stays disabled until you set an access token, so nothing is exposed by default.
