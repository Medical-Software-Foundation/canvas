// @ts-check
import { html } from "./html.js";

/**
 * @typedef {Object} StackProps
 * @property {keyof typeof GAP} [gap] Space between children (token key). Default "4".
 * @property {"stretch"|"start"|"center"|"end"} [align] Cross-axis alignment. Default "stretch".
 * @property {string} [as] Element tag to render. Default "div".
 * @property {unknown} [children] Items.
 */

/**
 * @typedef {Object} RowProps
 * @property {keyof typeof GAP} [gap] Space between children. Default "4".
 * @property {"stretch"|"start"|"center"|"end"} [align] Cross-axis alignment. Default "center".
 * @property {"start"|"center"|"end"|"between"|"around"} [justify] Main-axis distribution. Default "start".
 * @property {boolean} [wrap] Allow flex wrapping. Default false.
 * @property {string} [as] Element tag to render. Default "div".
 * @property {unknown} [children] Items.
 */

/** Maps a gap key to a spacing token. Keeps spacing on the scale, never ad-hoc px. */
const GAP = {
  0: "var(--npa-space-0)",
  1: "var(--npa-space-1)",
  2: "var(--npa-space-2)",
  3: "var(--npa-space-3)",
  4: "var(--npa-space-4)",
  5: "var(--npa-space-5)",
  6: "var(--npa-space-6)",
  8: "var(--npa-space-8)",
};

const ALIGN = { stretch: "stretch", start: "flex-start", center: "center", end: "flex-end" };
const JUSTIFY = {
  start: "flex-start",
  center: "center",
  end: "flex-end",
  between: "space-between",
  around: "space-around",
};

/**
 * Vertical flex container.
 * @param {StackProps} props
 */
export function Stack({ gap = 4, align = "stretch", as = "div", children }) {
  const style = `display:flex;flex-direction:column;gap:${GAP[gap]};align-items:${ALIGN[align]};`;
  return html`<${as} class="npa-stack" style=${style}>${children}<//>`;
}

/**
 * Horizontal flex container.
 * @param {RowProps} props
 */
export function Row({ gap = 4, align = "center", justify = "start", wrap = false, as = "div", children }) {
  const style =
    `display:flex;flex-direction:row;gap:${GAP[gap]};` +
    `align-items:${ALIGN[align]};justify-content:${JUSTIFY[justify]};` +
    `flex-wrap:${wrap ? "wrap" : "nowrap"};`;
  return html`<${as} class="npa-row" style=${style}>${children}<//>`;
}
