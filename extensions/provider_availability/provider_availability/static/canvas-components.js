/* canvas-accordion-title: title bar content. Has its own shadow DOM slot so children render. */
if (!customElements.get('canvas-accordion-title')) {
  class CanvasAccordionTitle extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = '<style>:host{display:flex;align-items:center;gap:8px;flex:1;min-width:0}</style><slot></slot>';
    }
  }
  customElements.define('canvas-accordion-title', CanvasAccordionTitle);
}

/* canvas-accordion-content: collapsible content area, hidden by default */
if (!customElements.get('canvas-accordion-content')) {
  class CanvasAccordionContent extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = '<style>:host{display:none;padding:.5em 0 1em}:host([visible]){display:block}</style><slot></slot>';
    }
    connectedCallback() {
      this.setAttribute('role', 'region');
    }
  }
  customElements.define('canvas-accordion-content', CanvasAccordionContent);
}

/* canvas-accordion-item: collapsible section with chevron, title slot, and content slot */
if (!customElements.get('canvas-accordion-item')) {
  class CanvasAccordionItem extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._isOpen = false;
    }

    connectedCallback() {
      var self = this;
      this._isOpen = this.hasAttribute('open');
      this._render();
      this._bindEvents();
      setTimeout(function() {
        self._assignSlots();
        if (self._isOpen) self._expand(false);
      }, 0);
    }

    get open() { return this._isOpen; }
    set open(val) {
      if (val) this._expand(true);
      else this._collapse(true);
    }

    toggle() {
      if (this._isOpen) this._collapse(true);
      else this._expand(true);
    }

    _render() {
      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          .title {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 7px 0;
            font-size: 1.125em;
            font-weight: 700;
            line-height: 1.14285714em;
            color: rgba(0, 0, 0, 0.87);
            background: transparent;
            border: none;
            width: 100%;
            text-align: left;
            cursor: pointer;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            transition: color 0.1s ease;
          }
          .title:hover { color: rgba(0, 0, 0, 0.95); }
          .title:focus-visible {
            outline: 2px solid #2185d0;
            outline-offset: -2px;
          }
          .icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 10px;
            height: 10px;
            flex-shrink: 0;
            transition: transform 0.1s ease;
            transform: rotate(-90deg);
          }
          :host([open]) .icon {
            transform: rotate(0deg);
          }
        </style>
        <div class="title" role="button" tabindex="0" aria-expanded="false">
          <span class="icon"><svg width="10" height="6" viewBox="0 0 10 6" fill="currentColor"><path d="M1 0h8a1 1 0 01.7 1.7l-4 4a1 1 0 01-1.4 0l-4-4A1 1 0 011 0z"/></svg></span>
          <slot name="title"></slot>
        </div>
        <slot name="content"></slot>
      `;
    }

    _assignSlots() {
      var titleEl = this.querySelector('canvas-accordion-title');
      if (titleEl) titleEl.setAttribute('slot', 'title');
      var contentEl = this.querySelector('canvas-accordion-content');
      if (contentEl) contentEl.setAttribute('slot', 'content');
    }

    _bindEvents() {
      var self = this;
      var title = this.shadowRoot.querySelector('.title');

      title.addEventListener('click', function() {
        self.toggle();
      });

      title.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          self.toggle();
        }
      });
    }

    _expand(fireEvent) {
      this._isOpen = true;
      this.setAttribute('open', '');
      this.shadowRoot.querySelector('.title').setAttribute('aria-expanded', 'true');
      var content = this.querySelector('canvas-accordion-content');
      if (content) content.setAttribute('visible', '');
      if (fireEvent) {
        this.dispatchEvent(new CustomEvent('toggle', { bubbles: true, composed: true, detail: { open: true } }));
      }
    }

    _collapse(fireEvent) {
      this._isOpen = false;
      this.removeAttribute('open');
      this.shadowRoot.querySelector('.title').setAttribute('aria-expanded', 'false');
      var content = this.querySelector('canvas-accordion-content');
      if (content) content.removeAttribute('visible');
      if (fireEvent) {
        this.dispatchEvent(new CustomEvent('toggle', { bubbles: true, composed: true, detail: { open: false } }));
      }
    }
  }
  customElements.define('canvas-accordion-item', CanvasAccordionItem);
}

/* canvas-accordion: thin container, no shadow DOM */
if (!customElements.get('canvas-accordion')) {
  class CanvasAccordion extends HTMLElement {
    constructor() { super(); }
    connectedCallback() { this.style.display = 'block'; this.style.width = '100%'; }
  }
  customElements.define('canvas-accordion', CanvasAccordion);
}

if (!customElements.get('canvas-badge')) {
  class CanvasBadge extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: inline-block;
            vertical-align: baseline;
          }

          span {
            display: inline-block;
            line-height: 1;
            margin: 0 .14285714em;
            padding: var(--canvas-badge-padding, .5833em .833em);
            font-weight: var(--canvas-badge-font-weight, var(--font-weight-bold, 700));
            font-family: var(--canvas-badge-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
            font-size: var(--canvas-badge-font-size, .85714286rem);
            border: var(--canvas-badge-border, 0 solid transparent);
            border-radius: var(--canvas-badge-radius, var(--radius, .28571429rem));
            background: var(--canvas-badge-bg, #e8e8e8);
            color: var(--canvas-badge-color, rgba(0, 0, 0, 0.6));
            white-space: nowrap;
            transition: background 0.1s ease;
          }

          /* Solid colors */
          :host([color="red"]) span { background: var(--canvas-badge-red-bg, var(--palette-red, #db2828)); color: var(--canvas-badge-red-color, #fff); }
          :host([color="orange"]) span { background: var(--canvas-badge-orange-bg, var(--palette-orange, #f2711c)); color: var(--canvas-badge-orange-color, #fff); }
          :host([color="yellow"]) span { background: var(--canvas-badge-yellow-bg, var(--palette-yellow, #fbbd08)); color: var(--canvas-badge-yellow-color, #fff); }
          :host([color="olive"]) span { background: var(--canvas-badge-olive-bg, var(--palette-olive, #b5cc18)); color: var(--canvas-badge-olive-color, #fff); }
          :host([color="green"]) span { background: var(--canvas-badge-green-bg, var(--palette-green, #21ba45)); color: var(--canvas-badge-green-color, #fff); }
          :host([color="teal"]) span { background: var(--canvas-badge-teal-bg, var(--palette-teal, #00b5ad)); color: var(--canvas-badge-teal-color, #fff); }
          :host([color="blue"]) span { background: var(--canvas-badge-blue-bg, var(--palette-blue, #2185d0)); color: var(--canvas-badge-blue-color, #fff); }
          :host([color="violet"]) span { background: var(--canvas-badge-violet-bg, var(--palette-violet, #6435c9)); color: var(--canvas-badge-violet-color, #fff); }
          :host([color="purple"]) span { background: var(--canvas-badge-purple-bg, var(--palette-purple, #a333c8)); color: var(--canvas-badge-purple-color, #fff); }
          :host([color="pink"]) span { background: var(--canvas-badge-pink-bg, var(--palette-pink, #e03997)); color: var(--canvas-badge-pink-color, #fff); }
          :host([color="brown"]) span { background: var(--canvas-badge-brown-bg, var(--palette-brown, #a5673f)); color: var(--canvas-badge-brown-color, #fff); }
          :host([color="grey"]) span { background: var(--canvas-badge-grey-bg, var(--palette-grey, #767676)); color: var(--canvas-badge-grey-color, #fff); }
          :host([color="black"]) span { background: var(--canvas-badge-black-bg, var(--palette-black, #1b1c1d)); color: var(--canvas-badge-black-color, #fff); }

          /* Sizes */
          :host([size="mini"]) span { font-size: var(--canvas-badge-font-size-mini, .64285714rem); }
          :host([size="tiny"]) span { font-size: var(--canvas-badge-font-size-tiny, .71428571rem); }
          :host([size="small"]) span { font-size: var(--canvas-badge-font-size-small, .78571429rem); }
          :host([size="large"]) span { font-size: var(--canvas-badge-font-size-large, 1rem); }

          /* Basic variant (white bg, colored border and text) */
          :host([basic]) span {
            background: #fff;
            border: 1px solid rgba(34, 36, 38, 0.15);
            color: rgba(0, 0, 0, 0.87);
          }
          :host([basic][color="red"]) span { background: #fff; color: var(--canvas-badge-red-bg, var(--palette-red, #db2828)); border-color: var(--canvas-badge-red-bg, var(--palette-red, #db2828)); }
          :host([basic][color="orange"]) span { background: #fff; color: var(--canvas-badge-orange-bg, var(--palette-orange, #f2711c)); border-color: var(--canvas-badge-orange-bg, var(--palette-orange, #f2711c)); }
          :host([basic][color="yellow"]) span { background: #fff; color: var(--canvas-badge-yellow-bg, var(--palette-yellow, #fbbd08)); border-color: var(--canvas-badge-yellow-bg, var(--palette-yellow, #fbbd08)); }
          :host([basic][color="olive"]) span { background: #fff; color: var(--canvas-badge-olive-bg, var(--palette-olive, #b5cc18)); border-color: var(--canvas-badge-olive-bg, var(--palette-olive, #b5cc18)); }
          :host([basic][color="green"]) span { background: #fff; color: var(--canvas-badge-green-bg, var(--palette-green, #21ba45)); border-color: var(--canvas-badge-green-bg, var(--palette-green, #21ba45)); }
          :host([basic][color="teal"]) span { background: #fff; color: var(--canvas-badge-teal-bg, var(--palette-teal, #00b5ad)); border-color: var(--canvas-badge-teal-bg, var(--palette-teal, #00b5ad)); }
          :host([basic][color="blue"]) span { background: #fff; color: var(--canvas-badge-blue-bg, var(--palette-blue, #2185d0)); border-color: var(--canvas-badge-blue-bg, var(--palette-blue, #2185d0)); }
          :host([basic][color="violet"]) span { background: #fff; color: var(--canvas-badge-violet-bg, var(--palette-violet, #6435c9)); border-color: var(--canvas-badge-violet-bg, var(--palette-violet, #6435c9)); }
          :host([basic][color="purple"]) span { background: #fff; color: var(--canvas-badge-purple-bg, var(--palette-purple, #a333c8)); border-color: var(--canvas-badge-purple-bg, var(--palette-purple, #a333c8)); }
          :host([basic][color="pink"]) span { background: #fff; color: var(--canvas-badge-pink-bg, var(--palette-pink, #e03997)); border-color: var(--canvas-badge-pink-bg, var(--palette-pink, #e03997)); }
          :host([basic][color="brown"]) span { background: #fff; color: var(--canvas-badge-brown-bg, var(--palette-brown, #a5673f)); border-color: var(--canvas-badge-brown-bg, var(--palette-brown, #a5673f)); }
          :host([basic][color="grey"]) span { background: #fff; color: var(--canvas-badge-grey-bg, var(--palette-grey, #767676)); border-color: var(--canvas-badge-grey-bg, var(--palette-grey, #767676)); }
          :host([basic][color="black"]) span { background: #fff; color: var(--canvas-badge-black-bg, var(--palette-black, #1b1c1d)); border-color: var(--canvas-badge-black-bg, var(--palette-black, #1b1c1d)); }

          /* Circular variant: circle for 1-2 chars, pill for 3+ */
          :host([circular]) span {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 2em;
            min-height: 2em;
            padding: 0;
            border-radius: 500rem;
            box-sizing: border-box;
            aspect-ratio: 1;
          }

          :host([circular]) span.pill {
            aspect-ratio: auto;
            padding: 0 .5em;
          }
        </style>
        <span part="badge"><slot></slot></span>
      `;
      this._span = this.shadowRoot.querySelector('span');
      this._slot = this.shadowRoot.querySelector('slot');
    }

    connectedCallback() {
      this._slot.addEventListener('slotchange', () => this._updateShape());
      this._updateShape();
    }

    _updateShape() {
      var text = this.textContent.trim();
      if (text.length > 2) {
        this._span.classList.add('pill');
      } else {
        this._span.classList.remove('pill');
      }
    }
  }

  customElements.define('canvas-badge', CanvasBadge);
}

if (!customElements.get('canvas-banner')) {
  class CanvasBanner extends HTMLElement {
    static get observedAttributes() {
      return ['variant', 'header', 'dismissible'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._render();
      this._onDismissClick = this._onDismissClick.bind(this);
    }

    connectedCallback() {
      var btn = this.shadowRoot.querySelector('.dismiss');
      if (btn) btn.addEventListener('click', this._onDismissClick);
    }

    disconnectedCallback() {
      var btn = this.shadowRoot.querySelector('.dismiss');
      if (btn) btn.removeEventListener('click', this._onDismissClick);
    }

    attributeChangedCallback() {
      this._render();
      var btn = this.shadowRoot.querySelector('.dismiss');
      if (btn) btn.addEventListener('click', this._onDismissClick);
    }

    _onDismissClick(e) {
      e.stopPropagation();
      this.dispatchEvent(new CustomEvent('dismiss', { bubbles: true, composed: true }));
    }

    _render() {
      var header = this.getAttribute('header');
      var dismissible = this.hasAttribute('dismissible');

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
          }

          .banner {
            position: relative;
            min-height: 1em;
            padding: 1em 1.5em;
            line-height: 1.4285em;
            font-size: .92857143em;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            color: rgba(0, 0, 0, 0.87);
            background: #f8f8f9;
            border-radius: var(--radius, .28571429rem);
            box-shadow: 0 0 0 1px rgba(34, 36, 38, 0.22) inset, 0 0 0 0 transparent;
          }

          :host([dismissible]) .banner {
            padding-right: 2.5em;
          }

          /* Variants */
          :host([variant="warning"]) .banner {
            background-color: #fffaf3;
            color: #573a08;
            box-shadow: 0 0 0 1px #c9ba9b inset, 0 0 0 0 transparent;
          }
          :host([variant="warning"]) .header { color: #794b02; }

          :host([variant="error"]) .banner {
            background-color: #fff6f6;
            color: #9f3a38;
            box-shadow: 0 0 0 1px #e0b4b4 inset, 0 0 0 0 transparent;
          }
          :host([variant="error"]) .header { color: #912d2b; }

          :host([variant="success"]) .banner {
            background-color: #fcfff5;
            color: #2c662d;
            box-shadow: 0 0 0 1px #a3c293 inset, 0 0 0 0 transparent;
          }
          :host([variant="success"]) .header { color: #1a531b; }

          :host([variant="info"]) .banner {
            background-color: #f8ffff;
            color: #276f86;
            box-shadow: 0 0 0 1px #a9d5de inset, 0 0 0 0 transparent;
          }
          :host([variant="info"]) .header { color: #0e566c; }

          /* Header */
          .header {
            font-weight: 700;
            font-size: 1.14285714em;
          }

          /* Slotted content spacing */
          .header + .body { margin-top: .25em; }
          .body { opacity: 0.85; }
          ::slotted(ul) { padding-left: 1.5em; margin: 0; }
          ::slotted(p) { margin: 0; }
          ::slotted(p + ul) { margin-top: .5em; }
          ::slotted(li) { margin-bottom: .25em; }

          /* Dismiss button */
          .dismiss {
            position: absolute;
            top: 1em;
            right: 1em;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0;
            margin: 0;
            background: none;
            border: none;
            cursor: pointer;
            color: inherit;
            opacity: .5;
            line-height: 1;
            transition: opacity 0.1s ease;
          }
          .dismiss:hover { opacity: 1; }
          .dismiss svg { display: block; }
        </style>
        <div class="banner" role="alert">
          ${header ? '<div class="header">' + header + '</div>' : ''}
          <div class="body"><slot></slot></div>
          ${dismissible ? '<button class="dismiss" aria-label="Dismiss"><svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button>' : ''}
        </div>
      `;
    }
  }

  customElements.define('canvas-banner', CanvasBanner);
}

if (!customElements.get('canvas-button')) {
  class CanvasButton extends HTMLElement {
    static get observedAttributes() {
      return ['variant', 'size', 'disabled', 'type'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open', delegatesFocus: true });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: inline-flex;
          }

          button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: var(--canvas-button-gap, var(--space-tiny, 8px));
            padding: var(--canvas-button-padding, .67857143em 1.5em);
            font-size: var(--canvas-button-font-size, 1rem);
            font-weight: var(--canvas-button-font-weight, var(--font-weight-bold, 700));
            font-family: var(--canvas-button-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
            line-height: 1.21428571em;
            border: var(--canvas-button-border, 1px solid transparent);
            border-radius: var(--canvas-button-radius, var(--radius, .28571429rem));
            cursor: pointer;
            transition: background-color var(--canvas-button-transition, var(--transition-fast, 200ms)), opacity var(--canvas-button-transition, var(--transition-fast, 200ms));
            min-height: 1em;
            width: 100%;
            height: 100%;
            background: var(--canvas-button-bg, var(--color-secondary, var(--palette-blue, #2185D0)));
            color: var(--canvas-button-color, #fff);
          }

          button:focus-visible {
            outline: var(--canvas-button-focus-ring, var(--focus-ring, 2px solid #2185D0));
            outline-offset: var(--canvas-button-focus-ring-offset, var(--focus-ring-offset, 2px));
          }

          /* Variants */
          :host([variant="primary"]) button {
            background: var(--canvas-button-primary-bg, var(--color-primary, var(--palette-green, #22BA45)));
            color: var(--canvas-button-primary-color, #fff);
          }

          :host([variant="secondary"]) button,
          :host(:not([variant])) button {
            background: var(--canvas-button-bg, var(--color-secondary, var(--palette-blue, #2185D0)));
            color: var(--canvas-button-color, #fff);
          }

          :host([variant="ghost"]) button {
            background: var(--canvas-button-ghost-bg, #e0e1e2);
            color: var(--canvas-button-ghost-color, rgba(0, 0, 0, 0.6));
          }

          :host([variant="danger"]) button {
            background: var(--canvas-button-danger-bg, var(--color-danger, var(--palette-red, #BD0B00)));
            color: var(--canvas-button-danger-color, #fff);
          }

          /* Hover */
          :host([variant="primary"]) button:hover,
          :host([variant="secondary"]) button:hover,
          :host(:not([variant])) button:hover,
          :host([variant="danger"]) button:hover {
            opacity: 0.9;
          }

          :host([variant="ghost"]) button:hover {
            background: var(--canvas-button-ghost-hover-bg, #cacbcd);
            color: var(--canvas-button-ghost-hover-color, rgba(0, 0, 0, 0.8));
          }

          /* Sizes */
          :host([size="sm"]) button {
            padding: var(--canvas-button-padding-sm, .58928571em 1.125em);
            font-size: var(--canvas-button-font-size-sm, .92857143rem);
            min-height: 36px;
          }

          :host([size="xs"]) button {
            padding: var(--canvas-button-padding-xs, .5em .85714286em);
            font-size: var(--canvas-button-font-size-xs, .78571429rem);
            font-weight: 400;
            min-height: 0;
          }

          /* Disabled */
          :host([disabled]) button {
            opacity: 0.45;
            cursor: default;
            pointer-events: none;
          }
        </style>
        <button type="button" part="button"><slot></slot></button>
      `;
      this._button = this.shadowRoot.querySelector('button');
    }

    connectedCallback() {
      this._syncType();
      this._syncDisabled();
      this._button.addEventListener('click', this._handleClick.bind(this));
    }

    disconnectedCallback() {
      this._button.removeEventListener('click', this._handleClick.bind(this));
    }

    attributeChangedCallback(name) {
      if (name === 'type') this._syncType();
      if (name === 'disabled') this._syncDisabled();
    }

    _syncType() {
      this._button.type = this.getAttribute('type') || 'button';
    }

    _syncDisabled() {
      var disabled = this.hasAttribute('disabled');
      if (disabled) {
        this._button.setAttribute('disabled', '');
      } else {
        this._button.removeAttribute('disabled');
      }
    }

    _handleClick(e) {
      e.stopPropagation();
      if (this.hasAttribute('disabled')) return;
      if (this.getAttribute('type') === 'submit') {
        var form = this.closest('form');
        if (form) form.requestSubmit();
      }
      this.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, composed: true }));
    }
  }

  customElements.define('canvas-button', CanvasButton);
}

if (!customElements.get('canvas-card')) {
  class CanvasCard extends HTMLElement {
    static get observedAttributes() {
      return ['raised'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
          }

          .card {
            display: flex;
            flex-direction: column;
            position: relative;
            border: 1px solid rgba(34, 36, 38, 0.15);
            box-shadow: var(--canvas-card-shadow, 0 1px 2px 0 rgba(34, 36, 38, 0.15));
            border-radius: var(--radius, .28571429rem);
            background: var(--color-surface, #FFFFFF);
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            color: var(--color-text, rgba(0, 0, 0, 0.87));
            overflow: hidden;
          }

          :host([raised]) .card {
            box-shadow: var(--canvas-card-shadow, 0 2px 4px 0 rgba(34, 36, 38, 0.12), 0 2px 10px 0 rgba(34, 36, 38, 0.15));
          }

          ::slotted(canvas-card-body) {
            display: block;
            padding: 1em;
            background: var(--color-surface, #FFFFFF);
          }

          ::slotted(canvas-card-body[no-padding]) {
            padding: 0;
          }

          ::slotted(canvas-card-body + canvas-card-body) {
            border-top: 1px solid rgba(34, 36, 38, 0.15);
          }

          ::slotted(canvas-card-footer) {
            display: block;
            padding: 1em;
            background: #f3f4f5;
            color: rgba(0, 0, 0, 0.6);
            border-top: 1px solid rgba(34, 36, 38, 0.15);
          }

          ::slotted(canvas-card-footer[no-padding]) {
            padding: 0;
          }
        </style>
        <div class="card">
          <slot></slot>
        </div>
      `;
    }
  }

  class CanvasCardBody extends HTMLElement {
    constructor() {
      super();
    }
  }

  class CanvasCardFooter extends HTMLElement {
    constructor() {
      super();
    }
  }

  customElements.define('canvas-card', CanvasCard);
  customElements.define('canvas-card-body', CanvasCardBody);
  customElements.define('canvas-card-footer', CanvasCardFooter);
}

if (!customElements.get('canvas-checkbox')) {
  class CanvasCheckbox extends HTMLElement {
    static get observedAttributes() {
      return ['label', 'checked', 'disabled', 'name', 'value'];
    }

    static formAssociated = true;

    constructor() {
      super();
      this._internals = this.attachInternals();
      this.attachShadow({ mode: 'open', delegatesFocus: true });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: inline-flex;
            align-items: center;
            min-height: var(--canvas-checkbox-min-height, auto);
            min-width: var(--canvas-checkbox-min-width, auto);
            cursor: pointer;
            font-size: 1rem;
            line-height: 1;
            font-family: lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
          }

          :host([disabled]) {
            cursor: not-allowed;
            opacity: 0.45;
          }

          input {
            position: absolute;
            opacity: 0;
            width: 17px;
            height: 17px;
            cursor: pointer;
            z-index: 3;
            margin: 0;
          }

          :host([disabled]) input { cursor: not-allowed; }

          .box {
            position: relative;
            flex-shrink: 0;
            width: 17px;
            height: 17px;
            background: #FFFFFF;
            border: 1px solid #d4d4d5;
            border-radius: .21428571rem;
            transition: border 0.1s ease, background 0.1s ease;
            box-sizing: border-box;
          }

          .box::after {
            content: "";
            position: absolute;
            top: 1px;
            left: 4px;
            width: 3.5px;
            height: 8px;
            border: solid rgba(0, 0, 0, 0.95);
            border-width: 0 3px 3px 0;
            transform: rotate(45deg);
            opacity: 0;
            transition: opacity 0.1s ease;
          }

          input:checked ~ .box {
            border-color: rgba(34, 36, 38, 0.35);
          }

          input:checked ~ .box::after { opacity: 1; }

          :host(:hover) .box { border-color: rgba(34, 36, 38, 0.35); }

          input:focus ~ .box,
          :host(:hover) input:focus ~ .box {
            border-color: #85b7d9;
          }

          .label-text {
            padding-left: 8px;
            color: rgba(0, 0, 0, 0.87);
          }
        </style>
        <input type="checkbox" part="input">
        <span class="box"></span>
        <span class="label-text" part="label"></span>
      `;
      this._input = this.shadowRoot.querySelector('input');
      this._labelText = this.shadowRoot.querySelector('.label-text');
      this._boundOnChange = this._onChange.bind(this);
      this._boundOnClick = this._onClick.bind(this);
    }

    connectedCallback() {
      this._input.addEventListener('change', this._boundOnChange);
      this.addEventListener('click', this._boundOnClick);
      this._syncAll();
    }

    disconnectedCallback() {
      this._input.removeEventListener('change', this._boundOnChange);
      this.removeEventListener('click', this._boundOnClick);
    }

    attributeChangedCallback(name) {
      switch (name) {
        case 'label':
          this._labelText.textContent = this.getAttribute('label') || '';
          break;
        case 'checked':
          this._input.checked = this.hasAttribute('checked');
          this._syncFormValue();
          break;
        case 'disabled':
          this._input.disabled = this.hasAttribute('disabled');
          break;
        case 'name':
          this._input.name = this.getAttribute('name') || '';
          break;
        case 'value':
          this._input.value = this.getAttribute('value') || 'on';
          this._syncFormValue();
          break;
      }
    }

    get checked() {
      return this._input.checked;
    }

    set checked(v) {
      if (v) {
        this.setAttribute('checked', '');
      } else {
        this.removeAttribute('checked');
      }
      this._input.checked = v;
      this._syncFormValue();
    }

    get value() {
      return this.getAttribute('value') || 'on';
    }

    get name() {
      return this.getAttribute('name');
    }

    _syncAll() {
      this._labelText.textContent = this.getAttribute('label') || '';
      this._input.name = this.getAttribute('name') || '';
      this._input.value = this.getAttribute('value') || 'on';
      this._input.checked = this.hasAttribute('checked');
      this._input.disabled = this.hasAttribute('disabled');
      this._syncFormValue();
    }

    _syncFormValue() {
      if (this._input.checked) {
        this._internals.setFormValue(this.getAttribute('value') || 'on');
      } else {
        this._internals.setFormValue(null);
      }
    }

    _onClick(e) {
      if (this.hasAttribute('disabled')) return;
      var origin = e.composedPath ? e.composedPath()[0] : e.target;
      if (origin === this._input) return;
      this._input.checked = !this._input.checked;
      this._input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    _onChange(e) {
      e.stopPropagation();
      if (this._input.checked) {
        this.setAttribute('checked', '');
      } else {
        this.removeAttribute('checked');
      }
      this._syncFormValue();
      this.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    }
  }

  customElements.define('canvas-checkbox', CanvasCheckbox);
}

if (!customElements.get('canvas-chip')) {
  class CanvasChip extends HTMLElement {

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: inline-flex;
            vertical-align: baseline;
          }

          span {
            display: inline-flex;
            align-items: center;
            gap: .4em;
            line-height: 1;
            margin: 0 .14285714em;
            padding: var(--canvas-chip-padding, .5833em .708em .5833em .833em);
            font-weight: var(--canvas-chip-font-weight, var(--font-weight-bold, 700));
            font-family: var(--canvas-chip-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
            font-size: var(--canvas-chip-font-size, .85714286rem);
            border: var(--canvas-chip-border, 0 solid transparent);
            border-radius: var(--canvas-chip-radius, var(--radius, .28571429rem));
            background: var(--canvas-chip-bg, #e8e8e8);
            color: var(--canvas-chip-color, rgba(0, 0, 0, 0.6));
            white-space: nowrap;
            transition: background 0.1s ease;
          }

          /* Solid colors */
          :host([color="red"]) span { background: var(--canvas-chip-red-bg, var(--palette-red, #db2828)); color: var(--canvas-chip-red-color, #fff); }
          :host([color="orange"]) span { background: var(--canvas-chip-orange-bg, var(--palette-orange, #f2711c)); color: var(--canvas-chip-orange-color, #fff); }
          :host([color="yellow"]) span { background: var(--canvas-chip-yellow-bg, var(--palette-yellow, #fbbd08)); color: var(--canvas-chip-yellow-color, #fff); }
          :host([color="olive"]) span { background: var(--canvas-chip-olive-bg, var(--palette-olive, #b5cc18)); color: var(--canvas-chip-olive-color, #fff); }
          :host([color="green"]) span { background: var(--canvas-chip-green-bg, var(--palette-green, #21ba45)); color: var(--canvas-chip-green-color, #fff); }
          :host([color="teal"]) span { background: var(--canvas-chip-teal-bg, var(--palette-teal, #00b5ad)); color: var(--canvas-chip-teal-color, #fff); }
          :host([color="blue"]) span { background: var(--canvas-chip-blue-bg, var(--palette-blue, #2185d0)); color: var(--canvas-chip-blue-color, #fff); }
          :host([color="violet"]) span { background: var(--canvas-chip-violet-bg, var(--palette-violet, #6435c9)); color: var(--canvas-chip-violet-color, #fff); }
          :host([color="purple"]) span { background: var(--canvas-chip-purple-bg, var(--palette-purple, #a333c8)); color: var(--canvas-chip-purple-color, #fff); }
          :host([color="pink"]) span { background: var(--canvas-chip-pink-bg, var(--palette-pink, #e03997)); color: var(--canvas-chip-pink-color, #fff); }
          :host([color="brown"]) span { background: var(--canvas-chip-brown-bg, var(--palette-brown, #a5673f)); color: var(--canvas-chip-brown-color, #fff); }
          :host([color="grey"]) span { background: var(--canvas-chip-grey-bg, var(--palette-grey, #767676)); color: var(--canvas-chip-grey-color, #fff); }
          :host([color="black"]) span { background: var(--canvas-chip-black-bg, var(--palette-black, #1b1c1d)); color: var(--canvas-chip-black-color, #fff); }

          /* Sizes */
          :host([size="mini"]) span { font-size: var(--canvas-chip-font-size-mini, .64285714rem); }
          :host([size="tiny"]) span { font-size: var(--canvas-chip-font-size-tiny, .71428571rem); }
          :host([size="small"]) span { font-size: var(--canvas-chip-font-size-small, .78571429rem); }

          /* Basic variant */
          :host([basic]) span {
            background: #fff;
            border: 1px solid rgba(34, 36, 38, 0.15);
            color: rgba(0, 0, 0, 0.87);
          }
          :host([basic][color="red"]) span { background: #fff; color: var(--canvas-chip-red-bg, var(--palette-red, #db2828)); border-color: var(--canvas-chip-red-bg, var(--palette-red, #db2828)); }
          :host([basic][color="orange"]) span { background: #fff; color: var(--canvas-chip-orange-bg, var(--palette-orange, #f2711c)); border-color: var(--canvas-chip-orange-bg, var(--palette-orange, #f2711c)); }
          :host([basic][color="yellow"]) span { background: #fff; color: var(--canvas-chip-yellow-bg, var(--palette-yellow, #fbbd08)); border-color: var(--canvas-chip-yellow-bg, var(--palette-yellow, #fbbd08)); }
          :host([basic][color="olive"]) span { background: #fff; color: var(--canvas-chip-olive-bg, var(--palette-olive, #b5cc18)); border-color: var(--canvas-chip-olive-bg, var(--palette-olive, #b5cc18)); }
          :host([basic][color="green"]) span { background: #fff; color: var(--canvas-chip-green-bg, var(--palette-green, #21ba45)); border-color: var(--canvas-chip-green-bg, var(--palette-green, #21ba45)); }
          :host([basic][color="teal"]) span { background: #fff; color: var(--canvas-chip-teal-bg, var(--palette-teal, #00b5ad)); border-color: var(--canvas-chip-teal-bg, var(--palette-teal, #00b5ad)); }
          :host([basic][color="blue"]) span { background: #fff; color: var(--canvas-chip-blue-bg, var(--palette-blue, #2185d0)); border-color: var(--canvas-chip-blue-bg, var(--palette-blue, #2185d0)); }
          :host([basic][color="violet"]) span { background: #fff; color: var(--canvas-chip-violet-bg, var(--palette-violet, #6435c9)); border-color: var(--canvas-chip-violet-bg, var(--palette-violet, #6435c9)); }
          :host([basic][color="purple"]) span { background: #fff; color: var(--canvas-chip-purple-bg, var(--palette-purple, #a333c8)); border-color: var(--canvas-chip-purple-bg, var(--palette-purple, #a333c8)); }
          :host([basic][color="pink"]) span { background: #fff; color: var(--canvas-chip-pink-bg, var(--palette-pink, #e03997)); border-color: var(--canvas-chip-pink-bg, var(--palette-pink, #e03997)); }
          :host([basic][color="brown"]) span { background: #fff; color: var(--canvas-chip-brown-bg, var(--palette-brown, #a5673f)); border-color: var(--canvas-chip-brown-bg, var(--palette-brown, #a5673f)); }
          :host([basic][color="grey"]) span { background: #fff; color: var(--canvas-chip-grey-bg, var(--palette-grey, #767676)); border-color: var(--canvas-chip-grey-bg, var(--palette-grey, #767676)); }
          :host([basic][color="black"]) span { background: #fff; color: var(--canvas-chip-black-bg, var(--palette-black, #1b1c1d)); border-color: var(--canvas-chip-black-bg, var(--palette-black, #1b1c1d)); }

          /* Dismiss button */
          .dismiss {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1em;
            height: 1em;
            padding: 0;
            border: none;
            background: transparent;
            color: inherit;
            opacity: 0.7;
            cursor: pointer;
            line-height: 1;
            transition: opacity 0.1s ease;
            flex-shrink: 0;
          }

          .dismiss:hover { opacity: 1; }
          .dismiss svg { display: block; }

        </style>
        <span part="chip">
          <slot></slot>
          <button class="dismiss" aria-label="Dismiss">
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
              <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </button>
        </span>
      `;
      this._dismiss = this.shadowRoot.querySelector('.dismiss');
    }

    connectedCallback() {
      this._dismiss.addEventListener('click', this._handleDismiss.bind(this));
    }

    disconnectedCallback() {
      this._dismiss.removeEventListener('click', this._handleDismiss.bind(this));
    }

    _handleDismiss(e) {
      e.stopPropagation();
      this.dispatchEvent(new CustomEvent('dismiss', { bubbles: true, composed: true }));
    }
  }

  customElements.define('canvas-chip', CanvasChip);
}

/* canvas-option: shared marker element used by dropdown, combobox, and multi-select */
if (!customElements.get('canvas-option')) {
  class CanvasOption extends HTMLElement {
    constructor() { super(); }
    connectedCallback() { this.style.display = 'none'; }
  }
  customElements.define('canvas-option', CanvasOption);
}

/* canvas-combobox: searchable single-select dropdown with type-to-filter */
if (!customElements.get('canvas-combobox')) {
  class CanvasCombobox extends HTMLElement {
    static get observedAttributes() {
      return ['label', 'placeholder', 'value', 'disabled', 'required', 'error', 'name'];
    }

    static get formAssociated() { return true; }

    constructor() {
      super();
      this._internals = this.attachInternals();
      this.attachShadow({ mode: 'open', delegatesFocus: true });
      this._options = [];
      this._highlighted = -1;
      this._selectedValue = null;
      this._selectedText = '';
      this._previousText = '';
      this._open = false;
      this._onDocClick = this._onDocClick.bind(this);
    }

    connectedCallback() {
      var self = this;
      setTimeout(function() {
        self._readOptions();
        self._render();
        self._bindEvents();
      }, 0);
      document.addEventListener('click', this._onDocClick);
    }

    disconnectedCallback() {
      document.removeEventListener('click', this._onDocClick);
    }

    attributeChangedCallback(name) {
      if (name === 'value') {
        var val = this.getAttribute('value');
        if (val !== this._selectedValue) this._selectByValue(val, true);
      }
      if (name === 'label' || name === 'placeholder' || name === 'error' || name === 'disabled') {
        if (this.shadowRoot.querySelector('.combobox')) {
          this._render();
          this._bindEvents();
        }
      }
    }

    get value() { return this._selectedValue || ''; }
    set value(v) {
      this._selectByValue(v, true);
      this.setAttribute('value', v || '');
    }

    get name() { return this.getAttribute('name'); }

    _readOptions() {
      this._options = [];
      var opts = this.querySelectorAll('canvas-option');
      for (var i = 0; i < opts.length; i++) {
        var opt = opts[i];
        this._options.push({
          value: opt.getAttribute('value') || opt.textContent.trim(),
          label: opt.getAttribute('label') || opt.textContent.trim(),
          html: opt.innerHTML,
          disabled: opt.hasAttribute('disabled'),
          selected: opt.hasAttribute('selected')
        });
      }
      var preselected = this._options.find(function(o) { return o.selected; });
      if (preselected) {
        this._selectedValue = preselected.value;
        this._selectedText = preselected.label;
        this._previousText = preselected.label;
        this._internals.setFormValue(preselected.value);
      }
    }

    _render() {
      var label = this.getAttribute('label');
      var placeholder = this.getAttribute('placeholder') || '';
      var error = this.getAttribute('error');
      var disabled = this.hasAttribute('disabled');
      var displayText = this._selectedText || '';

      var optionsHtml = '';
      for (var i = 0; i < this._options.length; i++) {
        var o = this._options[i];
        var classes = 'option';
        if (o.value === this._selectedValue) classes += ' selected';
        var attrs = 'role="option" data-value="' + o.value + '" data-index="' + i + '"';
        if (o.disabled) attrs += ' aria-disabled="true"';
        if (o.value === this._selectedValue) attrs += ' aria-selected="true"';
        optionsHtml += '<li class="' + classes + '" ' + attrs + '>' + o.html + '</li>';
      }

      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          .label { display: block; margin-bottom: .28571429rem; font-size: .92857143em; font-weight: 700; font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif); color: var(--color-text, rgba(0, 0, 0, 0.87)); line-height: 1em; }
          :host([error]) .label { color: #9f3a38; }
          .combobox { position: relative; width: 100%; }
          .input {
            width: 100%; margin: 0; padding: .67857143em 2.1em .67857143em 1em;
            font-size: 1em; font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            line-height: 1.21428571em; color: var(--color-text, rgba(0, 0, 0, 0.87));
            background: var(--color-surface, #FFFFFF);
            border: 1px solid rgba(34, 36, 38, 0.15);
            border-radius: var(--radius, .28571429rem);
            outline: none; box-sizing: border-box;
            transition: border-color 0.1s ease, box-shadow 0.1s ease, border-radius 0.1s ease;
          }
          .input:focus { border-color: #96c8da; }
          .input.open { border-color: #96c8da; border-bottom-color: transparent; border-radius: var(--radius, .28571429rem) var(--radius, .28571429rem) 0 0; z-index: 10; }
          .input.open.flip { border-color: #96c8da; border-top-color: transparent; border-radius: 0 0 var(--radius, .28571429rem) var(--radius, .28571429rem); }
          :host([disabled]) .input { opacity: 0.45; cursor: default; pointer-events: none; }
          :host([error]) .input { background: #fff6f6; border-color: #e0b4b4; }
          .arrow { position: absolute; right: 1em; top: 50%; transform: translateY(-50%); width: 8px; height: 5px; pointer-events: none; }
          .menu {
            display: none; position: absolute; top: calc(100% - 1px); left: 0; right: 0;
            max-height: 16.02857143rem; overflow-y: auto;
            background: var(--color-surface, #FFFFFF);
            border: 1px solid #96c8da; border-top: none;
            border-radius: 0 0 var(--radius, .28571429rem) var(--radius, .28571429rem);
            box-shadow: 0 0px 3px 0 rgba(34, 36, 38, 0.06);
            z-index: 11; list-style: none; margin: 0; padding: 0;
          }
          .menu.visible { display: block; }
          .menu.flip {
            bottom: 100%; top: auto;
            border-top: 1px solid #96c8da; border-bottom: none;
            border-radius: var(--radius, .28571429rem) var(--radius, .28571429rem) 0 0;
            box-shadow: 0 0px 3px 0 rgba(34, 36, 38, 0.06);
          }
          .option {
            padding: .78571429rem 1.14285714rem; font-size: 1rem; line-height: 1.0625rem;
            color: var(--color-text, rgba(0, 0, 0, 0.87)); cursor: pointer;
            border-top: 1px solid #fafafa; transition: background 0.1s ease;
          }
          .option:first-child { border-top: none; }
          .option:hover, .option.highlighted { background: rgba(0, 0, 0, 0.05); color: rgba(0, 0, 0, 0.95); }
          .option.selected { background: rgba(0, 0, 0, 0.05); color: rgba(0, 0, 0, 0.95); font-weight: 700; }
          .option[aria-disabled="true"] { color: #767676; cursor: not-allowed; }
          .option[aria-disabled="true"]:hover { background: transparent; }
          .option.hidden { display: none; }
          .empty { padding: .78571429rem 1.14285714rem; font-size: 1rem; color: rgba(0, 0, 0, 0.4); display: none; }
          .empty.visible { display: block; }
          .error-text { margin-top: .28571429rem; font-size: .92857143em; font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif); color: #9f3a38; line-height: 1.4285em; }
        </style>
        ${label ? '<span class="label">' + label + '</span>' : ''}
        <div class="combobox">
          <input class="input" type="text" role="combobox"
            aria-autocomplete="list" aria-expanded="false" aria-controls="listbox"
            placeholder="${placeholder}" value="${displayText}"
            ${disabled ? 'disabled' : ''}>
          <svg class="arrow" viewBox="0 0 10 6" fill="#575757"><path d="M1 0h8a1 1 0 01.7 1.7l-4 4a1 1 0 01-1.4 0l-4-4A1 1 0 011 0z"/></svg>
          <ul class="menu" id="listbox" role="listbox">
            ${optionsHtml}
            <li class="empty">No results</li>
          </ul>
        </div>
        ${error ? '<span class="error-text">' + error + '</span>' : ''}
      `;
    }

    _bindEvents() {
      var self = this;
      var input = this.shadowRoot.querySelector('.input');
      var menu = this.shadowRoot.querySelector('.menu');

      input.addEventListener('click', function() {
        if (self.hasAttribute('disabled')) return;
        if (!self._open) self._openMenu();
      });

      input.addEventListener('input', function() {
        if (!self._open) self._openMenu();
        self._filter(input.value);
      });

      input.addEventListener('keydown', function(e) {
        if (self.hasAttribute('disabled')) return;
        switch (e.key) {
          case 'ArrowDown':
            e.preventDefault();
            if (!self._open) self._openMenu();
            self._highlightNext(1);
            break;
          case 'ArrowUp':
            e.preventDefault();
            if (!self._open) self._openMenu();
            self._highlightNext(-1);
            break;
          case 'Enter':
            e.preventDefault();
            if (!self._open) {
              self._openMenu();
            } else if (self._highlighted >= 0) {
              var visible = self._getVisibleOptions();
              if (visible[self._highlighted]) {
                self._selectByValue(visible[self._highlighted].dataset.value, false);
                self._close();
              }
            }
            break;
          case 'Escape':
            e.preventDefault();
            self._restore();
            self._close();
            break;
          case 'Home':
            if (self._open) { e.preventDefault(); self._highlightIndex(0); }
            break;
          case 'End':
            if (self._open) {
              e.preventDefault();
              var visible = self._getVisibleOptions();
              self._highlightIndex(visible.length - 1);
            }
            break;
          case 'Tab':
            if (self._open) {
              if (self._highlighted >= 0) {
                var visible = self._getVisibleOptions();
                if (visible[self._highlighted]) self._selectByValue(visible[self._highlighted].dataset.value, false);
              } else {
                self._restore();
              }
              self._close();
            }
            break;
        }
      });

      menu.addEventListener('click', function(e) {
        var opt = e.target.closest('.option');
        if (!opt) return;
        if (opt.getAttribute('aria-disabled') === 'true') return;
        self._selectByValue(opt.dataset.value, false);
        self._close();
        input.focus();
      });
    }

    _openMenu() {
      this._open = true;
      this._highlighted = -1;
      this._previousText = this._selectedText;
      var input = this.shadowRoot.querySelector('.input');
      var menu = this.shadowRoot.querySelector('.menu');
      input.classList.add('open');
      input.setAttribute('aria-expanded', 'true');
      menu.classList.add('visible');
      this._showAll();
      this._checkFlip();
    }

    _close() {
      this._open = false;
      this._highlighted = -1;
      var input = this.shadowRoot.querySelector('.input');
      var menu = this.shadowRoot.querySelector('.menu');
      input.classList.remove('open', 'flip');
      input.setAttribute('aria-expanded', 'false');
      menu.classList.remove('visible', 'flip');
      this._clearHighlight();
      this._showAll();
    }

    _restore() {
      var input = this.shadowRoot.querySelector('.input');
      input.value = this._previousText;
    }

    _onDocClick(e) {
      if (!this.contains(e.target) && !this.shadowRoot.contains(e.target)) {
        if (this._open) {
          this._restore();
          this._close();
        }
      }
    }

    _filter(query) {
      var q = query.toLowerCase();
      var items = this.shadowRoot.querySelectorAll('.option');
      var anyVisible = false;
      for (var i = 0; i < items.length; i++) {
        var label = this._options[items[i].dataset.index].label.toLowerCase();
        if (label.indexOf(q) >= 0) {
          items[i].classList.remove('hidden');
          anyVisible = true;
        } else {
          items[i].classList.add('hidden');
        }
      }
      var empty = this.shadowRoot.querySelector('.empty');
      if (anyVisible) {
        empty.classList.remove('visible');
      } else {
        empty.classList.add('visible');
      }
      this._highlighted = -1;
      this._clearHighlight();
    }

    _showAll() {
      var items = this.shadowRoot.querySelectorAll('.option');
      for (var i = 0; i < items.length; i++) items[i].classList.remove('hidden');
      var empty = this.shadowRoot.querySelector('.empty');
      empty.classList.remove('visible');
    }

    _checkFlip() {
      var menu = this.shadowRoot.querySelector('.menu');
      var input = this.shadowRoot.querySelector('.input');
      var rect = menu.getBoundingClientRect();
      if (rect.bottom > window.innerHeight) {
        menu.classList.add('flip');
        input.classList.add('flip');
      }
    }

    _selectByValue(val, silent) {
      var opt = this._options.find(function(o) { return o.value === val; });
      if (!opt || opt.disabled) return;
      this._selectedValue = opt.value;
      this._selectedText = opt.label;
      this._previousText = opt.label;
      this._internals.setFormValue(opt.value);

      var input = this.shadowRoot.querySelector('.input');
      if (input) input.value = opt.label;

      var items = this.shadowRoot.querySelectorAll('.option');
      for (var i = 0; i < items.length; i++) {
        if (items[i].dataset.value === val) {
          items[i].classList.add('selected');
          items[i].setAttribute('aria-selected', 'true');
        } else {
          items[i].classList.remove('selected');
          items[i].removeAttribute('aria-selected');
        }
      }

      if (!silent) {
        this.dispatchEvent(new CustomEvent('change', { bubbles: true, composed: true }));
      }
    }

    _getVisibleOptions() {
      return this.shadowRoot.querySelectorAll('.option:not(.hidden):not([aria-disabled="true"])');
    }

    _highlightNext(dir) {
      var opts = this._getVisibleOptions();
      if (opts.length === 0) return;
      this._highlighted += dir;
      if (this._highlighted < 0) this._highlighted = opts.length - 1;
      if (this._highlighted >= opts.length) this._highlighted = 0;
      this._applyHighlight(opts);
    }

    _highlightIndex(index) {
      var opts = this._getVisibleOptions();
      if (index < 0 || index >= opts.length) return;
      this._highlighted = index;
      this._applyHighlight(opts);
    }

    _applyHighlight(opts) {
      this._clearHighlight();
      if (this._highlighted >= 0 && opts[this._highlighted]) {
        opts[this._highlighted].classList.add('highlighted');
        opts[this._highlighted].scrollIntoView({ block: 'nearest' });
      }
    }

    _clearHighlight() {
      var items = this.shadowRoot.querySelectorAll('.option.highlighted');
      for (var i = 0; i < items.length; i++) items[i].classList.remove('highlighted');
    }
  }

  customElements.define('canvas-combobox', CanvasCombobox);
}

if (!customElements.get('canvas-option')) {
  class CanvasOption extends HTMLElement {
    constructor() { super(); }
    connectedCallback() { this.style.display = 'none'; }
  }
  customElements.define('canvas-option', CanvasOption);
}

if (!customElements.get('canvas-dropdown')) {
  class CanvasDropdown extends HTMLElement {
    static get observedAttributes() {
      return ['label', 'placeholder', 'value', 'disabled', 'required', 'error', 'name', 'size'];
    }

    static get formAssociated() { return true; }

    constructor() {
      super();
      this._internals = this.attachInternals();
      this.attachShadow({ mode: 'open' });
      this._options = [];
      this._highlighted = -1;
      this._selectedValue = null;
      this._selectedText = '';
      this._open = false;
      this._onDocClick = this._onDocClick.bind(this);
    }

    connectedCallback() {
      var self = this;
      setTimeout(function() {
        self._readOptions();
        self._render();
        self._bindEvents();
      }, 0);
      document.addEventListener('click', this._onDocClick);
    }

    disconnectedCallback() {
      document.removeEventListener('click', this._onDocClick);
    }

    attributeChangedCallback(name) {
      if (name === 'value') {
        var val = this.getAttribute('value');
        if (val !== this._selectedValue) this._selectByValue(val);
      }
      if (name === 'label' || name === 'placeholder' || name === 'error' || name === 'disabled') {
        if (this.shadowRoot.querySelector('.dropdown')) {
          this._render();
          this._bindEvents();
        }
      }
    }

    get value() { return this._selectedValue || ''; }
    set value(v) {
      this._selectByValue(v);
      this.setAttribute('value', v || '');
    }

    get name() { return this.getAttribute('name'); }

    _readOptions() {
      this._options = [];
      var opts = this.querySelectorAll('canvas-option');
      for (var i = 0; i < opts.length; i++) {
        var opt = opts[i];
        this._options.push({
          value: opt.getAttribute('value') || opt.textContent.trim(),
          label: opt.getAttribute('label') || opt.textContent.trim(),
          html: opt.innerHTML,
          disabled: opt.hasAttribute('disabled'),
          selected: opt.hasAttribute('selected')
        });
      }
      var preselected = this._options.find(function(o) { return o.selected; });
      if (preselected) {
        this._selectedValue = preselected.value;
        this._selectedText = preselected.label;
        this._internals.setFormValue(preselected.value);
      }
    }

    _render() {
      var label = this.getAttribute('label');
      var placeholder = this.getAttribute('placeholder') || '';
      var error = this.getAttribute('error');
      var disabled = this.hasAttribute('disabled');
      var displayText = this._selectedText || '';
      var isPlaceholder = !displayText;

      var optionsHtml = '';
      for (var i = 0; i < this._options.length; i++) {
        var o = this._options[i];
        var classes = 'option';
        if (o.value === this._selectedValue) classes += ' selected';
        var attrs = 'role="option" data-value="' + o.value + '" data-index="' + i + '"';
        if (o.disabled) attrs += ' aria-disabled="true"';
        if (o.value === this._selectedValue) attrs += ' aria-selected="true"';
        optionsHtml += '<li class="' + classes + '" ' + attrs + '>' + o.html + '</li>';
      }

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
          }

          .label {
            display: block;
            margin-bottom: .28571429rem;
            font-size: .92857143em;
            font-weight: 700;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            color: var(--color-text, rgba(0, 0, 0, 0.87));
            line-height: 1em;
          }

          :host([error]) .label { color: #9f3a38; }

          .dropdown {
            position: relative;
            display: flex;
            align-items: center;
            width: 100%;
            padding: .67857143em 2.1em .67857143em 1em;
            font-size: 1em;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            line-height: 1.21428571em;
            color: var(--color-text, rgba(0, 0, 0, 0.87));
            background: var(--color-surface, #FFFFFF);
            border: 1px solid rgba(34, 36, 38, 0.15);
            border-radius: var(--radius, .28571429rem);
            cursor: pointer;
            outline: none;
            transition: border-color 0.1s ease, box-shadow 0.1s ease, border-radius 0.1s ease;
            box-sizing: border-box;
          }

          .dropdown:focus {
            border-color: #96c8da;
          }

          .dropdown.open {
            border-color: #96c8da;
            border-bottom-color: transparent;
            border-radius: var(--radius, .28571429rem) var(--radius, .28571429rem) 0 0;
            z-index: 10;
          }

          :host([size="sm"]) .dropdown {
            font-size: .75em;
          }

          :host([disabled]) .dropdown {
            opacity: 0.45;
            cursor: default;
            pointer-events: none;
          }

          :host([error]) .dropdown {
            background: #fff6f6;
            border-color: #e0b4b4;
          }

          .text {
            flex: 1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: var(--color-text, rgba(0, 0, 0, 0.87));
          }

          .text.placeholder {
            color: rgba(191, 191, 191, 0.87);
          }

          .arrow {
            position: absolute;
            top: 50%;
            right: 1em;
            transform: translateY(-50%);
            width: 0;
            height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid rgba(0, 0, 0, 0.8);
            pointer-events: none;
          }

          .menu {
            display: none;
            position: absolute;
            top: 100%;
            left: -1px;
            right: -1px;
            max-height: 16.02857143rem;
            overflow-y: auto;
            background: var(--color-surface, #FFFFFF);
            border: 1px solid #96c8da;
            border-top: none;
            border-radius: 0 0 var(--radius, .28571429rem) var(--radius, .28571429rem);
            box-shadow: 0 0px 3px 0 rgba(34, 36, 38, 0.06);
            z-index: 11;
            list-style: none;
            margin: 0;
            padding: 0;
          }

          .dropdown.open .menu {
            display: block;
          }

          .option {
            padding: .78571429rem 1.14285714rem;
            font-size: 1rem;
            line-height: 1.0625rem;
            color: var(--color-text, rgba(0, 0, 0, 0.87));
            cursor: pointer;
            border-top: 1px solid #fafafa;
            transition: background 0.1s ease;
          }

          .option:first-child { border-top: none; }

          .option:hover,
          .option.highlighted {
            background: rgba(0, 0, 0, 0.05);
            color: rgba(0, 0, 0, 0.95);
          }

          .option.selected {
            background: rgba(0, 0, 0, 0.05);
            color: rgba(0, 0, 0, 0.95);
            font-weight: 700;
          }

          .option[aria-disabled="true"] {
            color: #767676;
            cursor: not-allowed;
          }

          .option[aria-disabled="true"]:hover {
            background: transparent;
          }

          .error-text {
            margin-top: .28571429rem;
            font-size: .92857143em;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            color: #9f3a38;
            line-height: 1.4285em;
          }
        </style>
        ${label ? '<span class="label">' + label + '</span>' : ''}
        <div class="dropdown" tabindex="${disabled ? '-1' : '0'}" role="combobox" aria-expanded="false" aria-haspopup="listbox">
          <span class="text${isPlaceholder ? ' placeholder' : ''}">${isPlaceholder ? placeholder : displayText}</span>
          <span class="arrow"></span>
          <ul class="menu" role="listbox">${optionsHtml}</ul>
        </div>
        ${error ? '<span class="error-text">' + error + '</span>' : ''}
      `;
    }

    _bindEvents() {
      var self = this;
      var dd = this.shadowRoot.querySelector('.dropdown');

      dd.addEventListener('click', function(e) {
        if (self.hasAttribute('disabled')) return;
        var opt = e.target.closest('.option');
        if (opt) {
          if (opt.getAttribute('aria-disabled') === 'true') return;
          self._selectByValue(opt.dataset.value);
          self._close();
        } else {
          if (self._open) self._close();
          else self._openMenu();
        }
      });

      dd.addEventListener('keydown', function(e) {
        if (self.hasAttribute('disabled')) return;
        switch (e.key) {
          case 'ArrowDown':
            e.preventDefault();
            if (!self._open) self._openMenu();
            self._highlightNext(1);
            break;
          case 'ArrowUp':
            e.preventDefault();
            if (!self._open) self._openMenu();
            self._highlightNext(-1);
            break;
          case 'Enter':
          case ' ':
            e.preventDefault();
            if (!self._open) {
              self._openMenu();
            } else if (self._highlighted >= 0) {
              var opts = self.shadowRoot.querySelectorAll('.option:not([aria-disabled="true"])');
              if (opts[self._highlighted]) {
                self._selectByValue(opts[self._highlighted].dataset.value);
                self._close();
              }
            }
            break;
          case 'Escape':
            e.preventDefault();
            self._close();
            break;
          case 'Home':
            if (self._open) {
              e.preventDefault();
              self._highlightIndex(0);
            }
            break;
          case 'End':
            if (self._open) {
              e.preventDefault();
              var opts = self.shadowRoot.querySelectorAll('.option:not([aria-disabled="true"])');
              self._highlightIndex(opts.length - 1);
            }
            break;
          case 'Tab':
            if (self._open) {
              if (self._highlighted >= 0) {
                var opts = self.shadowRoot.querySelectorAll('.option:not([aria-disabled="true"])');
                if (opts[self._highlighted]) {
                  self._selectByValue(opts[self._highlighted].dataset.value);
                }
              }
              self._close();
            }
            break;
        }
      });
    }

    _openMenu() {
      this._open = true;
      this._highlighted = -1;
      var dd = this.shadowRoot.querySelector('.dropdown');
      dd.classList.add('open');
      dd.setAttribute('aria-expanded', 'true');
    }

    _close() {
      this._open = false;
      this._highlighted = -1;
      var dd = this.shadowRoot.querySelector('.dropdown');
      dd.classList.remove('open');
      dd.setAttribute('aria-expanded', 'false');
      this._clearHighlight();
    }

    _onDocClick(e) {
      if (!this.contains(e.target) && !this.shadowRoot.contains(e.target)) {
        if (this._open) this._close();
      }
    }

    _selectByValue(val) {
      var opt = this._options.find(function(o) { return o.value === val; });
      if (!opt || opt.disabled) return;
      this._selectedValue = opt.value;
      this._selectedText = opt.label;
      this._internals.setFormValue(opt.value);

      var text = this.shadowRoot.querySelector('.text');
      if (text) {
        text.textContent = opt.label;
        text.classList.remove('placeholder');
      }

      var items = this.shadowRoot.querySelectorAll('.option');
      for (var i = 0; i < items.length; i++) {
        if (items[i].dataset.value === val) {
          items[i].classList.add('selected');
          items[i].setAttribute('aria-selected', 'true');
        } else {
          items[i].classList.remove('selected');
          items[i].removeAttribute('aria-selected');
        }
      }

      this.dispatchEvent(new CustomEvent('change', { bubbles: true, composed: true }));
    }

    _highlightNext(dir) {
      var opts = this.shadowRoot.querySelectorAll('.option:not([aria-disabled="true"])');
      if (opts.length === 0) return;
      this._highlighted += dir;
      if (this._highlighted < 0) this._highlighted = opts.length - 1;
      if (this._highlighted >= opts.length) this._highlighted = 0;
      this._applyHighlight(opts);
    }

    _highlightIndex(index) {
      var opts = this.shadowRoot.querySelectorAll('.option:not([aria-disabled="true"])');
      if (index < 0 || index >= opts.length) return;
      this._highlighted = index;
      this._applyHighlight(opts);
    }

    _applyHighlight(opts) {
      this._clearHighlight();
      if (this._highlighted >= 0 && opts[this._highlighted]) {
        opts[this._highlighted].classList.add('highlighted');
        opts[this._highlighted].scrollIntoView({ block: 'nearest' });
        var dd = this.shadowRoot.querySelector('.dropdown');
        dd.setAttribute('aria-activedescendant', 'opt-' + this._highlighted);
      }
    }

    _clearHighlight() {
      var items = this.shadowRoot.querySelectorAll('.option.highlighted');
      for (var i = 0; i < items.length; i++) {
        items[i].classList.remove('highlighted');
      }
      var dd = this.shadowRoot.querySelector('.dropdown');
      if (dd) dd.removeAttribute('aria-activedescendant');
    }
  }

  customElements.define('canvas-dropdown', CanvasDropdown);
}

if (!customElements.get('canvas-input')) {
  class CanvasInput extends HTMLElement {
    static get observedAttributes() {
      return ['label', 'placeholder', 'multiline', 'rows', 'required', 'error', 'disabled', 'value', 'name', 'type'];
    }

    static formAssociated = true;

    constructor() {
      super();
      this._internals = this.attachInternals();
      this.attachShadow({ mode: 'open', delegatesFocus: true });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
          }

          label {
            display: none;
            margin: 0 0 .28571429rem 0;
            font-size: var(--canvas-input-label-font-size, .92857143em);
            font-weight: var(--canvas-input-label-font-weight, var(--font-weight-bold, 700));
            font-family: var(--canvas-input-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
            color: var(--canvas-input-label-color, var(--color-text, rgba(0, 0, 0, 0.87)));
            text-transform: none;
            line-height: 1em;
          }

          :host([label]) label { display: block; }

          input, textarea {
            width: 100%;
            padding: var(--canvas-input-padding, .67857143em 1em);
            font-size: var(--canvas-input-font-size, 1em);
            font-family: var(--canvas-input-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
            line-height: var(--canvas-input-line-height, 1.21428571em);
            color: var(--canvas-input-color, var(--color-text, rgba(0, 0, 0, 0.87)));
            background: var(--canvas-input-bg, var(--color-surface, #FFFFFF));
            border: var(--canvas-input-border, 1px solid rgba(34, 36, 38, 0.15));
            border-radius: var(--canvas-input-radius, var(--radius, .28571429rem));
            transition: border-color 0.1s ease, box-shadow 0.1s ease;
            box-shadow: none;
            outline: 0;
            box-sizing: border-box;
          }

          input:focus, textarea:focus {
            border-color: var(--canvas-input-focus-border, #85b7d9);
            background: var(--canvas-input-bg, var(--color-surface, #FFFFFF));
            color: rgba(0, 0, 0, 0.8);
            box-shadow: none;
            outline: none;
          }

          input::placeholder, textarea::placeholder {
            color: var(--canvas-input-placeholder, rgba(191, 191, 191, 0.87));
          }

          input:focus::placeholder, textarea:focus::placeholder {
            color: var(--canvas-input-focus-placeholder, rgba(115, 115, 115, 0.87));
          }

          input:disabled, textarea:disabled {
            background: var(--canvas-input-disabled-bg, var(--color-bg, #F5F5F5));
            cursor: not-allowed;
          }

          textarea {
            min-height: var(--canvas-input-textarea-min-height, 80px);
            resize: vertical;
          }

          :host(:not([multiline])) textarea { display: none; }
          :host([multiline]) input { display: none; }

          /* Error state */
          .error-msg {
            display: none;
            font-size: .92857143em;
            color: var(--canvas-input-error-text, #9f3a38);
            line-height: 1em;
            font-weight: var(--canvas-input-label-font-weight, var(--font-weight-bold, 700));
            font-family: var(--canvas-input-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
            margin-top: .28571429rem;
          }

          :host([error]) .error-msg { display: block; }

          :host([error]) label {
            color: var(--canvas-input-error-text, #9f3a38);
          }

          :host([error]) input,
          :host([error]) textarea {
            background: var(--canvas-input-error-bg, #fff6f6);
            border-color: var(--canvas-input-error-border, #e0b4b4);
            color: var(--canvas-input-error-text, #9f3a38);
          }

          :host([error]) input::placeholder,
          :host([error]) textarea::placeholder {
            color: var(--canvas-input-error-border, #e0b4b4);
          }
        </style>
        <label part="label"></label>
        <input part="input" type="text">
        <textarea part="textarea"></textarea>
        <span class="error-msg" part="error" aria-live="polite"></span>
      `;
      this._label = this.shadowRoot.querySelector('label');
      this._input = this.shadowRoot.querySelector('input');
      this._textarea = this.shadowRoot.querySelector('textarea');
      this._errorMsg = this.shadowRoot.querySelector('.error-msg');
      this._boundOnInput = this._onInput.bind(this);
      this._boundOnChange = this._onChange.bind(this);
    }

    connectedCallback() {
      this._input.addEventListener('input', this._boundOnInput);
      this._input.addEventListener('change', this._boundOnChange);
      this._textarea.addEventListener('input', this._boundOnInput);
      this._textarea.addEventListener('change', this._boundOnChange);
      this._syncAll();
    }

    disconnectedCallback() {
      this._input.removeEventListener('input', this._boundOnInput);
      this._input.removeEventListener('change', this._boundOnChange);
      this._textarea.removeEventListener('input', this._boundOnInput);
      this._textarea.removeEventListener('change', this._boundOnChange);
    }

    attributeChangedCallback(name, oldVal, newVal) {
      switch (name) {
        case 'label':
          this._label.textContent = newVal || '';
          break;
        case 'placeholder':
          this._input.placeholder = newVal || '';
          this._textarea.placeholder = newVal || '';
          break;
        case 'rows':
          this._textarea.rows = newVal || 4;
          break;
        case 'required':
          var req = this.hasAttribute('required');
          this._input.required = req;
          this._textarea.required = req;
          this._input.setAttribute('aria-required', req);
          this._textarea.setAttribute('aria-required', req);
          break;
        case 'disabled':
          var dis = this.hasAttribute('disabled');
          this._input.disabled = dis;
          this._textarea.disabled = dis;
          break;
        case 'error':
          this._syncError();
          break;
        case 'value':
          if (newVal !== null) {
            this._activeEl.value = newVal;
            this._internals.setFormValue(newVal);
          }
          break;
        case 'name':
          break;
        case 'type':
          this._input.type = newVal || 'text';
          break;
      }
    }

    get _activeEl() {
      return this.hasAttribute('multiline') ? this._textarea : this._input;
    }

    get value() {
      return this._activeEl.value;
    }

    set value(v) {
      this._activeEl.value = v;
      this._internals.setFormValue(v);
    }

    get name() {
      return this.getAttribute('name');
    }

    _syncAll() {
      this._label.textContent = this.getAttribute('label') || '';
      this._input.placeholder = this.getAttribute('placeholder') || '';
      this._textarea.placeholder = this.getAttribute('placeholder') || '';
      this._textarea.rows = this.getAttribute('rows') || 4;
      this._input.type = this.getAttribute('type') || 'text';

      var req = this.hasAttribute('required');
      this._input.required = req;
      this._textarea.required = req;
      this._input.setAttribute('aria-required', req);
      this._textarea.setAttribute('aria-required', req);

      var dis = this.hasAttribute('disabled');
      this._input.disabled = dis;
      this._textarea.disabled = dis;

      var val = this.getAttribute('value');
      if (val !== null) {
        this._input.value = val;
        this._textarea.value = val;
        this._internals.setFormValue(val);
      }

      this._syncError();
    }

    _syncError() {
      var err = this.getAttribute('error');
      if (err) {
        this._errorMsg.textContent = err;
        this._input.setAttribute('aria-invalid', 'true');
        this._textarea.setAttribute('aria-invalid', 'true');
        this._errorMsg.id = 'err';
        this._input.setAttribute('aria-describedby', 'err');
        this._textarea.setAttribute('aria-describedby', 'err');
      } else {
        this._errorMsg.textContent = '';
        this._input.removeAttribute('aria-invalid');
        this._textarea.removeAttribute('aria-invalid');
        this._input.removeAttribute('aria-describedby');
        this._textarea.removeAttribute('aria-describedby');
      }
    }

    _onInput(e) {
      e.stopPropagation();
      this._internals.setFormValue(this._activeEl.value);
      this.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    }

    _onChange(e) {
      e.stopPropagation();
      this._internals.setFormValue(this._activeEl.value);
      this.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    }
  }

  customElements.define('canvas-input', CanvasInput);
}

/*
  canvas-modal compositional API

  <canvas-modal> - overlay container. Attributes: size, persistent
  <canvas-modal-header> - optional header bar. Attributes: dismissable
  <canvas-modal-content> - optional padded content area. Attributes: flush
  <canvas-modal-footer> - optional actions footer. No attributes.

  All three inner elements are optional. Without them, children render
  directly inside the modal box with no padding or structure.
*/

/* canvas-modal-header: title bar with optional close button */
if (!customElements.get('canvas-modal-header')) {
  class CanvasModalHeader extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: flex; align-items: center; justify-content: space-between;
            padding: 1.25rem 1.5rem;
            font-size: 1.42857143rem; font-weight: 700; line-height: 1.28571429em;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            color: rgba(0, 0, 0, 0.85);
            border-bottom: 1px solid rgba(34, 36, 38, 0.15);
          }
          .title { flex: 1; }
          .close {
            display: none; align-items: center; justify-content: center;
            width: 2rem; height: 2rem; flex-shrink: 0;
            padding: 0; margin: 0 -.5rem 0 .5rem;
            background: transparent; border: none; border-radius: var(--radius, .28571429rem);
            cursor: pointer; color: rgba(0, 0, 0, 0.6);
            transition: color 0.1s ease, background 0.1s ease;
          }
          .close:hover { color: rgba(0, 0, 0, 0.87); background: rgba(0, 0, 0, 0.05); }
          .close svg { display: block; }
          :host([dismissable]) .close { display: inline-flex; }
        </style>
        <span class="title"><slot></slot></span>
        <button class="close" aria-label="Close">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M1.5 1.5l11 11M12.5 1.5l-11 11" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </button>
      `;
    }
    connectedCallback() {
      var self = this;
      this.shadowRoot.querySelector('.close').addEventListener('click', function() {
        var modal = self.closest('canvas-modal');
        if (modal) modal.dismiss();
      });
    }
  }
  customElements.define('canvas-modal-header', CanvasModalHeader);
}

/* canvas-modal-content: padded content area */
if (!customElements.get('canvas-modal-content')) {
  class CanvasModalContent extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: flex; flex-direction: column; min-height: 0;
            padding: 1.5rem;
            font-size: 1em; line-height: 1.4;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            color: var(--color-text, rgba(0, 0, 0, 0.87));
          }
          :host([flush]) { padding: 0; }
          ::slotted(*) { flex-shrink: 0; }
          ::slotted([data-fill]) { flex: 1; min-height: 0; }
        </style>
        <slot></slot>
      `;
    }
  }
  customElements.define('canvas-modal-content', CanvasModalContent);
}

/* canvas-modal-footer: actions bar */
if (!customElements.get('canvas-modal-footer')) {
  class CanvasModalFooter extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: flex; justify-content: flex-end; gap: 8px;
            padding: 1rem;
            background: #f9fafb;
            border-top: 1px solid rgba(34, 36, 38, 0.15);
            border-radius: 0 0 var(--radius, .28571429rem) var(--radius, .28571429rem);
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
          }
        </style>
        <slot></slot>
      `;
    }
  }
  customElements.define('canvas-modal-footer', CanvasModalFooter);
}

/* canvas-modal: the overlay container */
if (!customElements.get('canvas-modal')) {
  class CanvasModal extends HTMLElement {
    static get observedAttributes() {
      return ['size'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._isOpen = false;
      this._previousFocus = null;
      this._onKeyDown = this._onKeyDown.bind(this);
    }

    connectedCallback() {
      this._render();
      this._bindEvents();
    }

    attributeChangedCallback() {
      if (this.shadowRoot.querySelector('.modal')) {
        this._render();
        this._bindEvents();
      }
    }

    get isOpen() { return this._isOpen; }

    open() {
      if (this._isOpen) return;
      this._isOpen = true;
      this._previousFocus = document.activeElement;
      var backdrop = this.shadowRoot.querySelector('.backdrop');
      var scroll = this.shadowRoot.querySelector('.scroll');
      backdrop.classList.add('active');
      scroll.classList.add('active');
      document.body.style.overflow = 'hidden';
      document.addEventListener('keydown', this._onKeyDown);
      var self = this;
      requestAnimationFrame(function() { self._focusFirst(); });
      this.dispatchEvent(new CustomEvent('open', { bubbles: true, composed: true }));
    }

    dismiss() {
      if (!this._isOpen) return;
      this._isOpen = false;
      var backdrop = this.shadowRoot.querySelector('.backdrop');
      var scroll = this.shadowRoot.querySelector('.scroll');
      backdrop.classList.remove('active');
      scroll.classList.remove('active');
      document.body.style.overflow = '';
      document.removeEventListener('keydown', this._onKeyDown);
      if (this._previousFocus && this._previousFocus.focus) {
        this._previousFocus.focus();
      }
      this._previousFocus = null;
      this.dispatchEvent(new CustomEvent('dismiss', { bubbles: true, composed: true }));
    }

    _render() {
      var size = this.getAttribute('size') || 'medium';
      var sizeClass = 'modal modal-' + size;

      this.shadowRoot.innerHTML = `
        <style>
          :host { display: contents; }
          .backdrop {
            display: none; position: fixed; inset: 0;
            background-color: rgba(0, 0, 0, 0.5); z-index: 1000;
          }
          .backdrop.active { display: block; }
          .scroll {
            display: none; position: fixed; inset: 0;
            overflow-y: auto; z-index: 1001; padding: 2rem;
          }
          .scroll.active { display: flex; align-items: flex-start; justify-content: center; }
          .modal {
            position: relative;
            display: flex; flex-direction: column;
            background: var(--color-surface, #FFFFFF);
            border: none;
            border-radius: var(--radius, .28571429rem);
            box-shadow: 1px 3px 3px 0 rgba(0, 0, 0, 0.2), 1px 3px 15px 2px rgba(0, 0, 0, 0.2);
            margin: auto;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
          }
          .modal-small { width: 35rem; max-width: calc(100vw - 4rem); }
          .modal-medium { width: 52.5rem; max-width: calc(100vw - 4rem); }
          .modal-full { width: calc(100vw - 6rem); min-height: calc(100vh - 6rem); }
          ::slotted(canvas-modal-content) { flex: 1 0 auto; }
        </style>
        <div class="backdrop"></div>
        <div class="scroll">
          <div class="${sizeClass}" role="dialog" aria-modal="true">
            <slot></slot>
          </div>
        </div>
      `;
    }

    _bindEvents() {
      var self = this;
      var scroll = this.shadowRoot.querySelector('.scroll');
      scroll.addEventListener('click', function(e) {
        if (self.hasAttribute('persistent')) return;
        if (e.target === scroll) self.dismiss();
      });
    }

    _onKeyDown(e) {
      if (e.key === 'Escape') {
        if (this.hasAttribute('persistent')) return;
        e.preventDefault();
        this.dismiss();
        return;
      }
      if (e.key === 'Tab') {
        this._trapFocus(e);
      }
    }

    _getFocusable() {
      var modal = this.shadowRoot.querySelector('.modal');
      var focusable = [];
      var slot = modal.querySelector('slot');
      if (!slot) return focusable;
      var assigned = slot.assignedElements({ flatten: true });
      for (var i = 0; i < assigned.length; i++) {
        this._collectFocusable(assigned[i], focusable);
      }
      return focusable;
    }

    _collectFocusable(el, list) {
      if (this._isFocusable(el)) list.push(el);
      if (el.shadowRoot) {
        var shadowChildren = el.shadowRoot.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        for (var i = 0; i < shadowChildren.length; i++) {
          if (this._isFocusable(shadowChildren[i])) list.push(shadowChildren[i]);
        }
      }
      var children = el.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"]), canvas-button, canvas-input, canvas-dropdown, canvas-combobox, canvas-multi-select');
      for (var i = 0; i < children.length; i++) {
        this._collectFocusable(children[i], list);
      }
    }

    _isFocusable(el) {
      if (el.disabled) return false;
      if (el.tabIndex < 0) return false;
      return true;
    }

    _trapFocus(e) {
      var focusable = this._getFocusable();
      if (focusable.length === 0) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first || (first.shadowRoot && first.shadowRoot.activeElement)) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last || (last.shadowRoot && last.shadowRoot.activeElement)) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    _focusFirst() {
      var focusable = this._getFocusable();
      if (focusable.length > 0) focusable[0].focus();
    }
  }

  customElements.define('canvas-modal', CanvasModal);
}

/* canvas-option: shared marker element used by dropdown, combobox, and multi-select */
if (!customElements.get('canvas-option')) {
  class CanvasOption extends HTMLElement {
    constructor() { super(); }
    connectedCallback() { this.style.display = 'none'; }
  }
  customElements.define('canvas-option', CanvasOption);
}

/* canvas-multi-select: multi-value select with chips, type-to-filter, and form association */
if (!customElements.get('canvas-multi-select')) {
  class CanvasMultiSelect extends HTMLElement {
    static get observedAttributes() {
      return ['label', 'placeholder', 'disabled', 'required', 'error', 'name'];
    }

    static get formAssociated() { return true; }

    constructor() {
      super();
      this._internals = this.attachInternals();
      this.attachShadow({ mode: 'open', delegatesFocus: true });
      this._options = [];
      this._selected = [];
      this._highlighted = -1;
      this._open = false;
      this._onDocClick = this._onDocClick.bind(this);
    }

    connectedCallback() {
      var self = this;
      setTimeout(function() {
        self._readOptions();
        self._render();
        self._bindEvents();
        self._updateFormValue();
      }, 0);
      document.addEventListener('click', this._onDocClick);
    }

    disconnectedCallback() {
      document.removeEventListener('click', this._onDocClick);
    }

    attributeChangedCallback(name) {
      if (name === 'label' || name === 'placeholder' || name === 'error' || name === 'disabled') {
        if (this.shadowRoot.querySelector('.multi-select')) {
          this._render();
          this._bindEvents();
        }
      }
    }

    get value() { return this._selected.slice(); }
    set value(arr) {
      this._selected = Array.isArray(arr) ? arr.slice() : [];
      if (this.shadowRoot.querySelector('.multi-select')) {
        this._renderChips();
        this._syncOptionVisibility();
        this._updateFormValue();
      }
    }

    get name() { return this.getAttribute('name'); }

    _readOptions() {
      this._options = [];
      var opts = this.querySelectorAll('canvas-option');
      for (var i = 0; i < opts.length; i++) {
        var opt = opts[i];
        var val = opt.getAttribute('value') || opt.textContent.trim();
        this._options.push({
          value: val,
          label: opt.getAttribute('label') || opt.textContent.trim(),
          html: opt.innerHTML,
          disabled: opt.hasAttribute('disabled')
        });
        if (opt.hasAttribute('selected') && this._selected.indexOf(val) === -1) {
          this._selected.push(val);
        }
      }
    }

    _render() {
      var label = this.getAttribute('label');
      var placeholder = this.getAttribute('placeholder') || '';
      var error = this.getAttribute('error');
      var disabled = this.hasAttribute('disabled');

      var optionsHtml = '';
      for (var i = 0; i < this._options.length; i++) {
        var o = this._options[i];
        var sel = this._selected.indexOf(o.value) >= 0;
        var attrs = 'role="option" data-value="' + o.value + '" data-index="' + i + '"';
        if (o.disabled) attrs += ' aria-disabled="true"';
        optionsHtml += '<li class="option' + (sel ? ' selected' : '') + '" ' + attrs + '>' + o.html + '</li>';
      }

      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          .label { display: block; margin-bottom: .28571429rem; font-size: .92857143em; font-weight: 700; font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif); color: var(--color-text, rgba(0, 0, 0, 0.87)); line-height: 1em; }
          :host([error]) .label { color: #9f3a38; }
          .multi-select { position: relative; width: 100%; }
          .trigger {
            display: flex; flex-wrap: wrap; align-items: center; gap: 4px;
            min-height: calc(1.21428571em + 2 * .67857143em + 2px);
            padding: .4em .4em; padding-right: 2.1em;
            background: var(--color-surface, #FFFFFF);
            border: 1px solid rgba(34, 36, 38, 0.15);
            border-radius: var(--radius, .28571429rem);
            cursor: text; box-sizing: border-box;
            transition: border-color 0.1s ease, box-shadow 0.1s ease, border-radius 0.1s ease;
          }
          .trigger:focus-within { border-color: #96c8da; }
          .trigger.open { border-color: #96c8da; border-bottom-color: transparent; border-radius: var(--radius, .28571429rem) var(--radius, .28571429rem) 0 0; }
          .trigger.open.flip { border-bottom-color: #96c8da; border-top-color: transparent; border-radius: 0 0 var(--radius, .28571429rem) var(--radius, .28571429rem); }
          :host([disabled]) .trigger { opacity: 0.45; cursor: default; pointer-events: none; }
          :host([error]) .trigger { background: #fff6f6; border-color: #e0b4b4; }
          .input {
            flex: 1; min-width: 80px; padding: .25em .33em;
            font-size: 1em; font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            line-height: 1.21428571em; color: var(--color-text, rgba(0, 0, 0, 0.87));
            background: transparent; border: none; outline: none; margin: 0;
          }
          .input::placeholder { color: rgba(191, 191, 191, 0.87); }
          .arrow { position: absolute; right: 1em; top: calc((1.21428571em + 2 * .67857143em + 2px) / 2); transform: translateY(-50%); width: 8px; height: 5px; pointer-events: none; }
          .chip {
            display: inline-flex; align-items: center; gap: .4em;
            padding: .5833em .708em .5833em .833em;
            font-size: .85714286rem; font-weight: 700; line-height: 1;
            color: rgba(0, 0, 0, 0.6); background: #e8e8e8;
            border: 0 solid transparent; border-radius: var(--radius, .28571429rem);
            white-space: nowrap; cursor: default; user-select: none;
            transition: background 0.1s ease;
          }
          .chip:hover { background: #e0e0e0; }
          .chip-dismiss {
            display: inline-flex; align-items: center; justify-content: center;
            width: 1em; height: 1em; flex-shrink: 0;
            padding: 0; margin: 0; background: transparent; border: none;
            cursor: pointer; color: inherit; opacity: .7;
            line-height: 1; transition: opacity 0.1s ease;
          }
          .chip-dismiss:hover { opacity: 1; }
          .chip-dismiss svg { display: block; }
          .menu {
            display: none; position: absolute; top: calc(100% - 1px); left: 0; right: 0;
            max-height: 16.02857143rem; overflow-y: auto;
            background: var(--color-surface, #FFFFFF);
            border: 1px solid #96c8da; border-top: none;
            border-radius: 0 0 var(--radius, .28571429rem) var(--radius, .28571429rem);
            box-shadow: 0 0px 3px 0 rgba(34, 36, 38, 0.06);
            z-index: 11; list-style: none; margin: 0; padding: 0;
          }
          .menu.visible { display: block; }
          .menu.flip {
            bottom: calc(100% - 1px); top: auto;
            border-top: 1px solid #96c8da; border-bottom: none;
            border-radius: var(--radius, .28571429rem) var(--radius, .28571429rem) 0 0;
            box-shadow: 0 0px 3px 0 rgba(34, 36, 38, 0.06);
          }
          .option {
            padding: .78571429rem 1.14285714rem; font-size: 1rem; line-height: 1.0625rem;
            color: var(--color-text, rgba(0, 0, 0, 0.87)); cursor: pointer;
            border-top: 1px solid #fafafa; transition: background 0.1s ease;
          }
          .option:first-child { border-top: none; }
          .option:hover, .option.highlighted { background: rgba(0, 0, 0, 0.05); color: rgba(0, 0, 0, 0.95); }
          .option.selected { display: none; }
          .option.hidden { display: none; }
          .option[aria-disabled="true"] { color: #767676; cursor: not-allowed; }
          .option[aria-disabled="true"]:hover { background: transparent; }
          .empty { padding: .78571429rem 1.14285714rem; font-size: 1rem; color: rgba(0, 0, 0, 0.4); display: none; }
          .empty.visible { display: block; }
          .error-text { margin-top: .28571429rem; font-size: .92857143em; font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif); color: #9f3a38; line-height: 1.4285em; }
        </style>
        ${label ? '<span class="label">' + label + '</span>' : ''}
        <div class="multi-select">
          <div class="trigger">
            <input class="input" type="text" placeholder="${placeholder}" ${disabled ? 'disabled' : ''}>
          </div>
          <svg class="arrow" viewBox="0 0 10 6" fill="#575757"><path d="M1 0h8a1 1 0 01.7 1.7l-4 4a1 1 0 01-1.4 0l-4-4A1 1 0 011 0z"/></svg>
          <ul class="menu" role="listbox" aria-multiselectable="true">
            ${optionsHtml}
            <li class="empty">No results</li>
          </ul>
        </div>
        ${error ? '<span class="error-text">' + error + '</span>' : ''}
      `;
      this._renderChips();
    }

    _renderChips() {
      var trigger = this.shadowRoot.querySelector('.trigger');
      var input = this.shadowRoot.querySelector('.input');
      var existing = trigger.querySelectorAll('.chip');
      for (var i = existing.length - 1; i >= 0; i--) existing[i].remove();

      for (var i = 0; i < this._selected.length; i++) {
        var opt = this._options.find(function(o) { return o.value === this._selected[i]; }.bind(this));
        if (!opt) continue;
        var chip = document.createElement('span');
        chip.className = 'chip';
        chip.dataset.value = opt.value;
        chip.innerHTML = opt.label + '<button class="chip-dismiss" aria-label="Remove ' + opt.label + '"><svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button>';
        trigger.insertBefore(chip, input);
      }
      this._bindChipEvents();
    }

    _syncOptionVisibility() {
      var items = this.shadowRoot.querySelectorAll('.option');
      for (var i = 0; i < items.length; i++) {
        var val = items[i].dataset.value;
        if (this._selected.indexOf(val) >= 0) {
          items[i].classList.add('selected');
        } else {
          items[i].classList.remove('selected');
        }
      }
      this._checkEmpty();
    }

    _checkEmpty() {
      var visible = this.shadowRoot.querySelectorAll('.option:not(.selected):not(.hidden)');
      var empty = this.shadowRoot.querySelector('.empty');
      if (visible.length === 0) empty.classList.add('visible');
      else empty.classList.remove('visible');
    }

    _updateFormValue() {
      var fd = new FormData();
      var name = this.getAttribute('name');
      if (name) {
        for (var i = 0; i < this._selected.length; i++) {
          fd.append(name, this._selected[i]);
        }
      }
      this._internals.setFormValue(fd);
    }

    _bindEvents() {
      var self = this;
      var trigger = this.shadowRoot.querySelector('.trigger');
      var input = this.shadowRoot.querySelector('.input');
      var menu = this.shadowRoot.querySelector('.menu');

      trigger.addEventListener('click', function(e) {
        if (self.hasAttribute('disabled')) return;
        var dismiss = e.target.closest('.chip-dismiss');
        if (dismiss) {
          var chip = dismiss.closest('.chip');
          if (chip) self._deselect(chip.dataset.value);
          return;
        }
        var chip = e.target.closest('.chip');
        if (chip) return;
        if (!self._open) self._openMenu();
        input.focus();
      });

      input.addEventListener('input', function() {
        if (!self._open) self._openMenu();
        self._filter(input.value);
      });

      input.addEventListener('keydown', function(e) {
        if (self.hasAttribute('disabled')) return;
        switch (e.key) {
          case 'ArrowDown':
            e.preventDefault();
            if (!self._open) self._openMenu();
            self._highlightNext(1);
            break;
          case 'ArrowUp':
            e.preventDefault();
            if (!self._open) self._openMenu();
            self._highlightNext(-1);
            break;
          case 'Enter':
            e.preventDefault();
            if (!self._open) {
              self._openMenu();
            } else if (self._highlighted >= 0) {
              var visible = self._getVisibleOptions();
              if (visible[self._highlighted]) {
                self._selectValue(visible[self._highlighted].dataset.value);
                input.value = '';
                self._clearFilter();
                self._highlighted = -1;
              }
            }
            break;
          case 'Escape':
            e.preventDefault();
            input.value = '';
            self._clearFilter();
            self._close();
            break;
          case 'Backspace':
            if (input.value === '' && self._selected.length > 0) {
              self._deselect(self._selected[self._selected.length - 1]);
            }
            break;
          case 'Home':
            if (self._open) { e.preventDefault(); self._highlightIndex(0); }
            break;
          case 'End':
            if (self._open) {
              e.preventDefault();
              var visible = self._getVisibleOptions();
              self._highlightIndex(visible.length - 1);
            }
            break;
          case 'Tab':
            if (self._open) {
              input.value = '';
              self._clearFilter();
              self._close();
            }
            break;
        }
      });

      menu.addEventListener('click', function(e) {
        var opt = e.target.closest('.option');
        if (!opt) return;
        if (opt.getAttribute('aria-disabled') === 'true') return;
        self._selectValue(opt.dataset.value);
        input.value = '';
        self._clearFilter();
        input.focus();
      });
    }

    _selectValue(val) {
      if (this._selected.indexOf(val) >= 0) return;
      this._selected.push(val);
      this._renderChips();
      this._syncOptionVisibility();
      this._updateFormValue();
      this.dispatchEvent(new CustomEvent('change', { bubbles: true, composed: true }));
    }

    _deselect(val) {
      var idx = this._selected.indexOf(val);
      if (idx < 0) return;
      this._selected.splice(idx, 1);
      this._renderChips();
      this._syncOptionVisibility();
      this._updateFormValue();
      this.dispatchEvent(new CustomEvent('change', { bubbles: true, composed: true }));
    }

    _bindChipEvents() {
      var self = this;
      var chips = this.shadowRoot.querySelectorAll('.chip-dismiss');
      for (var i = 0; i < chips.length; i++) {
        chips[i].onclick = function(e) {
          e.stopPropagation();
          var chip = this.closest('.chip');
          if (chip) self._deselect(chip.dataset.value);
        };
      }
    }

    _openMenu() {
      this._open = true;
      this._highlighted = -1;
      var trigger = this.shadowRoot.querySelector('.trigger');
      var menu = this.shadowRoot.querySelector('.menu');
      trigger.classList.add('open');
      menu.classList.add('visible');
      this._checkEmpty();
      this._checkFlip();
    }

    _close() {
      this._open = false;
      this._highlighted = -1;
      var trigger = this.shadowRoot.querySelector('.trigger');
      var menu = this.shadowRoot.querySelector('.menu');
      trigger.classList.remove('open', 'flip');
      menu.classList.remove('visible', 'flip');
      this._clearHighlight();
    }

    _onDocClick(e) {
      if (!this.contains(e.target) && !this.shadowRoot.contains(e.target)) {
        if (this._open) {
          this.shadowRoot.querySelector('.input').value = '';
          this._clearFilter();
          this._close();
        }
      }
    }

    _filter(query) {
      var q = query.toLowerCase();
      var items = this.shadowRoot.querySelectorAll('.option');
      for (var i = 0; i < items.length; i++) {
        var label = this._options[items[i].dataset.index].label.toLowerCase();
        if (label.indexOf(q) >= 0) {
          items[i].classList.remove('hidden');
        } else {
          items[i].classList.add('hidden');
        }
      }
      this._checkEmpty();
      this._highlighted = -1;
      this._clearHighlight();
    }

    _clearFilter() {
      var items = this.shadowRoot.querySelectorAll('.option');
      for (var i = 0; i < items.length; i++) items[i].classList.remove('hidden');
      this._checkEmpty();
    }

    _checkFlip() {
      var menu = this.shadowRoot.querySelector('.menu');
      var trigger = this.shadowRoot.querySelector('.trigger');
      var rect = menu.getBoundingClientRect();
      if (rect.bottom > window.innerHeight) {
        menu.classList.add('flip');
        trigger.classList.add('flip');
      }
    }

    _getVisibleOptions() {
      return this.shadowRoot.querySelectorAll('.option:not(.selected):not(.hidden):not([aria-disabled="true"])');
    }

    _highlightNext(dir) {
      var opts = this._getVisibleOptions();
      if (opts.length === 0) return;
      this._highlighted += dir;
      if (this._highlighted < 0) this._highlighted = opts.length - 1;
      if (this._highlighted >= opts.length) this._highlighted = 0;
      this._applyHighlight(opts);
    }

    _highlightIndex(index) {
      var opts = this._getVisibleOptions();
      if (index < 0 || index >= opts.length) return;
      this._highlighted = index;
      this._applyHighlight(opts);
    }

    _applyHighlight(opts) {
      this._clearHighlight();
      if (this._highlighted >= 0 && opts[this._highlighted]) {
        opts[this._highlighted].classList.add('highlighted');
        opts[this._highlighted].scrollIntoView({ block: 'nearest' });
      }
    }

    _clearHighlight() {
      var items = this.shadowRoot.querySelectorAll('.option.highlighted');
      for (var i = 0; i < items.length; i++) items[i].classList.remove('highlighted');
    }
  }

  customElements.define('canvas-multi-select', CanvasMultiSelect);
}

if (!customElements.get('canvas-radio')) {
  class CanvasRadio extends HTMLElement {
    static get observedAttributes() {
      return ['name', 'label', 'value', 'checked', 'disabled'];
    }

    static formAssociated = true;

    constructor() {
      super();
      this._internals = this.attachInternals();
      this.attachShadow({ mode: 'open', delegatesFocus: true });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: inline-flex;
            align-items: center;
            min-height: var(--canvas-radio-min-height, auto);
            min-width: var(--canvas-radio-min-width, auto);
            padding: 4px 8px;
            cursor: pointer;
            font-size: 1rem;
            line-height: 1;
            font-family: lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
          }

          :host([disabled]) {
            cursor: not-allowed;
            opacity: 0.45;
          }

          input {
            position: absolute;
            opacity: 0;
            width: 15px;
            height: 15px;
            cursor: pointer;
            z-index: 3;
            margin: 0;
          }

          :host([disabled]) input { cursor: not-allowed; }

          .dot {
            position: relative;
            flex-shrink: 0;
            box-sizing: content-box;
            width: 15px;
            height: 15px;
            background: #FFFFFF;
            border: 1px solid #d4d4d5;
            border-radius: 500rem;
            transition: border 0.1s ease;
          }

          .dot::after {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            width: 15px;
            height: 15px;
            border-radius: 500rem;
            background-color: rgba(0, 0, 0, 0.87);
            transform: scale(.46666667);
            opacity: 0;
            transition: opacity 0.1s ease;
          }

          input:checked + .dot {
            border-color: rgba(34, 36, 38, 0.35);
          }

          input:checked + .dot::after { opacity: 1; }

          :host(:hover) .dot { border-color: rgba(34, 36, 38, 0.35); }

          input:focus + .dot,
          :host(:hover) input:focus + .dot {
            border-color: #85b7d9;
          }

          .label-text {
            padding-left: 8px;
            color: rgba(0, 0, 0, 0.87);
          }
        </style>
        <input type="radio" part="input">
        <span class="dot"></span>
        <span class="label-text" part="label"></span>
      `;
      this._input = this.shadowRoot.querySelector('input');
      this._labelText = this.shadowRoot.querySelector('.label-text');
      this._boundOnChange = this._onChange.bind(this);
      this._boundOnClick = this._onClick.bind(this);
    }

    connectedCallback() {
      this._input.addEventListener('change', this._boundOnChange);
      this.addEventListener('click', this._boundOnClick);
      this._syncAll();
    }

    disconnectedCallback() {
      this._input.removeEventListener('change', this._boundOnChange);
      this.removeEventListener('click', this._boundOnClick);
    }

    attributeChangedCallback(name) {
      switch (name) {
        case 'label':
          this._labelText.textContent = this.getAttribute('label') || '';
          break;
        case 'checked':
          this._input.checked = this.hasAttribute('checked');
          this._syncFormValue();
          break;
        case 'disabled':
          this._input.disabled = this.hasAttribute('disabled');
          break;
        case 'name':
          this._input.name = this.getAttribute('name') || '';
          break;
        case 'value':
          this._input.value = this.getAttribute('value') || '';
          this._syncFormValue();
          break;
      }
    }

    get checked() {
      return this._input.checked;
    }

    set checked(v) {
      if (v) {
        this.setAttribute('checked', '');
      } else {
        this.removeAttribute('checked');
      }
      this._input.checked = v;
      this._syncFormValue();
    }

    get value() {
      return this.getAttribute('value') || '';
    }

    get name() {
      return this.getAttribute('name');
    }

    _syncAll() {
      this._labelText.textContent = this.getAttribute('label') || '';
      this._input.name = this.getAttribute('name') || '';
      this._input.value = this.getAttribute('value') || '';
      this._input.checked = this.hasAttribute('checked');
      this._input.disabled = this.hasAttribute('disabled');
      this._syncFormValue();
    }

    _syncFormValue() {
      if (this._input.checked) {
        this._internals.setFormValue(this.getAttribute('value') || '');
      } else {
        this._internals.setFormValue(null);
      }
    }

    _onClick(e) {
      if (this.hasAttribute('disabled')) return;
      if (e.target === this._input) return;
      this._input.checked = true;
      this._input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    _onChange(e) {
      e.stopPropagation();
      this.setAttribute('checked', '');
      this._syncFormValue();
      this._uncheckSiblings();
      this.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    }

    _uncheckSiblings() {
      var name = this.getAttribute('name');
      if (!name) return;
      var parent = this.parentElement;
      if (!parent) return;
      var siblings = parent.querySelectorAll('canvas-radio[name="' + name + '"]');
      for (var i = 0; i < siblings.length; i++) {
        if (siblings[i] !== this && siblings[i].hasAttribute('checked')) {
          siblings[i].removeAttribute('checked');
          siblings[i]._input.checked = false;
          siblings[i]._syncFormValue();
        }
      }
    }
  }

  customElements.define('canvas-radio', CanvasRadio);
}

/* canvas-sidebar-layout: flex row container for sidebar + content split views */
if (!customElements.get('canvas-sidebar-layout')) {
  class CanvasSidebarLayout extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: flex;
            flex-direction: row;
            overflow: hidden;
            height: var(--canvas-sidebar-layout-height, auto);
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
          }
          :host([fullscreen]) {
            position: fixed;
            inset: 0;
          }
        </style>
        <slot></slot>
      `;
    }
  }
  customElements.define('canvas-sidebar-layout', CanvasSidebarLayout);
}

/* canvas-sidebar: scrollable left panel with gray background */
if (!customElements.get('canvas-sidebar')) {
  var SIDEBAR_WIDTHS = { 'default': '260px', 'narrow': '210px', 'wide': '400px' };

  class CanvasSidebar extends HTMLElement {
    static get observedAttributes() {
      return ['variant'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
            width: var(--canvas-sidebar-width, 260px);
            flex-shrink: 0;
            background: var(--canvas-sidebar-bg, #f5f5f5);
            padding: var(--canvas-sidebar-padding, 0);
            overflow-y: auto;
            box-sizing: border-box;
          }
          :host::-webkit-scrollbar { width: 8px; }
          :host::-webkit-scrollbar-thumb { background: rgba(0, 0, 0, 0.15); border-radius: 4px; }
          :host::-webkit-scrollbar-track { background: transparent; }
        </style>
        <slot></slot>
      `;
    }

    connectedCallback() {
      this._applyVariant();
    }

    attributeChangedCallback(name) {
      if (name === 'variant') this._applyVariant();
    }

    _applyVariant() {
      var variant = this.getAttribute('variant') || 'default';
      var width = SIDEBAR_WIDTHS[variant] || SIDEBAR_WIDTHS['default'];
      this.style.setProperty('--canvas-sidebar-width', width);
    }
  }
  customElements.define('canvas-sidebar', CanvasSidebar);
}

/* canvas-content: flexible right panel with white background */
if (!customElements.get('canvas-content')) {
  class CanvasContent extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
            flex: 1;
            background: var(--canvas-content-bg, #fff);
            padding: var(--canvas-content-padding, 0);
            overflow-y: auto;
            box-sizing: border-box;
          }
        </style>
        <slot></slot>
      `;
    }
  }
  customElements.define('canvas-content', CanvasContent);
}

if (!customElements.get('canvas-sortable-item')) {
  class CanvasSortableItem extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 4px 0;
            transition: transform 0.2s ease;
          }

          :host([dragging]) {
            opacity: 0.9;
            z-index: 9999;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            background: #fff;
            border-radius: var(--radius, .28571429rem);
            pointer-events: none;
          }

          .handle {
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            width: 20px;
            height: 20px;
            cursor: grab;
            color: rgba(0, 0, 0, 0.4);
            border-radius: var(--radius, .28571429rem);
          }

          .handle:hover {
            color: rgba(0, 0, 0, 0.7);
            background: rgba(0, 0, 0, 0.05);
          }

          .handle:active {
            cursor: grabbing;
          }

          .handle svg {
            pointer-events: none;
          }

          .content {
            flex: 1;
            min-width: 0;
          }
        </style>
        <span class="handle">
          <svg width="10" height="16" viewBox="0 0 10 16" fill="currentColor">
            <circle cx="2" cy="2" r="1.5"/>
            <circle cx="8" cy="2" r="1.5"/>
            <circle cx="2" cy="7" r="1.5"/>
            <circle cx="8" cy="7" r="1.5"/>
            <circle cx="2" cy="12" r="1.5"/>
            <circle cx="8" cy="12" r="1.5"/>
          </svg>
        </span>
        <div class="content"><slot></slot></div>
      `;

      var handle = this.shadowRoot.querySelector('.handle');
      handle.setAttribute('tabindex', '0');
      handle.setAttribute('role', 'button');
      handle.setAttribute('aria-label', 'Reorder');
      handle.setAttribute('aria-roledescription', 'sortable');

      var self = this;
      handle.addEventListener('keydown', function(e) {
        if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
        e.preventDefault();

        var list = self.closest('canvas-sortable-list');
        if (!list) return;

        var items = Array.prototype.slice.call(
          list.querySelectorAll('canvas-sortable-item')
        );
        var currentIndex = items.indexOf(self);
        var newIndex;

        if (e.key === 'ArrowUp' && currentIndex > 0) {
          newIndex = currentIndex - 1;
          list.insertBefore(self, items[newIndex]);
        } else if (e.key === 'ArrowDown' && currentIndex < items.length - 1) {
          newIndex = currentIndex + 1;
          list.insertBefore(self, items[newIndex].nextSibling);
        } else {
          return;
        }

        var event = new CustomEvent('reorder', {
          bubbles: true,
          composed: true,
          detail: {
            oldIndex: currentIndex,
            newIndex: newIndex,
            item: self
          }
        });
        list.dispatchEvent(event);

        handle.focus();
      });
    }
  }

  customElements.define('canvas-sortable-item', CanvasSortableItem);
}

if (!customElements.get('canvas-sortable-list')) {
  class CanvasSortableList extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
            position: relative;
          }

          ::slotted(canvas-sortable-item) {
            display: flex;
          }
        </style>
        <slot></slot>
      `;

      this._dragging = false;
      this._dragItem = null;
      this._dragSourceIndex = -1;
      this._placeholder = null;
      this._startY = 0;
      this._offsetY = 0;
      this._itemHeight = 0;

      this._onPointerDown = this._onPointerDown.bind(this);
      this._onPointerMove = this._onPointerMove.bind(this);
      this._onPointerUp = this._onPointerUp.bind(this);
    }

    connectedCallback() {
      this.addEventListener('pointerdown', this._onPointerDown);
    }

    disconnectedCallback() {
      this.removeEventListener('pointerdown', this._onPointerDown);
      this._cleanup();
    }

    _getItems() {
      return Array.prototype.slice.call(this.querySelectorAll('canvas-sortable-item:not([dragging])'));
    }

    _getHandleFromEvent(e) {
      /* Walk from the event target up through shadow roots to find .handle */
      var node = e.composedPath ? e.composedPath() : [];
      for (var i = 0; i < node.length; i++) {
        if (node[i].classList && node[i].classList.contains('handle')) return node[i];
      }
      return null;
    }

    _getItemFromHandle(handle) {
      /* The handle lives in the shadow root of a canvas-sortable-item */
      var root = handle.getRootNode();
      if (root && root.host && root.host.tagName === 'CANVAS-SORTABLE-ITEM') {
        return root.host;
      }
      return null;
    }

    _onPointerDown(e) {
      if (this._dragging) return;

      var handle = this._getHandleFromEvent(e);
      if (!handle) return;

      var item = this._getItemFromHandle(handle);
      if (!item) return;

      e.preventDefault();

      var items = this._getItems();
      this._dragSourceIndex = items.indexOf(item);
      this._dragItem = item;

      var rect = item.getBoundingClientRect();
      this._itemHeight = rect.height;
      this._startY = e.clientY;
      this._offsetY = e.clientY - rect.top;

      /* Measure all item positions before we start moving things */
      this._itemRects = [];
      for (var i = 0; i < items.length; i++) {
        this._itemRects.push(items[i].getBoundingClientRect());
      }

      /* Create a plain div placeholder that holds the space */
      this._placeholder = document.createElement('div');
      this._placeholder.style.height = rect.height + 'px';
      this._placeholder.style.transition = 'height 0.2s ease';
      this._placeholder.style.pointerEvents = 'none';
      item.parentNode.insertBefore(this._placeholder, item);

      /* Position the dragged item as fixed overlay */
      item.setAttribute('dragging', '');
      item.style.position = 'fixed';
      item.style.left = rect.left + 'px';
      item.style.top = rect.top + 'px';
      item.style.width = rect.width + 'px';
      item.style.transition = 'none';

      this._dragging = true;

      /* Force grabbing cursor everywhere and disable pointer events on list items
         so shadow DOM cursor rules cannot override the global cursor */
      this._cursorStyle = document.createElement('style');
      this._cursorStyle.textContent = '* { cursor: grabbing !important; user-select: none !important; }';
      document.head.appendChild(this._cursorStyle);
      this.style.pointerEvents = 'none';

      document.addEventListener('pointermove', this._onPointerMove);
      document.addEventListener('pointerup', this._onPointerUp);
    }

    _onPointerMove(e) {
      if (!this._dragging || !this._dragItem) return;

      /* Move the dragged item to follow the cursor */
      var newTop = e.clientY - this._offsetY;
      this._dragItem.style.top = newTop + 'px';

      /* Find where the placeholder should be based on cursor Y */
      var centerY = e.clientY;
      var items = this._getItems();
      var targetIndex = -1;

      for (var i = 0; i < items.length; i++) {
        var rect = items[i].getBoundingClientRect();
        var midY = rect.top + rect.height / 2;
        if (centerY < midY) {
          targetIndex = i;
          break;
        }
      }

      /* If cursor is below all items, place at the end */
      if (targetIndex === -1) {
        targetIndex = items.length;
      }

      /* Figure out which item the placeholder is currently next to */
      var currentNext = this._placeholder.nextElementSibling;
      var desiredNext = (targetIndex < items.length) ? items[targetIndex] : null;

      /* If placeholder is already in the right spot, nothing to do */
      if (currentNext === desiredNext) return;

      /* FLIP animation. Record positions before DOM change. */
      var rects = {};
      for (var i = 0; i < items.length; i++) {
        rects[i] = items[i].getBoundingClientRect();
      }

      /* Move the placeholder in the DOM */
      if (desiredNext) {
        this.insertBefore(this._placeholder, desiredNext);
      } else {
        this.appendChild(this._placeholder);
      }

      /* FLIP. Measure new positions and animate from old to new. */
      for (var i = 0; i < items.length; i++) {
        var oldRect = rects[i];
        var newRect = items[i].getBoundingClientRect();
        var deltaY = oldRect.top - newRect.top;
        if (Math.abs(deltaY) < 1) continue;

        items[i].style.transition = 'none';
        items[i].style.transform = 'translateY(' + deltaY + 'px)';

        /* Force reflow so the browser picks up the transform */
        items[i].offsetHeight;

        items[i].style.transition = 'transform 0.2s ease';
        items[i].style.transform = 'translateY(0)';
      }
    }

    _onPointerUp(e) {
      if (!this._dragging || !this._dragItem) {
        this._cleanup();
        return;
      }

      var item = this._dragItem;

      /* Insert the real item where the placeholder is */
      this.insertBefore(item, this._placeholder);

      /* Remove placeholder */
      if (this._placeholder && this._placeholder.parentNode) {
        this._placeholder.parentNode.removeChild(this._placeholder);
      }

      /* Reset styles on the dragged item */
      item.removeAttribute('dragging');
      item.style.position = '';
      item.style.left = '';
      item.style.top = '';
      item.style.width = '';
      item.style.transition = '';
      item.style.transform = '';

      /* Calculate new index and fire event */
      var items = this._getItems();
      var newIndex = items.indexOf(item);

      if (this._dragSourceIndex !== newIndex) {
        this.dispatchEvent(new CustomEvent('reorder', {
          bubbles: true,
          composed: true,
          cancelable: true,
          detail: {
            oldIndex: this._dragSourceIndex,
            newIndex: newIndex,
            item: item
          }
        }));
      }

      this._cleanup();
    }

    _cleanup() {
      this.style.pointerEvents = '';
      if (this._cursorStyle && this._cursorStyle.parentNode) {
        this._cursorStyle.parentNode.removeChild(this._cursorStyle);
      }
      this._cursorStyle = null;

      /* Clean up inline transition styles on all items */
      var items = this._getItems();
      for (var i = 0; i < items.length; i++) {
        items[i].style.transition = '';
        items[i].style.transform = '';
      }

      this._dragging = false;
      this._dragItem = null;
      this._dragSourceIndex = -1;
      this._itemRects = null;

      if (this._placeholder && this._placeholder.parentNode) {
        this._placeholder.parentNode.removeChild(this._placeholder);
      }
      this._placeholder = null;

      document.removeEventListener('pointermove', this._onPointerMove);
      document.removeEventListener('pointerup', this._onPointerUp);
    }
  }

  customElements.define('canvas-sortable-list', CanvasSortableList);
}

if (!customElements.get('canvas-table')) {
  class CanvasTable extends HTMLElement {
    static get observedAttributes() {
      return ['compact', 'celled', 'selectable', 'sticky', 'striped'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: table;
            width: 100%;
            border-collapse: collapse;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            color: var(--color-text, rgba(0, 0, 0, 0.87));
            font-size: 1em;
          }

          ::slotted(canvas-table-head) {
            display: table-header-group;
          }

          ::slotted(canvas-table-body) {
            display: table-row-group;
          }
        </style>
        <slot></slot>
      `;
    }

    connectedCallback() {
      this._applyVariants();
    }

    attributeChangedCallback() {
      this._applyVariants();
    }

    _applyVariants() {
      if (this.hasAttribute('compact')) {
        this.style.setProperty('--canvas-table-cell-padding', '0.35rem 0.7rem');
        this.style.setProperty('--canvas-table-header-padding', '0.5rem 0.7rem');
      } else {
        this.style.removeProperty('--canvas-table-cell-padding');
        this.style.removeProperty('--canvas-table-header-padding');
      }
    }
  }

  class CanvasTableHead extends HTMLElement {
    connectedCallback() {
      this.style.display = 'table-header-group';
    }
  }

  class CanvasTableBody extends HTMLElement {
    connectedCallback() {
      this.style.display = 'table-row-group';
    }
  }

  class CanvasTableRow extends HTMLElement {
    static get observedAttributes() {
      return ['positive', 'warning', 'negative', 'active'];
    }

    connectedCallback() {
      this.style.display = 'table-row';

      const inHead = this.parentElement && this.parentElement.tagName === 'CANVAS-TABLE-HEAD';

      if (inHead) {
        this.style.borderBottom = 'none';
      } else {
        this.style.borderBottom = '1px solid var(--canvas-table-border, rgba(34, 36, 38, 0.1))';
      }

      this._applyState();

      if (!inHead) {
        const table = this._getTable();

        if (table && table.hasAttribute('striped')) {
          const siblings = Array.from(this.parentElement.children).filter(
            (el) => el.tagName === 'CANVAS-TABLE-ROW'
          );
          const index = siblings.indexOf(this);
          if (index % 2 === 1) {
            this._stripeBackground = 'var(--canvas-table-stripe-bg, rgba(0, 0, 50, 0.02))';
          }
          this._applyState();
        }

        if (table && table.hasAttribute('selectable')) {
          this.style.cursor = 'pointer';
          this._onMouseEnter = () => {
            if (!this.hasAttribute('positive') && !this.hasAttribute('warning') &&
                !this.hasAttribute('negative') && !this.hasAttribute('active')) {
              this.style.background = 'rgba(0, 0, 50, 0.025)';
            }
          };
          this._onMouseLeave = () => {
            this._applyState();
          };
          this.addEventListener('mouseenter', this._onMouseEnter);
          this.addEventListener('mouseleave', this._onMouseLeave);
        }
      }
    }

    disconnectedCallback() {
      if (this._onMouseEnter) {
        this.removeEventListener('mouseenter', this._onMouseEnter);
      }
      if (this._onMouseLeave) {
        this.removeEventListener('mouseleave', this._onMouseLeave);
      }
    }

    attributeChangedCallback() {
      this._applyState();
    }

    _applyState() {
      if (this.hasAttribute('positive')) {
        this.style.background = 'var(--canvas-table-row-positive-bg, #fcfff5)';
        this.style.color = 'var(--canvas-table-row-positive-text, #2c662d)';
      } else if (this.hasAttribute('warning')) {
        this.style.background = 'var(--canvas-table-row-warning-bg, #fffaf3)';
        this.style.color = 'var(--canvas-table-row-warning-text, #573a08)';
      } else if (this.hasAttribute('negative')) {
        this.style.background = 'var(--canvas-table-row-negative-bg, #fff6f6)';
        this.style.color = 'var(--canvas-table-row-negative-text, #9f3a38)';
      } else if (this.hasAttribute('active')) {
        this.style.background = 'var(--canvas-table-row-active-bg, #e0e0e0)';
        this.style.color = '';
      } else if (this._stripeBackground) {
        this.style.background = this._stripeBackground;
        this.style.color = '';
      } else {
        this.style.background = '';
        this.style.color = '';
      }
    }

    _getTable() {
      let el = this.parentElement;
      while (el) {
        if (el.tagName === 'CANVAS-TABLE') {
          return el;
        }
        el = el.parentElement;
      }
      return null;
    }
  }

  class CanvasTableCell extends HTMLElement {
    static get observedAttributes() {
      return ['actions', 'bold', 'colspan', 'width'];
    }

    connectedCallback() {
      this.style.display = 'table-cell';
      this.style.verticalAlign = 'middle';
      this.style.textAlign = 'left';

      const inHead = this._isInHead();
      const table = this._getTable();

      if (inHead) {
        this.style.fontWeight = '700';
        this.style.padding = 'var(--canvas-table-header-padding, 0.5rem 1rem)';
        this.style.background = 'var(--canvas-table-header-bg, #FFFFFF)';
        this.style.borderBottom = '2px solid var(--canvas-table-border, rgba(34, 36, 38, 0.1))';

        if (table && table.hasAttribute('sticky')) {
          this.style.position = 'sticky';
          this.style.top = '0';
          this.style.zIndex = '2';
        }
      } else {
        this.style.padding = 'var(--canvas-table-cell-padding, 0.5rem 1rem)';
      }

      if (table && table.hasAttribute('celled')) {
        this.style.border = '1px solid var(--canvas-table-border, rgba(34, 36, 38, 0.1))';
      }

      if (this.hasAttribute('bold')) {
        this.style.fontWeight = '700';
      }

      if (this.hasAttribute('actions')) {
        this.style.whiteSpace = 'nowrap';
        this.style.textAlign = 'right';
        this.style.width = '1%';
      }

      if (this.hasAttribute('width')) {
        this.style.width = this.getAttribute('width');
      }

      if (this.hasAttribute('colspan')) {
        this.style.display = 'block';
        this.style.width = '100%';
        const row = this.parentElement;
        if (row) {
          Array.from(row.children).forEach((sibling) => {
            if (sibling !== this && sibling.tagName === 'CANVAS-TABLE-CELL') {
              sibling.style.display = 'none';
            }
          });
        }
      }
    }

    _isInHead() {
      const row = this.parentElement;
      if (!row) return false;
      const group = row.parentElement;
      if (!group) return false;
      return group.tagName === 'CANVAS-TABLE-HEAD';
    }

    _getTable() {
      let el = this.parentElement;
      while (el) {
        if (el.tagName === 'CANVAS-TABLE') {
          return el;
        }
        el = el.parentElement;
      }
      return null;
    }
  }

  customElements.define('canvas-table', CanvasTable);
  customElements.define('canvas-table-head', CanvasTableHead);
  customElements.define('canvas-table-body', CanvasTableBody);
  customElements.define('canvas-table-row', CanvasTableRow);
  customElements.define('canvas-table-cell', CanvasTableCell);
}

/* canvas-tab-panel: simple content container, visibility managed by canvas-tabs */
if (!customElements.get('canvas-tab-panel')) {
  class CanvasTabPanel extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = '<style>:host{display:block}:host([hidden]){display:none}.panel-inner{overflow:auto;max-width:100%}</style><div class="panel-inner"><slot></slot></div>';
    }
    connectedCallback() {
      this.setAttribute('role', 'tabpanel');
      if (!this.hasAttribute('hidden')) this.setAttribute('hidden', '');
    }
  }
  customElements.define('canvas-tab-panel', CanvasTabPanel);
}

/* canvas-tab-label: text label inside a canvas-tab. Truncates with ellipsis and sets title automatically. */
if (!customElements.get('canvas-tab-label')) {
  class CanvasTabLabel extends HTMLElement {
    constructor() { super(); }
    connectedCallback() { this.style.display = 'none'; }
  }
  customElements.define('canvas-tab-label', CanvasTabLabel);
}

/* canvas-tab: a single tab button inside canvas-tabs. Rich content via slot. */
if (!customElements.get('canvas-tab')) {
  class CanvasTab extends HTMLElement {
    constructor() { super(); }
    connectedCallback() {
      this.style.display = 'none';
      if (!this.querySelector('canvas-tab-label')) {
        console.warn('canvas-tab: missing <canvas-tab-label>. Wrap your tab text in <canvas-tab-label> for truncation and tooltip support.');
      }
    }
  }
  customElements.define('canvas-tab', CanvasTab);
}

/* canvas-tabs: tab bar container that manages active state, keyboard nav, and panel visibility */
if (!customElements.get('canvas-tabs')) {
  class CanvasTabs extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._tabs = [];
      this._buttons = [];
      this._focusIndex = 0;
    }

    connectedCallback() {
      var self = this;
      setTimeout(function() {
        self._readTabs();
        self._render();
        self._computeMinWidths();
        self._bindEvents();
        self._activateInitial();
      }, 0);
    }

    _readTabs() {
      this._tabs = [];
      var tabs = this.querySelectorAll(':scope > canvas-tab');
      for (var i = 0; i < tabs.length; i++) {
        var tab = tabs[i];
        var labelEl = tab.querySelector('canvas-tab-label');
        var hasLabel = !!labelEl;
        var labelText = hasLabel ? labelEl.textContent.trim() : tab.textContent.trim();

        /* Collect trailing content (everything after canvas-tab-label) */
        var trailingHtml = '';
        if (hasLabel) {
          var sibling = labelEl.nextElementSibling;
          while (sibling) {
            trailingHtml += sibling.outerHTML;
            sibling = sibling.nextElementSibling;
          }
        }

        this._tabs.push({
          panelId: tab.getAttribute('for'),
          badge: tab.getAttribute('badge'),
          active: tab.hasAttribute('active'),
          hasLabel: hasLabel,
          labelText: labelText,
          trailingHtml: trailingHtml,
          html: tab.innerHTML,
          text: labelText
        });
      }
    }

    _render() {
      var buttonsHtml = '';
      for (var i = 0; i < this._tabs.length; i++) {
        var t = this._tabs[i];
        var badgeHtml = '';
        if (t.badge) {
          badgeHtml = '<span class="tab-badge">' + t.badge + '</span>';
        }
        var titleAttr = t.hasLabel ? ' title="' + t.labelText.replace(/"/g, '&quot;') + '"' : '';

        if (t.hasLabel) {
          buttonsHtml += '<button class="tab-button" role="tab" aria-selected="false" tabindex="-1" data-index="' + i + '" data-panel="' + (t.panelId || '') + '">'
            + '<span class="tab-label-text"' + titleAttr + '>' + t.labelText + '</span>'
            + t.trailingHtml + badgeHtml
            + '</button>';
        } else {
          buttonsHtml += '<button class="tab-button" role="tab" aria-selected="false" tabindex="-1" data-index="' + i + '" data-panel="' + (t.panelId || '') + '">'
            + t.html + badgeHtml
            + '</button>';
        }
      }

      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          .tab-wrapper {
            position: relative;
            margin-bottom: 1em;
          }
          .tab-wrapper::after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 2px;
            background: rgba(34, 36, 38, 0.15);
          }
          .tab-bar {
            -webkit-mask-image: linear-gradient(to right, black, black);
            mask-image: linear-gradient(to right, black, black);
            transition: -webkit-mask-image 0.15s ease, mask-image 0.15s ease;
            display: flex;
            align-items: stretch;
            height: var(--tab-bar-height, 45.41px);
            width: 100%;
            background: transparent;
            padding: 0;
            overflow-x: auto;
            overflow-y: visible;
            scrollbar-width: none;
          }
          .tab-bar::-webkit-scrollbar { display: none; }
          .tab-bar.fade-right {
            -webkit-mask-image: linear-gradient(to right, black calc(100% - 50px), transparent);
            mask-image: linear-gradient(to right, black calc(100% - 50px), transparent);
          }
          .tab-bar.fade-left {
            -webkit-mask-image: linear-gradient(to right, transparent, black 50px);
            mask-image: linear-gradient(to right, transparent, black 50px);
          }
          .tab-bar.fade-both {
            -webkit-mask-image: linear-gradient(to right, transparent, black 50px, black calc(100% - 50px), transparent);
            mask-image: linear-gradient(to right, transparent, black 50px, black calc(100% - 50px), transparent);
          }
          .tab-button {
            display: inline-flex;
            align-items: center;
            gap: .50em;
            padding: 0 1.14285714em;
            flex: 0 1 auto;
            font-size: 1em;
            font-weight: 400;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            line-height: 1em;
            color: rgba(0, 0, 0, 0.87);
            background: transparent;
            border: none;
            border-bottom: 2px solid transparent;
            position: relative;
            z-index: 1;
            cursor: pointer;
            transition: border-color 0.1s ease;
            white-space: nowrap;
          }
          .tab-button:focus-visible {
            outline: 2px solid #2185d0;
            outline-offset: -2px;
          }
          .tab-button:hover { color: rgba(0, 0, 0, 0.95); }
          .tab-button[aria-selected="true"] {
            border-bottom-color: rgb(27, 28, 29);
            color: rgba(0, 0, 0, 0.95);
            font-weight: 700;
          }
          .tab-label-text {
            display: block;
            flex: 0 1 var(--tab-label-max-width, 160px);
            min-width: var(--tab-label-min-width, 60px);
            max-width: var(--tab-label-max-width, 160px);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }
          .tab-badge {
            display: inline-flex;
            align-items: center;
            padding: .21428571em .5625em;
            font-size: .71428571em;
            font-weight: 700;
            color: #767676;
            background: #fff;
            border: 1px solid #767676;
            border-radius: .28571429rem;
            line-height: 1;
            margin: 0;
            gap: 0;
            flex-shrink: 0;
          }
        </style>
        <div class="tab-wrapper">
          <div class="tab-bar" role="tablist">${buttonsHtml}</div>
        </div>
        <slot></slot>
      `;
    }

    _computeMinWidths() {
      var buttons = this.shadowRoot.querySelectorAll('.tab-button');
      var labels = this.shadowRoot.querySelectorAll('.tab-label-text');
      var minWidth = getComputedStyle(this.shadowRoot.host).getPropertyValue('--tab-label-min-width').trim() || '60px';

      /* Force labels to their minimum, measure each button, set as floor */
      for (var i = 0; i < labels.length; i++) {
        labels[i].style.width = minWidth;
        labels[i].style.flexBasis = minWidth;
      }

      for (var i = 0; i < buttons.length; i++) {
        var floor = buttons[i].scrollWidth;
        buttons[i].style.minWidth = floor + 'px';
      }

      /* Reset labels to their natural flex behavior */
      for (var i = 0; i < labels.length; i++) {
        labels[i].style.width = '';
        labels[i].style.flexBasis = '';
      }
    }

    _updateFades() {
      var bar = this.shadowRoot.querySelector('.tab-bar');
      if (!bar) return;
      var scrollLeft = bar.scrollLeft;
      var maxScroll = bar.scrollWidth - bar.clientWidth;
      var hasLeft = scrollLeft > 2;
      var hasRight = maxScroll - scrollLeft > 2;

      bar.classList.remove('fade-left', 'fade-right', 'fade-both');
      if (hasLeft && hasRight) bar.classList.add('fade-both');
      else if (hasLeft) bar.classList.add('fade-left');
      else if (hasRight) bar.classList.add('fade-right');
    }

    _bindEvents() {
      var self = this;
      this._buttons = Array.from(this.shadowRoot.querySelectorAll('.tab-button'));

      var bar = this.shadowRoot.querySelector('.tab-bar');
      bar.addEventListener('scroll', function() { self._updateFades(); });
      self._updateFades();

      bar.addEventListener('click', function(e) {
        var btn = e.target.closest('.tab-button');
        if (!btn) return;
        var index = parseInt(btn.dataset.index, 10);
        self._activate(index);
      });

      this.shadowRoot.querySelector('.tab-bar').addEventListener('keydown', function(e) {
        var btn = e.target.closest('.tab-button');
        if (!btn) return;
        var index = parseInt(btn.dataset.index, 10);
        var last = self._buttons.length - 1;

        switch (e.key) {
          case 'ArrowRight':
            e.preventDefault();
            self._focusTab(index < last ? index + 1 : 0);
            break;
          case 'ArrowLeft':
            e.preventDefault();
            self._focusTab(index > 0 ? index - 1 : last);
            break;
          case 'Home':
            e.preventDefault();
            self._focusTab(0);
            break;
          case 'End':
            e.preventDefault();
            self._focusTab(last);
            break;
        }
      });
    }

    _activateInitial() {
      var initial = 0;
      for (var i = 0; i < this._tabs.length; i++) {
        if (this._tabs[i].active) { initial = i; break; }
      }
      this._activate(initial);
    }

    _activate(index) {
      /* Deactivate all */
      for (var i = 0; i < this._buttons.length; i++) {
        this._buttons[i].setAttribute('aria-selected', 'false');
        this._buttons[i].setAttribute('tabindex', '-1');
      }
      /* Hide all panels */
      var panels = this.querySelectorAll(':scope > canvas-tab-panel');
      for (var i = 0; i < panels.length; i++) {
        panels[i].setAttribute('hidden', '');
        panels[i].removeAttribute('visible');
      }

      /* Activate selected */
      var btn = this._buttons[index];
      if (!btn) return;
      btn.setAttribute('aria-selected', 'true');
      btn.setAttribute('tabindex', '0');

      var panelId = btn.dataset.panel;
      if (panelId) {
        var panel = this.querySelector(':scope > canvas-tab-panel[id="' + panelId + '"]');
        if (panel) {
          panel.removeAttribute('hidden');
          panel.setAttribute('visible', '');
          btn.setAttribute('aria-controls', panelId);
          panel.setAttribute('aria-labelledby', 'tab-' + index);
        }
      }

      btn.id = 'tab-' + index;
      this._focusIndex = index;

      this.dispatchEvent(new CustomEvent('tab-change', {
        bubbles: true,
        composed: true,
        detail: { index: index, panel: panelId }
      }));
    }

    _focusTab(index) {
      if (this._buttons[index]) {
        this._buttons[index].focus();
        this._focusIndex = index;
      }
    }
  }

  customElements.define('canvas-tabs', CanvasTabs);
}

if (!customElements.get('canvas-toggle')) {
  class CanvasToggle extends HTMLElement {
    static get observedAttributes() {
      return ['label', 'checked', 'disabled', 'label-position'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open', delegatesFocus: true });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            min-height: var(--canvas-toggle-min-height, auto);
            min-width: var(--canvas-toggle-min-width, auto);
            cursor: pointer;
            user-select: none;
            font-size: 1rem;
            line-height: 1;
            font-family: lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
          }

          :host([label-position="start"]) {
            flex-direction: row-reverse;
          }

          :host([disabled]) {
            cursor: not-allowed;
            opacity: 0.45;
          }

          .track {
            position: relative;
            flex-shrink: 0;
            width: 3.5rem;
            height: 1.5rem;
            background: #F4F4F4;
            border-radius: 500rem;
            border: none;
            padding: 0;
            cursor: pointer;
            pointer-events: auto;
          }

          .track::after {
            content: "";
            position: absolute;
            top: 0;
            left: -0.05rem;
            width: 1.5rem;
            height: 1.5rem;
            background: #fff linear-gradient(transparent, rgba(0, 0, 0, 0.05));
            border-radius: 500rem;
            box-shadow: 0 1px 2px 0 rgba(34, 36, 38, 0.15), 0 0 0 1px rgba(34, 36, 38, 0.15) inset;
            transition: left 0.3s ease;
          }

          :host([checked]) .track { background: #0D71BC; }
          :host([checked]) .track::after { left: 2.15rem; }

          :host(:not([disabled]):hover) .track { background: #DEDEDE; }
          :host(:not([disabled]):hover[checked]) .track { background: #0D71BC; }

          .track:focus-visible {
            outline: 2px solid #85b7d9;
            outline-offset: 2px;
          }

          :host([disabled]) .track { cursor: not-allowed; }

          .label-text {
            color: rgba(0, 0, 0, 0.87);
          }
        </style>
        <button class="track" role="switch" aria-checked="false" tabindex="0" part="track"></button>
        <span class="label-text" part="label"></span>
      `;
      this._track = this.shadowRoot.querySelector('.track');
      this._labelText = this.shadowRoot.querySelector('.label-text');
      this._boundOnClick = this._onClick.bind(this);
    }

    connectedCallback() {
      this.addEventListener('click', this._boundOnClick);
      this._syncAll();
    }

    disconnectedCallback() {
      this.removeEventListener('click', this._boundOnClick);
    }

    attributeChangedCallback(name) {
      switch (name) {
        case 'label':
          this._labelText.textContent = this.getAttribute('label') || '';
          if (this.getAttribute('label')) {
            this._track.setAttribute('aria-label', this.getAttribute('label'));
          }
          break;
        case 'checked':
          this._track.setAttribute('aria-checked', this.hasAttribute('checked') ? 'true' : 'false');
          break;
        case 'disabled':
          if (this.hasAttribute('disabled')) {
            this._track.setAttribute('disabled', '');
            this._track.setAttribute('tabindex', '-1');
          } else {
            this._track.removeAttribute('disabled');
            this._track.setAttribute('tabindex', '0');
          }
          break;
      }
    }

    get checked() {
      return this.hasAttribute('checked');
    }

    set checked(v) {
      if (v) {
        this.setAttribute('checked', '');
      } else {
        this.removeAttribute('checked');
      }
    }

    _syncAll() {
      this._labelText.textContent = this.getAttribute('label') || '';
      if (this.getAttribute('label')) {
        this._track.setAttribute('aria-label', this.getAttribute('label'));
      }
      this._track.setAttribute('aria-checked', this.hasAttribute('checked') ? 'true' : 'false');
      if (this.hasAttribute('disabled')) {
        this._track.setAttribute('disabled', '');
        this._track.setAttribute('tabindex', '-1');
      }
    }

    _onClick(e) {
      e.stopPropagation();
      if (this.hasAttribute('disabled')) return;
      if (this.hasAttribute('checked')) {
        this.removeAttribute('checked');
      } else {
        this.setAttribute('checked', '');
      }
      this.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    }
  }

  customElements.define('canvas-toggle', CanvasToggle);
}
