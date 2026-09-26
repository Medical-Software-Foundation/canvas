// @ts-check
import { html } from "./html.js";

/**
 * @typedef {Object} SpinnerProps
 * @property {"sm"|"md"|"lg"} [size] Diameter scale. Default "md".
 * @property {string} [label] Accessible label announced to screen readers. Default "Loading".
 * @property {boolean} [center] Center within its parent block. Default false.
 */

const DIAMETER = { sm: "16px", md: "24px", lg: "36px" };

/**
 * Brand-colored loading spinner.
 * @param {SpinnerProps} props
 */
export function Spinner({ size = "md", label = "Loading", center = false }) {
  const d = DIAMETER[size];
  const wrapStyle = center ? "display:flex;justify-content:center;padding:var(--npa-space-4);" : "display:inline-flex;";

  return html`
    <span class="npa-spinner-wrap" style=${wrapStyle} role="status" aria-live="polite">
      <span class="npa-spinner" style=${`width:${d};height:${d};`}></span>
      <span class="npa-visually-hidden">${label}</span>
    </span>
    <style>
      .npa-spinner {
        display: inline-block;
        border: 2px solid var(--npa-color-border);
        border-top-color: var(--npa-color-primary);
        border-radius: var(--npa-radius-pill);
        animation: npa-spin 0.7s linear infinite;
      }
      @keyframes npa-spin { to { transform: rotate(360deg); } }
      .npa-visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        margin: -1px;
        padding: 0;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
        border: 0;
      }
    </style>
  `;
}
