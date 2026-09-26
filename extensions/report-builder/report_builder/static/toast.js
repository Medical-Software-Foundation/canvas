import { h } from 'https://esm.sh/preact@10.25.4';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

export function Toast({ message, kind = 'info' }) {
  return html`<div class=${`rb-toast rb-toast-${kind}`}>${message}</div>`;
}
