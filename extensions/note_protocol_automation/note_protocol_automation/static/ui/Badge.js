// @ts-check
import { html } from "./html.js";

/**
 * @typedef {"neutral"|"info"|"success"|"warning"|"danger"} BadgeTone
 */

/**
 * @typedef {Object} BadgeProps
 * @property {BadgeTone} [tone] Semantic color. Default "neutral".
 * @property {boolean} [subtle] Use the soft tinted background instead of solid. Default true.
 * @property {unknown} [children] Badge label.
 */

/**
 * Small status pill — used e.g. for the severity label on a symptom check-in.
 * @param {BadgeProps} props
 */
export function Badge({ tone = "neutral", subtle = true, children }) {
  const classes = ["npa-badge", `npa-badge--${tone}`, subtle ? "npa-badge--subtle" : "npa-badge--solid"].join(
    " "
  );

  return html`
    <span class=${classes}>${children}</span>
    <style>
      .npa-badge {
        display: inline-flex;
        align-items: center;
        font-family: var(--npa-font-sans);
        font-size: var(--npa-font-size-xs);
        font-weight: var(--npa-font-weight-semibold);
        line-height: 1;
        padding: var(--npa-space-1) var(--npa-space-2);
        border-radius: var(--npa-radius-pill);
        letter-spacing: 0.01em;
      }

      /* Subtle (tinted bg + colored text) */
      .npa-badge--subtle.npa-badge--neutral { background: var(--npa-gray-100); color: var(--npa-gray-600); }
      .npa-badge--subtle.npa-badge--info { background: var(--npa-color-info-bg); color: var(--npa-blue-700); }
      .npa-badge--subtle.npa-badge--success { background: var(--npa-color-success-bg); color: var(--npa-green-700); }
      .npa-badge--subtle.npa-badge--warning { background: var(--npa-color-warning-bg); color: var(--npa-color-warning); }
      .npa-badge--subtle.npa-badge--danger { background: var(--npa-color-danger-bg); color: var(--npa-color-danger); }

      /* Solid (filled bg + inverse text) */
      .npa-badge--solid { color: var(--npa-color-text-inverse); }
      .npa-badge--solid.npa-badge--neutral { background: var(--npa-gray-500); }
      .npa-badge--solid.npa-badge--info { background: var(--npa-color-info); }
      .npa-badge--solid.npa-badge--success { background: var(--npa-color-success); }
      .npa-badge--solid.npa-badge--warning { background: var(--npa-color-warning); }
      .npa-badge--solid.npa-badge--danger { background: var(--npa-color-danger); }
    </style>
  `;
}
