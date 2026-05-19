# Tied to plugin_version: bump alongside CANVAS_MANIFEST.json plugin_version.
# Deterministic per release so browsers always refetch static assets and the
# modal HTML after a deploy, regardless of how Canvas's plugin-reload path
# handles Python module re-import.
CACHE_BUST = "0.1.14"
