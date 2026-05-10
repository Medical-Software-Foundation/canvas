PLUGIN_NAME = "patient_tags"

BANNER_KEY_PREFIX = "custom-patient-tag-group-"
BANNER_NARRATIVE_MAX_CHARS = 90

# Legacy per-label banner keys from a pre-bannergroup version of this plugin.
# Listed here so compute_banner_effects can emit RemoveBannerAlert for them on
# every reconcile pass — without this, instances upgraded from the legacy
# schema keep stale banners attached to patients forever, since the current
# code path only knows about BANNER_KEY_PREFIX-prefixed keys.
LEGACY_BANNER_KEYS = [
    "do-not-contact",
    "do-not-schedule",
    "no-marketing",
    "banned",
    "treatment-contact",
]

DESCRIPTION_MAX_CHARS = 500

DEFAULT_SEPARATOR = " • "

RULE_ACTION_AUTO_ASSIGN = "auto_assign"
RULE_ACTION_AUTO_REMOVE = "auto_remove"
VALID_RULE_ACTIONS = [RULE_ACTION_AUTO_ASSIGN, RULE_ACTION_AUTO_REMOVE]

VALID_INTENTS = ["info", "warning", "alert"]
VALID_PLACEMENTS = [
    "CHART",
    "TIMELINE",
    "APPOINTMENT_CARD",
    "SCHEDULING_CARD",
    "PROFILE",
]

# Palette: each entry is keyed by name. `border` is the saturated chip border / unselected
# accent; `fill` is the translucent fill used when a pill is selected; `text` is the
# foreground color for legibility against the fill.
PALETTE = {
    "red":    {"border": "#E53935", "fill": "rgba(229, 57, 53, 0.22)",  "text": "#7F1D1D"},
    "orange": {"border": "#F57C00", "fill": "rgba(245, 124, 0, 0.22)",  "text": "#7C2D12"},
    "yellow": {"border": "#F9A825", "fill": "rgba(249, 168, 37, 0.28)", "text": "#713F12"},
    "green":  {"border": "#2E7D32", "fill": "rgba(46, 125, 50, 0.22)",  "text": "#14532D"},
    "blue":   {"border": "#1976D2", "fill": "rgba(25, 118, 210, 0.22)", "text": "#1E3A8A"},
    "pink":   {"border": "#EC407A", "fill": "rgba(236, 64, 122, 0.22)", "text": "#831843"},
    "purple": {"border": "#7B1FA2", "fill": "rgba(123, 31, 162, 0.22)", "text": "#581C87"},
    "brown":  {"border": "#6D4C41", "fill": "rgba(109, 76, 65, 0.22)",  "text": "#44322B"},
    "black":  {"border": "#212121", "fill": "rgba(33, 33, 33, 0.18)",   "text": "#111827"},
    "white":  {"border": "#9CA3AF", "fill": "rgba(255, 255, 255, 0.85)", "text": "#1F2937"},
}

DEFAULT_COLOR = "blue"
