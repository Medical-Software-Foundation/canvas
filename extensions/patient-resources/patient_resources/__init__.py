"""Patient Resources: an admin-curated library of patient-facing resource links."""

# Appended to every page and static-asset URL this plugin serves. Pinned to
# plugin_version in CANVAS_MANIFEST.json rather than generated from a timestamp:
# a timestamp changes on every worker restart and busts caches that were fine.
CACHE_BUST = "0.3.5"
