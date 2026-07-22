// @ts-check
/**
 * Shared Preact + htm binding for the admin-UI component library.
 *
 * Every component imports `h` and the bound `html` tagged-template from here so
 * the exact pinned versions (preact@10.25.4 / htm@3.1.1) live in ONE place.
 *
 * SUPPLY CHAIN: `preact` and `htm` are BARE SPECIFIERS. They resolve via the
 * import map declared in the iframe's index.html to the plugin's OWN same-origin
 * vendored copies under /static/vendor/ (SRI-checked) — NOT a CDN at runtime.
 * Vendoring locally keeps Preact + htm downloaded ONCE and reused from the browser
 * cache, with verifiable integrity.
 *
 * NO build step: this is a browser-native ES module loaded directly from the
 * plugin's static URL. Consumers import from this file with a RELATIVE path
 * (e.g. `./html.js`).
 */
import { h } from "preact";
import htm from "htm";

/** Preact's hyperscript factory, re-exported for components that need it raw. */
export { h };

/**
 * The htm tagged-template bound to Preact's `h`.
 * Usage: html`<${Button} variant="primary">Save<//>`
 * @type {(strings: TemplateStringsArray, ...values: unknown[]) => unknown}
 */
export const html = htm.bind(h);
