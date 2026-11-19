"""Shared CSS foundation for all visit-summaries templates.

Tokens from canvas-plugin-ui skill v2.0 with plugin-specific extensions.
"""

SHARED_CSS = """
/* canvas-plugin-ui tokens + plugin extensions */
:root {
  /* Colors */
  --color-text: rgba(0, 0, 0, 0.87);
  --color-text-active: rgba(0, 0, 0, 0.95);
  --color-text-muted: #767676;
  --color-primary: #22BA45;
  --color-secondary: #2185D0;
  --color-danger: #BD0B00;
  --color-warning: #ED4A0B;
  --color-accent-brown: #935330;
  --color-bg: #F5F5F5;
  --color-border: #E9E9E9;
  --color-surface: #FFFFFF;
  --color-error-bg: #fff6f6;
  --color-error-border: #e0b4b4;
  --color-error-text: #9f3a38;

  /* Typography */
  --font-family: lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-size-base: 16px;
  --font-size-label: .92857143em;
  --line-height-base: 1.4285em;
  --font-weight-bold: 700;

  /* Spacing (4px grid) */
  --space-mini: 4px;
  --space-tiny: 8px;
  --space-small: 12px;
  --space-medium: 16px;
  --space-large: 20px;
  --space-huge: 24px;

  /* Shape */
  --radius: .28571429rem;
  --border-width: 1px;
  --border-color: var(--color-border);

  /* Transitions */
  --transition-fast: 200ms;
  --transition-base: 250ms;

  /* Input and form element dimensions */
  --font-size-input: 1em;
  --line-height-label: 1em;
  --input-padding: .67857143em 1em;
  --input-line-height: 1.21428571em;
  --input-border: 1px solid rgba(34, 36, 38, 0.15);
  --input-focus-border: #85b7d9;
  --input-placeholder: rgba(191, 191, 191, 0.87);
  --input-focus-placeholder: rgba(115, 115, 115, 0.87);
  --input-transition: 0.1s ease;

  /* Button dimensions */
  --btn-padding: .67857143em 1.5em;
  --btn-padding-sm: .58928571em 1.125em;
  --btn-font-size: 1rem;
  --btn-font-size-sm: .92857143rem;
  --btn-padding-xs: .5em .85714286em;
  --btn-font-size-xs: .78571429rem;

  /* Table row state colors */
  --row-positive-bg: #fcfff5;
  --row-positive-text: #2c662d;
  --row-warning-bg: #fffaf3;
  --row-warning-text: #573a08;
  --row-negative-bg: #fff6f6;
  --row-negative-text: #9f3a38;
  --row-active-bg: #e0e0e0;
  --table-header-bg: #f9fafb;
  --table-border: rgba(34, 36, 38, 0.1);

  /* Checkbox dimensions */
  --checkbox-size: 15px;
  --checkbox-border: 1px solid #d4d4d5;
  --checkbox-radius: .21428571rem;
  --checkbox-hover-border: rgba(34, 36, 38, 0.35);
  --checkbox-focus-border: #96c8da;
  --checkbox-check-color: var(--color-text-active);
  --checkbox-label-offset: 1.85714em;

  /* Tab dimensions */
  --tab-padding: .85714286em 1.14285714em;
  --tab-font-size: 1em;
  --tab-line-height: 1em;
  --tab-color: var(--color-text);
  --tab-active-color: var(--color-text-active);
  --tab-active-weight: 700;
  --tab-border: 2px solid rgba(34, 36, 38, 0.15);
  --tab-active-border: 2px solid rgb(27, 28, 29);
  --tab-margin-bottom: var(--space-medium);
  --tab-badge-font-size: .71428571em;
  --tab-badge-padding: .21428571em .5625em;
  --tab-badge-color: #767676;
  --tab-badge-border: 1px solid #767676;
  --tab-badge-radius: .28571429rem;
  --tab-badge-margin-left: .71428571em;

  /* Radio dimensions */
  --radio-size: 13px;
  --radio-border: 1px solid #d4d4d5;
  --radio-hover-border: rgba(34, 36, 38, 0.35);
  --radio-focus-border: #96c8da;
  --radio-dot-color: var(--color-text);
  --radio-dot-scale: scale(.53846154);
  --radio-label-offset: 1.85714em;

  /* Dropdown dimensions */
  --dropdown-padding: .67857143em 2.1em .67857143em 1em;
  --dropdown-border: 1px solid rgba(34, 36, 38, 0.15);
  --dropdown-focus-border: #96c8da;
  --dropdown-shadow: 0 2px 3px 0 rgba(34, 36, 38, 0.15);
  --dropdown-arrow-right: 1em;
  --dropdown-arrow-color: rgba(0, 0, 0, 0.8);
  --dropdown-menu-max-height: 16.02857143em;
  --dropdown-item-padding: .78571429em 1.14285714em;
  --dropdown-item-separator: 1px solid #fafafa;
  --dropdown-item-hover-bg: rgba(0, 0, 0, 0.05);
  --dropdown-item-selected-bg: rgba(0, 0, 0, 0.05);
  --dropdown-item-selected-color: var(--color-text-active);

  /* Tooltip */
  --tooltip-bg: var(--color-surface);
  --tooltip-color: var(--color-text);
  --tooltip-border: 1px solid #d4d4d5;
  --tooltip-padding: .833em 1em;
  --tooltip-shadow: 0 2px 4px 0 rgba(34, 36, 38, 0.12), 0 2px 10px 0 rgba(34, 36, 38, 0.15);
  --tooltip-arrow-size: .71428571em;

  /* Divider */
  --divider-border: 1px solid rgba(34, 36, 38, 0.15);
  --divider-margin: 1rem 0;

  /* Skeleton loading */
  --skeleton-bg: #e9e9e9;
  --skeleton-shine: #f5f5f5;

  /* Accordion */
  --accordion-title-padding: 7px 0;
  --accordion-title-color: var(--color-text);
  --accordion-content-padding: 7px 0;
  --accordion-icon-size: 1.125em;
  --accordion-icon-transition: transform 0.1s ease;
  --accordion-styled-title-padding: .75em 1em;
  --accordion-styled-title-color: rgba(0, 0, 0, 0.4);
  --accordion-styled-title-active-color: var(--color-text);
  --accordion-styled-title-border: 1px solid rgba(34, 36, 38, 0.15);
  --accordion-styled-content-padding: .5em 1em 1.5em;
  --accordion-styled-shadow: 0 1px 2px 0 rgba(34, 36, 38, 0.15), 0 0 0 1px rgba(34, 36, 38, 0.15);

  /* Card */
  --card-bg: var(--color-surface);
  --card-shadow: 0 1px 3px 0 #d4d4d5, 0 0 0 1px #d4d4d5;
  --card-hover-shadow: 0 1px 3px 0 #bcbdbd, 0 0 0 1px #d4d4d5;
  --card-padding: var(--space-medium);

  /* Spinner */
  --spinner-size: 24px;

  /* Toggle dimensions */
  --toggle-width: 3.5rem;
  --toggle-height: 1.5rem;
  --toggle-thumb-size: 1.5rem;
  --toggle-checked-offset: 2.15rem;
  --toggle-track-inactive: #F4F4F4;
  --toggle-track-inactive-hover: #DEDEDE;
  --toggle-track-active: #0D71BC;
  --toggle-thumb-shadow: 0 1px 2px 0 rgba(34, 36, 38, 0.15), 0 0 0 1px rgba(34, 36, 38, 0.15) inset;

  /* Plugin extensions */
  --font-size-sm: .8125rem;
  --font-size-caps: .75rem;
  --font-size-badge: .6875rem;
  --font-size-badge-icon: .5625rem;
  --font-size-badge-sm: .625rem;
  --letter-spacing-caps: 0.04em;

  /* Callout semantic colors */
  --callout-caution-bg: #fdf6ec;
  --callout-caution-border: #f0d9a8;
  --callout-caution-text: #7a5c1f;
  --callout-alert-bg: #fdf0f0;
  --callout-alert-border: #f0c0c0;
  --callout-alert-text: #8b2020;
  --callout-info-bg: #f0f4fd;
  --callout-info-border: #c0d0f0;
  --callout-info-text: #2b4a7a;
  --callout-ok-bg: #f0f8f0;
  --callout-ok-border: #c0e0c0;
  --callout-ok-text: #2a6a2a;
  --accent-light: #E9F8EC;
}

*, *::before, *::after { box-sizing: border-box; }

html {
  font-size: var(--font-size-base);
  line-height: var(--line-height-base);
  min-height: 100vh;
  overflow: visible;
}

body {
  margin: 0;
  padding: var(--space-medium);
  min-height: 100vh;
  overflow: visible;
  font-family: var(--font-family);
  color: var(--color-text);
  background: var(--color-surface);
  -webkit-font-smoothing: antialiased;
  display: flex;
  flex-direction: column;
}

#summary-content { flex-grow: 1; }

/* Right chart pane body */
.pane-body { padding-bottom: var(--space-medium); }

/* Page header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-large);
  padding-bottom: var(--space-small);
  border-bottom: var(--border-width) solid var(--color-border);
}
.page-header.sticky {
  position: sticky;
  top: 0;
  background: var(--color-surface);
  padding-top: var(--space-medium);
  margin-top: calc(-1 * var(--space-medium));
  margin-left: calc(-1 * var(--space-medium));
  margin-right: calc(-1 * var(--space-medium));
  padding-left: var(--space-medium);
  padding-right: var(--space-medium);
  z-index: 10;
}
.page-title {
  font-size: 1em;
  font-weight: var(--font-weight-bold);
  color: var(--color-text-active);
  margin: 0;
}
.page-title-detail {
  font-weight: 400;
  color: var(--color-text-muted);
}
.page-subtitle {
  font-size: var(--font-size-label);
  color: var(--color-text);
  margin: var(--space-mini) 0 0;
}

/* AI badge */
.ai-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-mini);
  background: var(--color-bg);
  color: var(--color-text-muted);
  font-size: var(--font-size-badge);
  font-weight: 500;
  padding: var(--space-mini) var(--space-tiny);
  border-radius: var(--radius);
  flex-shrink: 0;
}
.ai-badge::before {
  display: none;
}

.badge {
  display: inline-block;
  font-size: var(--font-size-badge);
  font-weight: 600;
  text-transform: uppercase;
  padding: 1px var(--space-mini);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  color: var(--color-text-muted);
  vertical-align: middle;
  margin-left: var(--space-mini);
}

/* Content sections */
.summary-section,
.avs-section {
  margin-bottom: var(--space-large);
}
.summary-section h3,
.avs-section h3 {
  font-size: 1rem;
  font-weight: var(--font-weight-bold);
  color: var(--color-text-active);
  margin: 0 0 var(--space-tiny);
  padding-bottom: var(--space-mini);
  border-bottom: var(--border-width) solid var(--color-bg);
}
.summary-section p,
.summary-section ul,
.avs-section p,
.avs-section ul {
  margin: 0 0 var(--space-tiny);
  font-size: var(--font-size-label);
  color: var(--color-text);
  line-height: var(--line-height-base);
}
.summary-section p:last-child,
.avs-section p:last-child {
  margin-bottom: 0;
}
.summary-section ul,
.avs-section ul,
.banner ul {
  padding-left: var(--space-large);
}
.summary-section li,
.avs-section li,
.banner li {
  margin-bottom: 0;
  padding: var(--space-mini) 0;
  border-bottom: var(--border-width) solid var(--color-bg);
  font-size: var(--font-size-label);
}
.summary-section li:last-child,
.avs-section li:last-child,
.banner li:last-child {
  border-bottom: none;
}
.summary-section strong,
.avs-section strong {
  font-weight: var(--font-weight-bold);
  color: var(--color-text-active);
}

/* Tables inside sections */
.summary-section table,
.avs-section table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-label);
  margin: var(--space-mini) 0;
}
.summary-section th,
.avs-section th {
  background: var(--color-bg);
  padding: var(--space-tiny);
  text-align: left;
  font-weight: var(--font-weight-bold);
  color: var(--color-text-muted);
  border-bottom: 2px solid var(--color-border);
  font-size: var(--font-size-caps);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-caps);
}
.summary-section td,
.avs-section td {
  padding: var(--space-tiny) var(--space-tiny);
  border-bottom: var(--border-width) solid var(--color-bg);
  vertical-align: top;
  color: var(--color-text);
}
.summary-section tr:last-child td,
.avs-section tr:last-child td {
  border-bottom: none;
}

/* Callout boxes */
.callout,
.interim-header,
.avs-greeting,
.trend-alert {
  border-radius: var(--radius);
  padding: var(--space-small) var(--space-medium);
  font-size: var(--font-size-label);
  margin-bottom: var(--space-large);
  line-height: var(--line-height-base);
}
.callout p,
.interim-header p,
.avs-greeting p {
  margin: 0 0 var(--space-mini);
}
.callout p:last-child,
.interim-header p:last-child,
.avs-greeting p:last-child {
  margin: 0;
}

/* Callout color variants */
.callout--info,
.interim-header {
  background: var(--callout-info-bg);
  border: var(--border-width) solid var(--callout-info-border);
  color: var(--callout-info-text);
}
.callout--warning,
.trend-alert {
  background: var(--callout-caution-bg);
  border: var(--border-width) solid var(--callout-caution-border);
  color: var(--callout-caution-text);
}
.trend-alert::before {
  content: "Trend: ";
  font-weight: var(--font-weight-bold);
}
.callout--danger,
.avs-warning {
  background: var(--callout-alert-bg);
  border: var(--border-width) solid var(--callout-alert-border);
  color: var(--callout-alert-text);
  padding: var(--space-small) var(--space-medium);
}
.avs-warning h3 {
  color: var(--callout-alert-text);
  border-bottom-color: var(--callout-alert-border);
}
.callout--success {
  background: var(--callout-ok-bg);
  border: var(--border-width) solid var(--callout-ok-border);
  color: var(--callout-ok-text);
}
.callout--brand,
.avs-greeting {
  background: var(--color-bg);
  border: var(--border-width) solid var(--color-border);
  color: var(--color-text);
}

/* State indicators */
.no-data {
  color: var(--color-text-muted);
  font-style: italic;
}
.error {
  color: var(--callout-alert-text);
  font-style: italic;
}
.text-danger {
  color: var(--color-danger);
}
.hidden {
  display: none !important;
}

/* Lab flag (Since Last Visit) */
.lab-flag {
  color: var(--color-danger);
  font-weight: var(--font-weight-bold);
}

/* Buttons (from base.css) */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-tiny);
  padding: var(--btn-padding);
  font-size: var(--btn-font-size);
  font-weight: var(--font-weight-bold);
  font-family: var(--font-family);
  line-height: 1em;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
  transition: background-color var(--transition-fast), opacity var(--transition-fast);
  min-height: 44px;
}
.btn:focus-visible { outline: 2px solid var(--color-secondary); outline-offset: 2px; }
.btn-sm { padding: var(--btn-padding-sm); font-size: var(--btn-font-size-sm); min-height: 36px; }
.btn-xs { padding: var(--btn-padding-xs); font-size: var(--btn-font-size-xs); font-weight: 400; min-height: 0; }
.btn-primary { background: var(--color-primary); color: var(--color-surface); }
.btn-primary:hover { opacity: 0.9; }
.btn-secondary { background: var(--color-secondary); color: var(--color-surface); }
.btn-secondary:hover { opacity: 0.9; }
.btn-default { background: #e0e1e2; color: var(--color-text); }
.btn-default:hover { background: #cacbcd; }
.btn-danger { background: var(--color-danger); color: var(--color-surface); }
.btn-danger:hover { opacity: 0.9; }
.btn:disabled, .btn[disabled] { opacity: 0.45; cursor: not-allowed; pointer-events: none; }

/* Layout utilities (from base.css) */
.flex { display: flex; }
.flex-column { display: flex; flex-direction: column; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.items-center { align-items: center; }
.items-start { align-items: flex-start; }
.gap-mini { gap: var(--space-mini); }
.gap-tiny { gap: var(--space-tiny); }
.gap-sm { gap: var(--space-small); }
.gap-md { gap: var(--space-medium); }

/* Text utilities (from base.css) */
.text-muted { color: var(--color-text-muted); }
.text-bold { font-weight: var(--font-weight-bold); }
.text-sm { font-size: var(--font-size-label); }
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Links (from base.css) */
a { color: var(--color-secondary); text-decoration: none; transition: text-decoration var(--transition-fast); }
a:hover { text-decoration: underline; }

/* Spinner (from base.css) */
.spinner {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-huge);
}
.spinner::after {
  content: "";
  width: var(--spinner-size);
  height: var(--spinner-size);
  border: 3px solid var(--color-border);
  border-top-color: var(--color-secondary);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Empty state (from base.css) */
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-tiny);
  padding: var(--space-huge);
  color: var(--color-text-muted);
  font-size: var(--font-size-label);
  text-align: center;
}

/* Medication badges (AVS) */
.med-badge {
  display: inline-block;
  font-size: var(--font-size-badge-sm);
  font-weight: var(--font-weight-bold);
  padding: var(--space-mini) var(--space-mini);
  border-radius: var(--radius);
  margin-left: var(--space-mini);
  vertical-align: middle;
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-caps);
}
.med-badge.new {
  background: var(--accent-light);
  color: var(--color-primary);
}
.med-badge.increased {
  background: var(--callout-caution-bg);
  color: var(--callout-caution-text);
}

/* Banner (matches skill base.css) */
.banner {
  padding: var(--space-small) var(--space-medium);
  border-radius: var(--radius);
  font-size: var(--font-size-label);
  margin-bottom: var(--space-medium);
}
.banner-error {
  background: var(--color-error-bg);
  color: var(--color-error-text);
  box-shadow: 0 0 0 var(--border-width) var(--color-error-border) inset;
  font-weight: var(--font-weight-bold);
}
.banner-warning {
  background: #FFFAF3;
  color: #735B36;
  box-shadow: 0 0 0 var(--border-width) #C9BA9B inset;
}
.banner-warning .banner-header { font-weight: var(--font-weight-bold); }
.banner-info {
  background: #F8FFFF;
  color: #4B869A;
  box-shadow: 0 0 0 var(--border-width) #A9D5DE inset;
}
.banner-success {
  background: var(--callout-ok-bg);
  color: var(--callout-ok-text);
  box-shadow: 0 0 0 var(--border-width) var(--callout-ok-border) inset;
}
.banner-header { font-weight: var(--font-weight-bold); margin-bottom: var(--space-mini); }
.banner p { margin: 0; }
.banner.hidden { display: none; }

/* Toggle switch (from skill base.css) */
.toggle-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-tiny);
  min-height: 44px;
  cursor: pointer;
}
.toggle {
  position: relative;
  flex-shrink: 0;
  width: var(--toggle-width);
  height: var(--toggle-height);
  background: var(--toggle-track-inactive);
  border-radius: 500rem;
  border: none;
  cursor: pointer;
  padding: 0;
}
.toggle::after {
  content: "";
  position: absolute;
  top: 0;
  left: -0.05rem;
  width: var(--toggle-thumb-size);
  height: var(--toggle-thumb-size);
  background: #fff linear-gradient(transparent, rgba(0, 0, 0, 0.05));
  border-radius: 500rem;
  box-shadow: var(--toggle-thumb-shadow);
  transition: left 0.3s ease;
}
.toggle[aria-checked="true"] { background: var(--toggle-track-active); }
.toggle[aria-checked="true"]::after { left: var(--toggle-checked-offset); }
.toggle:hover { background: var(--toggle-track-inactive-hover); }
.toggle[aria-checked="true"]:hover { background: var(--toggle-track-active); }
.toggle[aria-disabled="true"] { opacity: 0.45; cursor: not-allowed; }
.toggle.saving { opacity: 0.6; pointer-events: none; }

/* Vitals table */
.vitals-table {
  width: 100%;
  border-collapse: collapse;
}
.vitals-table td {
  padding: var(--space-mini) 0;
  vertical-align: baseline;
}
.vitals-table td.vitals-label {
  font-size: var(--font-size-caps);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-caps);
  width: 3.75rem;
  padding-right: var(--space-tiny);
}
.vitals-table td.vitals-value {
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-active);
  padding-right: var(--space-huge);
}

/* AVS provenance badges and remove buttons */
.avs-section li,
.banner li {
  display: flex;
  align-items: flex-start;
  gap: var(--space-tiny);
}
.avs-item-text { flex: 1; }
.avs-provenance {
  display: inline-flex;
  align-items: center;
  gap: var(--space-mini);
  flex-shrink: 0;
  margin-left: var(--space-tiny);
}
.cmd-badge {
  display: inline-block;
  font-size: var(--font-size-badge);
  font-weight: var(--font-weight-bold);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-caps);
  padding: 0 var(--space-tiny);
  height: 25px;
  line-height: 25px;
  border-radius: var(--radius);
  background: #1d6fc5;
  color: #fff;
  white-space: nowrap;
}
.item-remove {
  display: none;
  align-items: center;
  justify-content: center;
  width: 25px;
  height: 25px;
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  color: var(--color-text-muted);
  font-size: 1rem;
  font-weight: var(--font-weight-bold);
  line-height: 1;
  cursor: pointer;
  padding: 0;
  flex-shrink: 0;
  transition: background-color var(--transition-fast), color var(--transition-fast);
}
.item-remove:hover { background: var(--color-error-bg); color: var(--color-danger); border-color: var(--color-error-border); }
.editing .item-remove { display: inline-flex; }

/* Section-level remove buttons (edit mode only) */
.avs-section-header {
  display: flex;
  align-items: center;
  gap: var(--space-tiny);
}
.avs-section-header h3 { flex: 1; }
.section-remove {
  display: none;
  align-items: center;
  justify-content: center;
  width: 25px;
  height: 25px;
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 0;
  flex-shrink: 0;
  transition: background-color var(--transition-fast), color var(--transition-fast);
}
.section-remove:hover { background: var(--color-error-bg); color: var(--color-danger); border-color: var(--color-error-border); }
.editing .section-remove { display: inline-flex; }

/* Textarea edit mode */
.avs-edit-textarea {
  display: block;
  width: 100%;
  font-family: var(--font-family);
  font-size: var(--font-size-label);
  line-height: var(--line-height-base);
  color: var(--color-text);
  background: transparent;
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-mini) var(--space-tiny);
  margin: 0;
  resize: none;
  overflow: hidden;
  box-sizing: border-box;
  outline: none;
  transition: border-color var(--transition-fast);
}
.avs-edit-textarea:focus {
  border-color: var(--input-focus-border);
}
.avs-added-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-tiny);
}
.avs-added-row .avs-edit-textarea { flex: 1; }
.avs-add-row {
  display: none;
  gap: var(--space-mini);
  margin-top: var(--space-mini);
  margin-left: var(--space-large);
  padding: var(--btn-padding-xs);
  font-size: var(--btn-font-size-xs);
  font-family: var(--font-family);
  font-weight: var(--font-weight-bold);
  color: var(--color-text);
  background: #e0e1e2;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
  transition: background-color var(--transition-fast);
  width: auto;
}
.avs-add-row:hover { background: #cacbcd; }
.editing .avs-add-row { display: inline-flex; }

/* Print styles */
@media print {
  html { font-size: 12.8px; }
  body {
    padding: 0;
    background: white;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .page-header,
  .page-header.sticky {
    position: static;
    margin: 0 0 var(--space-large);
    padding: 0 0 var(--space-small);
  }
  .print-area {
    display: none !important;
  }
  .avs-section,
  .summary-section {
    break-inside: avoid;
  }
  .avs-warning,
  .callout,
  .interim-header,
  .avs-greeting,
  .trend-alert,
  .vitals-table {
    break-inside: avoid;
  }
  .avs-provenance { display: none !important; }
  .section-remove { display: none !important; }
  #regenerate-btn { display: none !important; }
}
"""
