// @ts-check
import { html } from "./html.js";

/**
 * @typedef {Object} CardProps
 * @property {unknown} [title] Optional header title.
 * @property {unknown} [actions] Optional header right-aligned actions (e.g. a Button).
 * @property {"sm"|"md"|"lg"} [padding] Inner padding scale. Default "md".
 * @property {"none"|"sm"|"md"} [elevation] Drop shadow. Default "sm".
 * @property {unknown} [children] Card body content.
 */

/**
 * Surface container with optional header. Styled via tokens.css.
 * @param {CardProps} props
 */
export function Card({ title, actions, padding = "md", elevation = "sm", children }) {
  const classes = ["npa-card", `npa-card--pad-${padding}`, `npa-card--elev-${elevation}`].join(" ");
  const hasHeader = title != null || actions != null;

  return html`
    <section class=${classes}>
      ${hasHeader
        ? html`
            <header class="npa-card__header">
              ${title != null ? html`<h2 class="npa-card__title">${title}</h2>` : html`<span></span>`}
              ${actions != null ? html`<div class="npa-card__actions">${actions}</div>` : null}
            </header>
          `
        : null}
      <div class="npa-card__body">${children}</div>
    </section>
    <style>
      .npa-card {
        background: var(--npa-color-surface);
        border: 1px solid var(--npa-color-border);
        border-radius: var(--npa-radius-lg);
        overflow: hidden;
      }
      .npa-card--elev-none { box-shadow: none; }
      .npa-card--elev-sm { box-shadow: var(--npa-shadow-sm); }
      .npa-card--elev-md { box-shadow: var(--npa-shadow-md); }

      .npa-card__header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--npa-space-3);
        padding: var(--npa-space-3) var(--npa-space-4);
        border-bottom: 1px solid var(--npa-color-border);
        background: var(--npa-color-surface);
      }
      .npa-card__title {
        margin: 0;
        font-family: var(--npa-font-sans);
        font-size: var(--npa-font-size-lg);
        font-weight: var(--npa-font-weight-semibold);
        color: var(--npa-color-text);
      }
      .npa-card__actions { display: inline-flex; gap: var(--npa-space-2); }

      .npa-card--pad-sm .npa-card__body { padding: var(--npa-space-3); }
      .npa-card--pad-md .npa-card__body { padding: var(--npa-space-4); }
      .npa-card--pad-lg .npa-card__body { padding: var(--npa-space-6); }
    </style>
  `;
}
