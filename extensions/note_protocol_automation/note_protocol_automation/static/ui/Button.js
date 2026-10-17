// @ts-check
import { html } from "./html.js";

/**
 * @typedef {Object} ButtonProps
 * @property {"primary"|"secondary"|"ghost"|"danger"} [variant] Visual style. Default "primary".
 * @property {"sm"|"md"|"lg"} [size] Padding/type scale. Default "md".
 * @property {boolean} [disabled] Disable interaction.
 * @property {boolean} [loading] Show a spinner and disable.
 * @property {boolean} [block] Stretch to full width.
 * @property {"button"|"submit"|"reset"} [type] Native button type. Default "button".
 * @property {(event: Event) => void} [onClick] Click handler.
 * @property {unknown} [children] Button label / content.
 */

/**
 * Primary action button, styled entirely via tokens.css custom properties.
 * @param {ButtonProps} props
 */
export function Button({
  variant = "primary",
  size = "md",
  disabled = false,
  loading = false,
  block = false,
  type = "button",
  onClick,
  children,
}) {
  const classes = [
    "npa-btn",
    `npa-btn--${variant}`,
    `npa-btn--${size}`,
    block ? "npa-btn--block" : "",
    loading ? "npa-btn--loading" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return html`
    <button
      type=${type}
      class=${classes}
      disabled=${disabled || loading}
      aria-busy=${loading ? "true" : "false"}
      onClick=${onClick}
    >
      ${loading ? html`<span class="npa-btn__spinner" aria-hidden="true"></span>` : null}
      <span class="npa-btn__label">${children}</span>
    </button>
    <style>
      .npa-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: var(--npa-space-2);
        font-family: var(--npa-font-sans);
        font-weight: var(--npa-font-weight-semibold);
        line-height: 1;
        border: 1px solid transparent;
        border-radius: var(--npa-radius-md);
        cursor: pointer;
        transition: background-color var(--npa-transition-fast),
          border-color var(--npa-transition-fast), color var(--npa-transition-fast);
        text-decoration: none;
        white-space: nowrap;
      }
      .npa-btn:focus-visible {
        outline: 2px solid var(--npa-color-focus-ring);
        outline-offset: 2px;
      }
      .npa-btn:disabled {
        cursor: not-allowed;
        opacity: 0.55;
      }
      .npa-btn--block { width: 100%; }

      /* Sizes */
      .npa-btn--sm { padding: var(--npa-space-1) var(--npa-space-3); font-size: var(--npa-font-size-sm); }
      .npa-btn--md { padding: var(--npa-space-2) var(--npa-space-4); font-size: var(--npa-font-size-md); }
      .npa-btn--lg { padding: var(--npa-space-3) var(--npa-space-6); font-size: var(--npa-font-size-lg); }

      /* Variants */
      .npa-btn--primary { background: var(--npa-color-primary); color: var(--npa-color-text-inverse); }
      .npa-btn--primary:not(:disabled):hover { background: var(--npa-color-primary-hover); }
      .npa-btn--primary:not(:disabled):active { background: var(--npa-color-primary-active); }

      .npa-btn--secondary {
        background: var(--npa-color-surface);
        color: var(--npa-color-primary);
        border-color: var(--npa-color-border-strong);
      }
      .npa-btn--secondary:not(:disabled):hover { background: var(--npa-color-primary-subtle); }

      .npa-btn--ghost { background: transparent; color: var(--npa-color-primary); }
      .npa-btn--ghost:not(:disabled):hover { background: var(--npa-color-primary-subtle); }

      .npa-btn--danger { background: var(--npa-color-danger); color: var(--npa-color-text-inverse); }
      .npa-btn--danger:not(:disabled):hover { filter: brightness(0.93); }

      .npa-btn__spinner {
        width: 14px;
        height: 14px;
        border: 2px solid currentColor;
        border-right-color: transparent;
        border-radius: var(--npa-radius-pill);
        animation: npa-btn-spin 0.6s linear infinite;
      }
      @keyframes npa-btn-spin { to { transform: rotate(360deg); } }
    </style>
  `;
}
