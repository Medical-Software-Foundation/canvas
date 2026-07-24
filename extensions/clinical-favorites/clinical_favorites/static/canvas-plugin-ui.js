(function() {
  var CanvasUI = window.CanvasUI = window.CanvasUI || {};

  /* ---- API ---- */

  CanvasUI.register = function(tag, cls) {
    customElements.define(tag, cls);
  };

  /* ---- Utils ---- */

  CanvasUI.utils = (function() {
    var port = null;

    window.addEventListener('message', function(event) {
      if (event.data && event.data.type === 'INIT_CHANNEL' && event.ports && event.ports[0]) {
        port = event.ports[0];
        port.start();
      }
    });

    return {
      dismissModal: function() {
        if (port) port.postMessage({ type: 'CLOSE_MODAL' });
      },

      resizeModal: function(width, height) {
        var msg = { type: 'RESIZE' };
        if (width != null) msg.width = width;
        if (height != null) msg.height = height;
        if (port) port.postMessage(msg);
      }
    };
  })();

  /* ---- Internal helpers ---- */

  /* Shared constants for anchored callout positioning. Used by canvas-tooltip
     and by canvas-popover when the pointer affordance is enabled. The gap is
     the distance between the trigger edge and the surface edge along the
     direction axis. The edge margin is the minimum distance the surface keeps
     from any viewport side. The arrow size constants describe the 14 px by
     7 px triangular artwork the tooltip and the pointer popover share, and
     the corner inset keeps the arrow clear of the surface border radius. */
  var ANCHOR_GAP = 10;
  var ANCHOR_EDGE = 8;
  var ANCHOR_ARROW_SIZE = 14;
  var ANCHOR_ARROW_DEPTH = 7;
  var ANCHOR_ARROW_HALF = 7;
  var ANCHOR_ARROW_CORNER_INSET = 6;

  /* computeAutoPlacement: viewport aware flip decision for anchored floating
     elements. Given an anchor rectangle and a rendered floating element, it
     returns which direction ('up') and alignment ('end') should override the
     default 'down' plus 'start' placement when viewport space is insufficient.
     Explicit direction and align options opt out of the corresponding axis.
     Shared by canvas-menu-button and canvas-popover. */
  function computeAutoPlacement(anchorRect, floatingEl, options) {
    options = options || {};
    var explicitDirection = options.direction || null;
    var explicitAlign = options.align || null;
    var gutter = typeof options.gutter === 'number' ? options.gutter : 4;

    var floatingHeight = floatingEl.offsetHeight;
    var floatingWidth = floatingEl.offsetWidth;
    var viewportHeight = window.innerHeight;
    var viewportWidth = window.innerWidth;

    var placement = { direction: null, align: null };

    if (!explicitDirection) {
      var spaceBelow = viewportHeight - anchorRect.bottom - gutter;
      var spaceAbove = anchorRect.top - gutter;
      if (spaceBelow < floatingHeight && spaceAbove > spaceBelow) {
        placement.direction = 'up';
      }
    }

    if (!explicitAlign) {
      var spaceRight = viewportWidth - anchorRect.left - gutter;
      var spaceLeft = anchorRect.right - gutter;
      if (spaceRight < floatingWidth && spaceLeft >= floatingWidth) {
        placement.align = 'end';
      }
    }

    return placement;
  }

  /* ---- Components ---- */

  /* ======== canvas-option (shared) ======== */

  class CanvasOption extends HTMLElement {
    constructor() { super(); }
    connectedCallback() { this.style.display = 'none'; }
    get value() { return this.getAttribute('value') || (this.textContent || '').trim(); }
    set value(v) { this.setAttribute('value', v == null ? '' : String(v)); }
  }
  CanvasUI.register('canvas-option', CanvasOption);

  /* ======== canvas-accordion ======== */

  /* canvas-accordion-title: title bar content. Has its own shadow DOM slot so children render. */
  class CanvasAccordionTitle extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = '<style>:host{display:flex;align-items:center;gap:8px;flex:1;min-width:0}</style><slot></slot>';
    }
  }
  CanvasUI.register('canvas-accordion-title', CanvasAccordionTitle);

  /* canvas-accordion-content: collapsible content area, hidden by default */
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
  CanvasUI.register('canvas-accordion-content', CanvasAccordionContent);

  /* canvas-accordion-item: collapsible section with chevron, title slot, and content slot */
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
      var INTERACTIVE_SELECTOR = [
        'button', 'a[href]', 'input', 'select', 'textarea',
        '[role="button"]', '[role="switch"]', '[role="checkbox"]', '[role="radio"]',
        '[role="link"]', '[role="menuitem"]', '[role="tab"]', '[role="option"]',
        'canvas-button', 'canvas-toggle', 'canvas-checkbox', 'canvas-radio',
        'canvas-dropdown', 'canvas-combobox', 'canvas-multi-select',
        'canvas-menu-button', 'canvas-popover',
        'canvas-input', 'canvas-date-input', 'canvas-textarea'
      ].join(',');

      function isFromInteractiveChild(e) {
        var path = e.composedPath();
        for (var i = 0; i < path.length; i++) {
          var el = path[i];
          if (el === title) return false;
          if (el && el.nodeType === 1 && el.matches && el.matches(INTERACTIVE_SELECTOR)) return true;
        }
        return false;
      }

      title.addEventListener('click', function(e) {
        if (isFromInteractiveChild(e)) return;
        self.toggle();
      });

      title.addEventListener('keydown', function(e) {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        if (isFromInteractiveChild(e)) return;
        e.preventDefault();
        self.toggle();
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
  CanvasUI.register('canvas-accordion-item', CanvasAccordionItem);

  /* canvas-accordion: thin container, no shadow DOM */
  class CanvasAccordion extends HTMLElement {
    constructor() { super(); }
    connectedCallback() { this.style.display = 'block'; this.style.width = '100%'; }
  }
  CanvasUI.register('canvas-accordion', CanvasAccordion);

  /* ======== canvas-badge ======== */

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

  CanvasUI.register('canvas-badge', CanvasBadge);

  /* ======== canvas-banner ======== */

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

  CanvasUI.register('canvas-banner', CanvasBanner);

  /* ======== canvas-button ======== */

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
      if (this.hasAttribute('disabled')) return;
      if (this.getAttribute('type') === 'submit') {
        var form = this.closest('form');
        if (form) form.requestSubmit();
      }
    }
  }

  CanvasUI.register('canvas-button', CanvasButton);

  /* ======== canvas-button-group ======== */

  class CanvasButtonGroup extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: inline-flex;
            vertical-align: baseline;
          }

          :host([fluid]) {
            display: flex;
            width: 100%;
          }

          .group {
            display: inline-flex;
            flex-direction: row;
          }

          :host([fluid]) .group {
            display: flex;
            width: 100%;
          }

          :host([fluid]) ::slotted(canvas-button) {
            flex: 1 0 auto;
          }

          /* Remove radius from all buttons, then restore outer edges */
          ::slotted(canvas-button) {
            --canvas-button-radius: 0;
            margin: 0;
          }

          ::slotted(canvas-button:first-child) {
            --canvas-button-radius: var(--canvas-button-group-radius, var(--radius, .28571429rem)) 0 0 var(--canvas-button-group-radius, var(--radius, .28571429rem));
          }

          ::slotted(canvas-button:last-child) {
            --canvas-button-radius: 0 var(--canvas-button-group-radius, var(--radius, .28571429rem)) var(--canvas-button-group-radius, var(--radius, .28571429rem)) 0;
          }

          ::slotted(canvas-button:only-child) {
            --canvas-button-radius: var(--canvas-button-group-radius, var(--radius, .28571429rem));
          }
        </style>
        <div class="group" role="group">
          <slot></slot>
        </div>
      `;
    }
  }

  CanvasUI.register('canvas-button-group', CanvasButtonGroup);

  /* ======== canvas-card ======== */

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
            box-sizing: border-box;
            width: 100%;
            border: 1px solid #d4d4d5;
            box-shadow: var(--canvas-card-shadow, 0 1px 2px 0 rgba(34, 36, 38, 0.15));
            border-radius: var(--radius, .28571429rem);
            background: var(--color-surface, #FFFFFF);
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            color: var(--color-text, rgba(0, 0, 0, 0.87));
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

          ::slotted(canvas-card-body:first-child),
          ::slotted(canvas-card-footer:first-child) {
            border-top-left-radius: calc(var(--radius, .28571429rem) - 1px);
            border-top-right-radius: calc(var(--radius, .28571429rem) - 1px);
          }

          ::slotted(canvas-card-body:last-child),
          ::slotted(canvas-card-footer:last-child) {
            border-bottom-left-radius: calc(var(--radius, .28571429rem) - 1px);
            border-bottom-right-radius: calc(var(--radius, .28571429rem) - 1px);
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

  CanvasUI.register('canvas-card', CanvasCard);
  CanvasUI.register('canvas-card-body', CanvasCardBody);
  CanvasUI.register('canvas-card-footer', CanvasCardFooter);

  /* ======== canvas-inline-row ======== */

  class CanvasInlineRow extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: flex;
            gap: var(--canvas-inline-row-gap, var(--space-small, 12px));
            align-items: flex-end;
            flex-wrap: wrap;
          }

          ::slotted([inline-role="grow"]),
          ::slotted(canvas-input),
          ::slotted(canvas-dropdown),
          ::slotted(canvas-combobox),
          ::slotted(canvas-multi-select),
          ::slotted(canvas-textarea) {
            flex: 1 0 var(--canvas-inline-row-item-min, 160px);
          }

          ::slotted([inline-role="natural"]),
          ::slotted(canvas-button),
          ::slotted(canvas-checkbox),
          ::slotted(canvas-radio),
          ::slotted(canvas-toggle) {
            flex: 0 0 auto;
          }
        </style>
        <slot></slot>
      `;
    }
  }

  CanvasUI.register('canvas-inline-row', CanvasInlineRow);

  /* ======== canvas-checkbox ======== */

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
            border: 1px solid rgba(34, 36, 38, 0.15);
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
      if (e.composedPath()[0] === this._input) return;
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

  CanvasUI.register('canvas-checkbox', CanvasCheckbox);

  /* ======== canvas-chip ======== */

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

  CanvasUI.register('canvas-chip', CanvasChip);

  /* ======== canvas-combobox ======== */

  /* canvas-combobox: searchable single-select dropdown with type-to-filter */
  class CanvasCombobox extends HTMLElement {
    static get observedAttributes() {
      return ['label', 'placeholder', 'value', 'disabled', 'required', 'error', 'name', 'empty-state', 'creatable', 'creatable-label'];
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
      this._creatable = false;
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
      if (name === 'creatable') {
        this._creatable = this.hasAttribute('creatable');
        if (this.shadowRoot.querySelector('.combobox')) this._checkEmpty();
        return;
      }
      if (name === 'creatable-label') {
        if (this.shadowRoot.querySelector('.combobox')) this._checkEmpty();
        return;
      }
      if (name === 'value') {
        var val = this.getAttribute('value');
        if (val !== this._selectedValue) this._selectByValue(val, true);
      }
      if (name === 'label' || name === 'placeholder' || name === 'error' || name === 'disabled' || name === 'empty-state') {
        if (this.shadowRoot.querySelector('.combobox')) {
          this._render();
          this._bindEvents();
        }
      }
    }

    get value() { return this._selectedValue || ''; }
    set value(v) {
      var str = v == null ? '' : String(v);
      if (this._creatable) {
        if (str === '') {
          this._commitText('', true);
          this.removeAttribute('value');
          return;
        }
        var match = this._options.find(function(o) { return o.value === str; });
        if (!match) {
          this._commitText(str, true);
          this.setAttribute('value', str);
          return;
        }
      }
      this._selectByValue(str, true);
      this.setAttribute('value', str);
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
      var emptyState = this.getAttribute('empty-state');
      var displayText = this._selectedText || '';

      var optionsHtml = '';
      for (var i = 0; i < this._options.length; i++) {
        var o = this._options[i];
        var classes = 'option';
        if (o.value === this._selectedValue) classes += ' selected';
        var attrs = 'role="option" data-value="' + o.value + '" data-index="' + i + '" title="' + o.label.replace(/"/g, '&quot;') + '"';
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
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          }
          .option:first-child { border-top: none; }
          .option:hover, .option.highlighted { background: rgba(0, 0, 0, 0.05); color: rgba(0, 0, 0, 0.95); }
          .option.selected { background: rgba(0, 0, 0, 0.05); color: rgba(0, 0, 0, 0.95); font-weight: 700; }
          .option[aria-disabled="true"] { color: #767676; cursor: not-allowed; }
          .option[aria-disabled="true"]:hover { background: transparent; }
          .option.hidden { display: none; }
          .empty { padding: .78571429rem 1.14285714rem; font-size: 1rem; color: rgba(0, 0, 0, 0.4); display: none; }
          .empty.visible { display: block; }
          .empty.creatable-hint { color: rgba(0, 0, 0, 0.55); cursor: pointer; border-top: 1px solid #fafafa; }
          .empty.creatable-hint:hover { background: rgba(0, 0, 0, 0.025); }
          .empty.creatable-hint .creatable-name { color: #1e70bf; font-weight: 600; }
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
            <li class="empty"><slot name="empty">${emptyState != null ? emptyState : 'No results'}</slot></li>
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
            } else if (self._creatable) {
              self._commitOrRestore();
              self._close();
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
                self._commitOrRestore();
              }
              self._close();
            }
            break;
        }
      });

      menu.addEventListener('click', function(e) {
        var opt = e.target.closest('.option');
        if (opt) {
          if (opt.getAttribute('aria-disabled') === 'true') return;
          self._selectByValue(opt.dataset.value, false);
          self._close();
          input.focus();
          return;
        }
        if (self._creatable) {
          var hint = e.target.closest('.empty.creatable-hint');
          if (hint) {
            self._commitOrRestore();
            self._close();
            input.focus();
          }
        }
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
      var typed = (input.value || '').trim();
      if (this._creatable && typed.length > 0) {
        this._filter(input.value);
      } else {
        this._showAll();
      }
      this._checkEmpty();
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

    _commitText(value, silent) {
      var v = value == null ? '' : String(value).trim();
      this._selectedValue = v;
      this._selectedText = v;
      this._previousText = v;
      this._internals.setFormValue(v);
      var input = this.shadowRoot.querySelector('.input');
      if (input) input.value = v;
      if (!silent) {
        this.dispatchEvent(new CustomEvent('change', { bubbles: true, composed: true }));
      }
    }

    _commitOrRestore() {
      if (!this._creatable) {
        this._restore();
        return;
      }
      var input = this.shadowRoot.querySelector('.input');
      var typed = (input && input.value || '').trim();
      var priorValue = this._selectedValue || '';
      var match = this._options.find(function(o) { return o.label.toLowerCase() === typed.toLowerCase(); });
      if (match) {
        if (match.value !== priorValue) {
          this._selectByValue(match.value, false);
        } else {
          this._restore();
        }
        return;
      }
      if (typed !== priorValue) {
        this._commitText(typed, false);
      } else if (input) {
        input.value = this._selectedText || '';
      }
    }

    _escapeHtml(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    _onDocClick(e) {
      if (!this.contains(e.target) && !this.shadowRoot.contains(e.target)) {
        if (this._open) {
          this._commitOrRestore();
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

    _showAll() {
      var items = this.shadowRoot.querySelectorAll('.option');
      for (var i = 0; i < items.length; i++) items[i].classList.remove('hidden');
    }

    _checkEmpty() {
      var visible = this.shadowRoot.querySelectorAll('.option:not(.hidden)');
      var empty = this.shadowRoot.querySelector('.empty');
      if (!empty) return;
      var input = this.shadowRoot.querySelector('.input');
      var typed = (input && input.value || '').trim();
      var showCreatableHint = this._creatable && visible.length === 0 && typed.length > 0;
      if (showCreatableHint) {
        var prefix = this.getAttribute('creatable-label') || 'New entry';
        empty.innerHTML = this._escapeHtml(prefix) + ' <span class="creatable-name">"' + this._escapeHtml(typed) + '"</span> will be created on save.';
        empty.classList.add('creatable-hint', 'visible');
      } else {
        if (empty.classList.contains('creatable-hint')) {
          var emptyState = this.getAttribute('empty-state');
          empty.innerHTML = '<slot name="empty">' + (emptyState != null ? this._escapeHtml(emptyState) : 'No results') + '</slot>';
          empty.classList.remove('creatable-hint');
        }
        if (visible.length === 0) empty.classList.add('visible');
        else empty.classList.remove('visible');
      }
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

  CanvasUI.register('canvas-combobox', CanvasCombobox);

  /* ======== canvas-divider ======== */

  class CanvasDivider extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._render();
      this.shadowRoot.querySelector('slot').addEventListener('slotchange', () => this._render());
    }

    static get observedAttributes() {
      return ['fitted', 'hidden'];
    }

    attributeChangedCallback() {
      this._render();
    }

    _render() {
      var slot = this.shadowRoot.querySelector('slot');
      var hasText = slot ? slot.assignedNodes().some(function (n) {
        return n.nodeType === Node.TEXT_NODE ? n.textContent.trim() !== '' : true;
      }) : false;

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
            margin: var(--canvas-divider-margin, 1rem 0);
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: .05em;
            color: var(--canvas-divider-color, var(--color-text, rgba(0, 0, 0, 0.85)));
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
            font-size: var(--canvas-divider-font-size, 0.85714286rem);
          }

          :host([fitted]) {
            margin: 0;
          }

          :host([hidden]) {
            display: block !important;
            border-color: transparent;
          }

          /* Plain rule (no text content) */
          .rule {
            border: none;
            border-top: 1px solid var(--canvas-divider-border, var(--color-border, rgba(34, 36, 38, 0.15)));
            margin: 0;
          }

          :host([hidden]) .rule {
            border-color: transparent;
          }

          /* Horizontal text-between-lines layout */
          .horizontal {
            display: table;
            white-space: nowrap;
            height: auto;
            text-align: center;
            width: 100%;
          }

          .horizontal::before,
          .horizontal::after {
            content: '';
            display: table-cell;
            width: 50%;
            background-repeat: no-repeat;
            background-image: linear-gradient(var(--canvas-divider-border, var(--color-border, rgba(34, 36, 38, 0.15))), var(--canvas-divider-border, var(--color-border, rgba(34, 36, 38, 0.15))));
            background-size: 100% 1px;
            background-position: center;
          }

          .horizontal::before {
            background-position: right 1em center;
          }

          .horizontal::after {
            background-position: left 1em center;
          }

          .horizontal slot {
            display: table-cell;
            vertical-align: middle;
            padding: 0;
          }
        </style>
        ${hasText
          ? '<div class="horizontal" role="separator"><slot></slot></div>'
          : '<hr class="rule" role="separator"><slot style="display:none"></slot>'}
      `;
    }
  }

  CanvasUI.register('canvas-divider', CanvasDivider);

  /* ======== canvas-dropdown ======== */

  class CanvasDropdown extends HTMLElement {
    static get observedAttributes() {
      return ['label', 'placeholder', 'value', 'disabled', 'required', 'error', 'name', 'size', 'empty-state'];
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
      if (name === 'label' || name === 'placeholder' || name === 'error' || name === 'disabled' || name === 'empty-state') {
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
      var emptyState = this.getAttribute('empty-state');
      var displayText = this._selectedText || '';
      var isPlaceholder = !displayText;

      var optionsHtml = '';
      for (var i = 0; i < this._options.length; i++) {
        var o = this._options[i];
        var classes = 'option';
        if (o.value === this._selectedValue) classes += ' selected';
        var attrs = 'role="option" data-value="' + o.value + '" data-index="' + i + '" title="' + o.label.replace(/"/g, '&quot;') + '"';
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
            width: 8px;
            height: 5px;
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
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
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

          .empty {
            padding: .78571429rem 1.14285714rem;
            font-size: 1rem;
            color: rgba(0, 0, 0, 0.4);
            display: none;
          }

          .empty.visible { display: block; }

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
          <svg class="arrow" viewBox="0 0 10 6" fill="#575757"><path d="M1 0h8a1 1 0 01.7 1.7l-4 4a1 1 0 01-1.4 0l-4-4A1 1 0 011 0z"/></svg>
          <ul class="menu" role="listbox">
            ${optionsHtml}
            <li class="empty"><slot name="empty">${emptyState != null ? emptyState : 'No options'}</slot></li>
          </ul>
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
      this._checkEmpty();
    }

    _close() {
      this._open = false;
      this._highlighted = -1;
      var dd = this.shadowRoot.querySelector('.dropdown');
      dd.classList.remove('open');
      dd.setAttribute('aria-expanded', 'false');
      this._clearHighlight();
    }

    _checkEmpty() {
      var options = this.shadowRoot.querySelectorAll('.option');
      var empty = this.shadowRoot.querySelector('.empty');
      if (!empty) return;
      if (options.length === 0) empty.classList.add('visible');
      else empty.classList.remove('visible');
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

  CanvasUI.register('canvas-dropdown', CanvasDropdown);

  /* ======== canvas-input ======== */

  class CanvasInput extends HTMLElement {
    static get observedAttributes() {
      return ['label', 'placeholder', 'required', 'error', 'disabled', 'value', 'name', 'type'];
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

          input {
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

          input:focus {
            border-color: var(--canvas-input-focus-border, #85b7d9);
            background: var(--canvas-input-bg, var(--color-surface, #FFFFFF));
            color: rgba(0, 0, 0, 0.8);
            box-shadow: none;
            outline: none;
          }

          input::placeholder {
            color: var(--canvas-input-placeholder, rgba(191, 191, 191, 0.87));
          }

          input:focus::placeholder {
            color: var(--canvas-input-focus-placeholder, rgba(115, 115, 115, 0.87));
          }

          input:disabled {
            background: var(--canvas-input-disabled-bg, var(--color-bg, #F5F5F5));
            cursor: not-allowed;
          }

          /* Neutralize WebKit date and time internal padding so type="date",
             type="time", type="datetime-local", type="month", and type="week"
             render at the same height as type="text". Without these resets
             two internal pseudos push the content box taller.
             ::-webkit-datetime-edit carries 1px top and 1px bottom padding.
             ::-webkit-calendar-picker-indicator is 1em tall with 2px padding
             on every side, so its 1em+4px outer box exceeds the declared
             line-height by about half a pixel and grows the flex row. */
          input::-webkit-datetime-edit,
          input::-webkit-datetime-edit-fields-wrapper {
            padding: 0;
          }
          input::-webkit-calendar-picker-indicator {
            padding: 0;
          }

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

          :host([error]) input {
            background: var(--canvas-input-error-bg, #fff6f6);
            border-color: var(--canvas-input-error-border, #e0b4b4);
            color: var(--canvas-input-error-text, #9f3a38);
          }

          :host([error]) input::placeholder {
            color: var(--canvas-input-error-border, #e0b4b4);
          }
        </style>
        <label part="label"></label>
        <input part="input" type="text">
        <span class="error-msg" part="error" aria-live="polite"></span>
      `;
      this._label = this.shadowRoot.querySelector('label');
      this._input = this.shadowRoot.querySelector('input');
      this._errorMsg = this.shadowRoot.querySelector('.error-msg');
      this._boundOnInput = this._onInput.bind(this);
      this._boundOnChange = this._onChange.bind(this);
    }

    connectedCallback() {
      this._input.addEventListener('input', this._boundOnInput);
      this._input.addEventListener('change', this._boundOnChange);
      this._syncAll();
    }

    disconnectedCallback() {
      this._input.removeEventListener('input', this._boundOnInput);
      this._input.removeEventListener('change', this._boundOnChange);
    }

    attributeChangedCallback(name, oldVal, newVal) {
      switch (name) {
        case 'label':
          this._label.textContent = newVal || '';
          break;
        case 'placeholder':
          this._input.placeholder = newVal || '';
          break;
        case 'required':
          var req = this.hasAttribute('required');
          this._input.required = req;
          this._input.setAttribute('aria-required', req);
          break;
        case 'disabled':
          var dis = this.hasAttribute('disabled');
          this._input.disabled = dis;
          break;
        case 'error':
          this._syncError();
          break;
        case 'value':
          if (newVal !== null) {
            this._input.value = newVal;
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

    get value() {
      return this._input.value;
    }

    set value(v) {
      this._input.value = v;
      this._internals.setFormValue(v);
    }

    get name() {
      return this.getAttribute('name');
    }

    _syncAll() {
      this._label.textContent = this.getAttribute('label') || '';
      this._input.placeholder = this.getAttribute('placeholder') || '';
      this._input.type = this.getAttribute('type') || 'text';

      var req = this.hasAttribute('required');
      this._input.required = req;
      this._input.setAttribute('aria-required', req);

      var dis = this.hasAttribute('disabled');
      this._input.disabled = dis;

      var val = this.getAttribute('value');
      if (val !== null) {
        this._input.value = val;
        this._internals.setFormValue(val);
      }

      this._syncError();
    }

    _syncError() {
      var err = this.getAttribute('error');
      if (err) {
        this._errorMsg.textContent = err;
        this._input.setAttribute('aria-invalid', 'true');
        this._errorMsg.id = 'err';
        this._input.setAttribute('aria-describedby', 'err');
      } else {
        this._errorMsg.textContent = '';
        this._input.removeAttribute('aria-invalid');
        this._input.removeAttribute('aria-describedby');
      }
    }

    _onInput(e) {
      e.stopPropagation();
      this._internals.setFormValue(this._input.value);
      this.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    }

    _onChange(e) {
      e.stopPropagation();
      this._internals.setFormValue(this._input.value);
      this.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    }
  }

  CanvasUI.register('canvas-input', CanvasInput);

  /* ======== canvas-loader ======== */

  class CanvasLoader extends HTMLElement {
    static get observedAttributes() {
      return ['size', 'mode', 'centered', 'inverted', 'backdrop', 'text', 'aria-label'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
    }

    connectedCallback() {
      this._render();
    }

    attributeChangedCallback() {
      if (this.shadowRoot) this._render();
    }

    _render() {
      const text = this.getAttribute('text');
      const label = this.getAttribute('aria-label') || 'Loading';

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
          }

          .container {
            display: flex;
            justify-content: center;
            align-items: center;
            flex-direction: column;
          }

          /* Inline (default) */
          .container {
            min-height: var(--canvas-loader-min-height, auto);
          }

          :host([centered]) .container {
            width: 100%;
          }

          /* Overlay */
          :host([mode="overlay"]) {
            display: contents;
          }

          :host([mode="overlay"]) .container {
            position: absolute;
            inset: 0;
            z-index: var(--canvas-loader-z-index, 1000);
            background: var(--canvas-loader-backdrop, rgba(255, 255, 255, 0.85));
          }

          :host([mode="overlay"][backdrop="dark"]) .container {
            background: var(--canvas-loader-backdrop-dark, rgba(0, 0, 0, 0.5));
          }

          :host([mode="overlay"][backdrop="none"]) .container {
            background: none;
          }

          /* Fullscreen */
          :host([mode="fullscreen"]) {
            display: contents;
          }

          :host([mode="fullscreen"]) .container {
            position: fixed;
            inset: 0;
            z-index: var(--canvas-loader-z-index, 1000);
            background: var(--canvas-loader-backdrop, rgba(255, 255, 255, 0.85));
          }

          :host([mode="fullscreen"][backdrop="dark"]) .container {
            background: var(--canvas-loader-backdrop-dark, rgba(0, 0, 0, 0.5));
          }

          :host([mode="fullscreen"][backdrop="none"]) .container {
            background: none;
          }

          /* Spinner */
          .spinner {
            position: relative;
            width: var(--canvas-loader-size, 2.28571429rem);
            height: var(--canvas-loader-size, 2.28571429rem);
            flex-shrink: 0;
          }

          .spinner::before,
          .spinner::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            border-radius: 500rem;
            box-sizing: border-box;
          }

          .spinner::before {
            border: var(--canvas-loader-border-width, .2em) solid var(--canvas-loader-track-color, rgba(0, 0, 0, 0.1));
          }

          .spinner::after {
            border-width: var(--canvas-loader-border-width, .2em);
            border-style: solid;
            border-color: var(--canvas-loader-arc-color, #767676) transparent transparent;
            animation: loader .6s linear infinite;
          }

          :host([inverted]) .spinner::before {
            border-color: var(--canvas-loader-track-color-inverted, rgba(255, 255, 255, 0.15));
          }

          :host([inverted]) .spinner::after {
            border-color: var(--canvas-loader-arc-color-inverted, #fff) transparent transparent;
          }

          /* Sizes */
          :host([size="mini"]) .spinner {
            width: var(--canvas-loader-size-mini, 1rem);
            height: var(--canvas-loader-size-mini, 1rem);
          }

          :host([size="small"]) .spinner {
            width: var(--canvas-loader-size-small, 1.71428571rem);
            height: var(--canvas-loader-size-small, 1.71428571rem);
          }

          :host([size="large"]) .spinner {
            width: var(--canvas-loader-size-large, 3.42857143rem);
            height: var(--canvas-loader-size-large, 3.42857143rem);
          }

          /* Text label */
          .text {
            display: block;
            margin-top: var(--canvas-loader-text-gap, .78571429rem);
            font-family: var(--canvas-loader-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
            font-size: var(--canvas-loader-font-size, 1em);
            font-style: normal;
            color: var(--canvas-loader-text-color, rgba(0, 0, 0, 0.87));
          }

          :host([size="mini"]) .text { font-size: var(--canvas-loader-font-size-mini, .78571429em); }
          :host([size="small"]) .text { font-size: var(--canvas-loader-font-size-small, .92857143em); }
          :host([size="large"]) .text { font-size: var(--canvas-loader-font-size-large, 1.14285714em); }

          :host([inverted]) .text {
            color: var(--canvas-loader-text-color-inverted, rgba(255, 255, 255, 0.9));
          }

          :host([mode="overlay"][backdrop="dark"]) .text,
          :host([mode="fullscreen"][backdrop="dark"]) .text {
            color: var(--canvas-loader-text-color-inverted, rgba(255, 255, 255, 0.9));
          }

          :host([mode="overlay"][backdrop="dark"]) .spinner::before,
          :host([mode="fullscreen"][backdrop="dark"]) .spinner::before {
            border-color: var(--canvas-loader-track-color-inverted, rgba(255, 255, 255, 0.15));
          }

          :host([mode="overlay"][backdrop="dark"]) .spinner::after,
          :host([mode="fullscreen"][backdrop="dark"]) .spinner::after {
            border-color: var(--canvas-loader-arc-color-inverted, #fff) transparent transparent;
          }

          @keyframes loader {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
        </style>
        <div class="container">
          <div class="spinner" role="status" aria-label="${label}"></div>
          ${text ? `<span class="text">${text}</span>` : ''}
        </div>
      `;
    }
  }

  CanvasUI.register('canvas-loader', CanvasLoader);

  /* ======== canvas-menu-button ======== */

  /* canvas-menu-button: button that opens a menu of actions below.
     Not form associated. Uses role="menu" with role="menuitem" children.
     Trigger is slotted via slot="trigger", or a default ghost button is rendered.
     Items are canvas-option children. Clicking an option dispatches a 'select'
     event with detail.value and detail.label. */

  class CanvasMenuButton extends HTMLElement {
    static get observedAttributes() {
      return ['disabled', 'align', 'direction'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._options = [];
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
      }, 0);
      document.addEventListener('click', this._onDocClick);
    }

    disconnectedCallback() {
      document.removeEventListener('click', this._onDocClick);
    }

    attributeChangedCallback(name) {
      if (!this.shadowRoot.querySelector('.menu-button')) return;
      if (name === 'disabled' || name === 'align' || name === 'direction') {
        this._render();
        this._bindEvents();
      }
    }

    _readOptions() {
      this._children = [];
      this._options = [];
      var kids = this.children;
      for (var i = 0; i < kids.length; i++) {
        var el = kids[i];
        if (el.getAttribute && el.getAttribute('slot') === 'trigger') continue;
        var tag = el.tagName ? el.tagName.toLowerCase() : '';
        if (tag === 'canvas-option') {
          var record = {
            type: 'option',
            value: el.getAttribute('value') || el.textContent.trim(),
            label: el.getAttribute('label') || el.textContent.trim(),
            html: el.innerHTML,
            disabled: el.hasAttribute('disabled')
          };
          this._children.push(record);
          this._options.push(record);
        } else if (tag === 'hr') {
          this._children.push({ type: 'divider' });
        }
      }
    }

    _render() {
      var optionsHtml = '';
      for (var i = 0; i < this._children.length; i++) {
        var c = this._children[i];
        if (c.type === 'divider') {
          optionsHtml += '<li class="divider" role="separator"></li>';
          continue;
        }
        var attrs = 'role="menuitem" tabindex="-1" data-value="' + c.value + '"';
        if (c.disabled) attrs += ' aria-disabled="true"';
        optionsHtml += '<li class="option" ' + attrs + '>' + c.html + '</li>';
      }

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: inline-block;
            position: relative;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
          }

          :host([disabled]) { opacity: 0.45; pointer-events: none; }

          .menu-button { position: relative; }

          .trigger-wrap { display: inline-flex; }

          .default-trigger {
            display: inline-flex;
            align-items: center;
            gap: var(--space-tiny, 8px);
            padding: .67857143em 1.5em;
            font-size: 1rem;
            font-weight: 700;
            font-family: inherit;
            line-height: 1.21428571em;
            background: #e0e1e2;
            color: rgba(0, 0, 0, 0.6);
            border: 1px solid transparent;
            border-radius: var(--radius, .28571429rem);
            cursor: pointer;
            transition: background-color 0.1s ease, color 0.1s ease;
          }
          .default-trigger:hover {
            background: #cacbcd;
            color: rgba(0, 0, 0, 0.8);
          }
          .default-trigger:focus-visible {
            outline: var(--focus-ring, 2px solid #2185D0);
            outline-offset: 2px;
          }
          .default-arrow { width: 8px; height: 5px; }

          .menu {
            display: none;
            position: absolute;
            top: 100%;
            left: 0;
            min-width: 180px;
            max-width: 320px;
            margin: 2px 0 0;
            padding: 0;
            max-height: 16.02857143rem;
            overflow-y: auto;
            background: var(--color-surface, #FFFFFF);
            border: 1px solid rgba(34, 36, 38, 0.15);
            border-radius: var(--radius, .28571429rem);
            box-shadow: 0 2px 4px 0 rgba(34, 36, 38, 0.12), 0 2px 10px 0 rgba(34, 36, 38, 0.15);
            z-index: 100;
            list-style: none;
          }

          :host([align="end"]) .menu,
          .menu-button[data-placement-align="end"] .menu { left: auto; right: 0; }

          :host([direction="up"]) .menu,
          .menu-button[data-placement-direction="up"] .menu {
            top: auto;
            bottom: 100%;
            margin: 0 0 2px;
          }

          .menu-button.open .menu { display: block; }

          .option {
            padding: .78571429rem 1.14285714rem;
            font-size: 1rem;
            line-height: 1.0625rem;
            color: var(--color-text, rgba(0, 0, 0, 0.87));
            cursor: pointer;
            transition: background 0.1s ease;
            outline: none;
          }

          .option:hover,
          .option.highlighted {
            background: rgba(0, 0, 0, 0.05);
            color: rgba(0, 0, 0, 0.95);
          }

          .option[aria-disabled="true"] {
            color: #767676;
            cursor: not-allowed;
          }

          .option[aria-disabled="true"]:hover {
            background: transparent;
            color: #767676;
          }

          .divider {
            height: 0;
            margin: .28571429rem 0;
            padding: 0;
            border-top: 1px solid rgba(34, 36, 38, 0.15);
            list-style: none;
          }
        </style>
        <div class="menu-button">
          <span class="trigger-wrap">
            <slot name="trigger">
              <button class="default-trigger" type="button" aria-haspopup="menu" aria-expanded="false">
                <span>Actions</span>
                <svg class="default-arrow" viewBox="0 0 10 6" fill="currentColor"><path d="M1 0h8a1 1 0 01.7 1.7l-4 4a1 1 0 01-1.4 0l-4-4A1 1 0 011 0z"/></svg>
              </button>
            </slot>
          </span>
          <ul class="menu" role="menu" tabindex="-1">${optionsHtml}</ul>
        </div>
      `;
    }

    _bindEvents() {
      var self = this;
      var triggerWrap = this.shadowRoot.querySelector('.trigger-wrap');

      triggerWrap.addEventListener('click', function(e) {
        if (self.hasAttribute('disabled')) return;
        if (self._open) self._close();
        else self._openMenu();
      });

      triggerWrap.addEventListener('keydown', function(e) {
        if (self.hasAttribute('disabled')) return;
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          self._openMenu();
          self._highlightIndex(0);
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          self._openMenu();
          var opts = self._enabledOptions();
          if (opts.length) self._highlightIndex(opts.length - 1);
        }
      });

      var menu = this.shadowRoot.querySelector('.menu');

      menu.addEventListener('click', function(e) {
        var opt = e.target.closest('.option');
        if (!opt) return;
        if (opt.getAttribute('aria-disabled') === 'true') return;
        self._selectOption(opt.dataset.value);
      });

      menu.addEventListener('keydown', function(e) {
        switch (e.key) {
          case 'ArrowDown':
            e.preventDefault();
            self._highlightNext(1);
            break;
          case 'ArrowUp':
            e.preventDefault();
            self._highlightNext(-1);
            break;
          case 'Home':
            e.preventDefault();
            self._highlightIndex(0);
            break;
          case 'End':
            e.preventDefault();
            var opts = self._enabledOptions();
            if (opts.length) self._highlightIndex(opts.length - 1);
            break;
          case 'Enter':
          case ' ':
            e.preventDefault();
            if (self._highlighted >= 0) {
              var enabledOpts = self._enabledOptions();
              if (enabledOpts[self._highlighted]) {
                self._selectOption(enabledOpts[self._highlighted].dataset.value);
              }
            }
            break;
          case 'Escape':
            e.preventDefault();
            self._close();
            self._focusTrigger();
            break;
          case 'Tab':
            self._close();
            break;
        }
      });
    }

    _enabledOptions() {
      return this.shadowRoot.querySelectorAll('.option:not([aria-disabled="true"])');
    }

    _openMenu() {
      if (this._open) return;
      this._open = true;
      this._highlighted = -1;
      var root = this.shadowRoot.querySelector('.menu-button');
      root.classList.add('open');
      this._computePlacement();
      var defaultBtn = this.shadowRoot.querySelector('.default-trigger');
      if (defaultBtn) defaultBtn.setAttribute('aria-expanded', 'true');
      var menu = this.shadowRoot.querySelector('.menu');
      menu.focus();
      this.dispatchEvent(new CustomEvent('open', { bubbles: true, composed: true }));
    }

    _computePlacement() {
      var root = this.shadowRoot.querySelector('.menu-button');
      var menu = this.shadowRoot.querySelector('.menu');

      root.removeAttribute('data-placement-direction');
      root.removeAttribute('data-placement-align');

      var placement = computeAutoPlacement(root.getBoundingClientRect(), menu, {
        direction: this.getAttribute('direction'),
        align: this.getAttribute('align')
      });

      if (placement.direction) root.setAttribute('data-placement-direction', placement.direction);
      if (placement.align) root.setAttribute('data-placement-align', placement.align);
    }

    _close() {
      if (!this._open) return;
      this._open = false;
      this._highlighted = -1;
      var root = this.shadowRoot.querySelector('.menu-button');
      root.classList.remove('open');
      var defaultBtn = this.shadowRoot.querySelector('.default-trigger');
      if (defaultBtn) defaultBtn.setAttribute('aria-expanded', 'false');
      this._clearHighlight();
      this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
    }

    _focusTrigger() {
      var slot = this.shadowRoot.querySelector('slot[name="trigger"]');
      var assigned = slot ? slot.assignedElements() : [];
      if (assigned.length && typeof assigned[0].focus === 'function') {
        assigned[0].focus();
        return;
      }
      var defaultBtn = this.shadowRoot.querySelector('.default-trigger');
      if (defaultBtn) defaultBtn.focus();
    }

    _onDocClick(e) {
      if (!this.contains(e.target) && !this.shadowRoot.contains(e.target)) {
        if (this._open) this._close();
      }
    }

    _selectOption(val) {
      var opt = this._options.find(function(o) { return o.value === val; });
      if (!opt || opt.disabled) return;
      this.dispatchEvent(new CustomEvent('select', {
        bubbles: true,
        composed: true,
        detail: { value: opt.value, label: opt.label }
      }));
      this._close();
      this._focusTrigger();
    }

    _highlightNext(dir) {
      var opts = this._enabledOptions();
      if (opts.length === 0) return;
      this._highlighted += dir;
      if (this._highlighted < 0) this._highlighted = opts.length - 1;
      if (this._highlighted >= opts.length) this._highlighted = 0;
      this._applyHighlight(opts);
    }

    _highlightIndex(index) {
      var opts = this._enabledOptions();
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
      for (var i = 0; i < items.length; i++) {
        items[i].classList.remove('highlighted');
      }
    }
  }

  CanvasUI.register('canvas-menu-button', CanvasMenuButton);

  /* ======== canvas-popover ======== */

  /* canvas-popover: click triggered anchored container for arbitrary content.
     Covers filter forms, column pickers, legends, preference sheets, and bulk
     action panels. Uses role="dialog" with aria-modal="false" so it is a non
     modal dialog. For content that needs true modality (confirmations,
     blocking flows), use canvas-modal. Shares the auto-flip placement helper
     with canvas-menu-button. */

  class CanvasPopover extends HTMLElement {
    static get observedAttributes() {
      return ['open', 'align', 'direction', 'size', 'label', 'pointer'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._isActive = false;
      this._onDocClick = this._onDocClick.bind(this);
      this._onKeyDown = this._onKeyDown.bind(this);
      this._onReposition = this._onReposition.bind(this);
    }

    connectedCallback() {
      var self = this;
      setTimeout(function() {
        self._render();
        self._bindEvents();
        self._wireTriggerAria();
        if (self.hasAttribute('open')) self._activate();
      }, 0);
      document.addEventListener('click', this._onDocClick);
      document.addEventListener('keydown', this._onKeyDown);
    }

    disconnectedCallback() {
      document.removeEventListener('click', this._onDocClick);
      document.removeEventListener('keydown', this._onKeyDown);
      this._unbindTracking();
    }

    attributeChangedCallback(name, oldVal, newVal) {
      if (!this.shadowRoot.querySelector('.popover-root')) return;
      if (name === 'open') {
        if (newVal !== null && !this._isActive) this._activate();
        else if (newVal === null && this._isActive) this._deactivate();
        return;
      }
      if (name === 'label') {
        var surface = this.shadowRoot.querySelector('.surface');
        if (surface) surface.setAttribute('aria-label', newVal || '');
        return;
      }
      if (name === 'align' || name === 'direction' || name === 'pointer') {
        if (this._isActive) this._computePlacement();
      }
    }

    open() {
      if (!this.hasAttribute('open')) this.setAttribute('open', '');
    }

    close() {
      if (this.hasAttribute('open')) this.removeAttribute('open');
    }

    _render() {
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: inline-block;
            position: relative;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
          }

          .trigger-wrap { display: inline-flex; }

          .surface {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            padding: 1em 1.14285714em;
            width: max-content;
            max-width: min(var(--canvas-popover-max-width, 360px), calc(100vw - 8px));
            max-height: min(var(--canvas-popover-max-height, 100vh), calc(100vh - 8px), var(--canvas-popover-available-height, 100vh));
            background: var(--color-surface, #FFFFFF);
            border: 1px solid #d4d4d5;
            border-radius: var(--radius, .28571429rem);
            box-shadow: 0 2px 4px 0 rgba(34, 36, 38, 0.12), 0 2px 10px 0 rgba(34, 36, 38, 0.15);
            z-index: 2000;
            color: var(--color-text, rgba(0, 0, 0, 0.87));
            font-size: 1rem;
            line-height: 1.4285714;
            box-sizing: border-box;
            overflow-wrap: anywhere;
          }

          :host([size="sm"]) .surface { max-width: min(var(--canvas-popover-max-width, 280px), calc(100vw - 8px)); }
          :host([size="md"]) .surface { max-width: min(var(--canvas-popover-max-width, 360px), calc(100vw - 8px)); }
          :host([size="lg"]) .surface { max-width: min(var(--canvas-popover-max-width, 480px), calc(100vw - 8px)); }
          :host([size="auto"]) .surface { max-width: min(var(--canvas-popover-max-width, calc(100vw - 16px)), calc(100vw - 16px)); }

          .popover-root.open .surface { display: block; }

          .surface:focus { outline: none; }

          .pointer {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            pointer-events: none;
            line-height: 0;
          }

          .pointer-arrow {
            z-index: 1999;
            filter: drop-shadow(0 2px 4px rgba(34, 36, 38, 0.12)) drop-shadow(0 2px 10px rgba(34, 36, 38, 0.15));
          }

          .pointer-arrow svg { display: block; fill: #d4d4d5; stroke: none; }

          .pointer-cover { z-index: 2001; }

          .pointer-cover svg { display: block; fill: var(--color-surface, #FFFFFF); stroke: none; }

          :host([pointer]) .popover-root.open .pointer { display: block; }
        </style>
        <div class="popover-root">
          <span class="trigger-wrap">
            <slot name="trigger"></slot>
          </span>
          <div class="surface" role="dialog" aria-modal="false" tabindex="-1">
            <slot></slot>
          </div>
          <div class="pointer pointer-arrow" aria-hidden="true"></div>
          <div class="pointer pointer-cover" aria-hidden="true"></div>
        </div>
      `;
      var surface = this.shadowRoot.querySelector('.surface');
      surface.setAttribute('aria-label', this.getAttribute('label') || '');
    }

    _bindEvents() {
      var self = this;
      var triggerWrap = this.shadowRoot.querySelector('.trigger-wrap');

      triggerWrap.addEventListener('click', function() {
        if (self.hasAttribute('open')) self.close();
        else self.open();
      });

      var triggerSlot = this.shadowRoot.querySelector('slot[name="trigger"]');
      triggerSlot.addEventListener('slotchange', function() {
        self._wireTriggerAria();
      });
    }

    _wireTriggerAria() {
      var slot = this.shadowRoot.querySelector('slot[name="trigger"]');
      if (!slot) return;
      var assigned = slot.assignedElements();
      var expanded = this.hasAttribute('open') ? 'true' : 'false';
      for (var i = 0; i < assigned.length; i++) {
        assigned[i].setAttribute('aria-haspopup', 'dialog');
        assigned[i].setAttribute('aria-expanded', expanded);
      }
    }

    _activate() {
      if (this._isActive) return;
      this._isActive = true;
      var root = this.shadowRoot.querySelector('.popover-root');
      root.classList.add('open');
      var surface = this.shadowRoot.querySelector('.surface');
      surface.style.visibility = '';
      this._computePlacement();
      this._wireTriggerAria();
      var first = this._firstFocusable();
      if (first) first.focus();
      else surface.focus();
      this._bindTracking();
      this.dispatchEvent(new CustomEvent('open', { bubbles: true, composed: true }));
    }

    _deactivate() {
      if (!this._isActive) return;
      this._isActive = false;
      var root = this.shadowRoot.querySelector('.popover-root');
      root.classList.remove('open');
      this._wireTriggerAria();
      this._unbindTracking();
      this._focusTrigger();
      this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
    }

    _computePlacement() {
      var surface = this.shadowRoot.querySelector('.surface');
      var triggerWrap = this.shadowRoot.querySelector('.trigger-wrap');

      surface.style.removeProperty('--canvas-popover-available-height');

      var triggerRect = triggerWrap.getBoundingClientRect();
      var hasPointer = this.hasAttribute('pointer');
      // When the pointer is enabled, adopt the tooltip recipe so the distance
      // between trigger and surface matches canvas-tooltip and the arrow can
      // tuck into the gap. Without a pointer, keep the compact 6 px gutter
      // and 4 px viewport edge so existing popover adopters see no shift.
      var gutter = hasPointer ? ANCHOR_GAP : 6;
      var viewportEdge = hasPointer ? ANCHOR_EDGE : 4;

      var spaceBelow = window.innerHeight - triggerRect.bottom - gutter - viewportEdge;
      var spaceAbove = triggerRect.top - gutter - viewportEdge;
      if (spaceBelow < 0) spaceBelow = 0;
      if (spaceAbove < 0) spaceAbove = 0;

      var contentHeight = surface.scrollHeight;
      var explicitDirection = this.getAttribute('direction');
      var direction;
      if (explicitDirection === 'up' || explicitDirection === 'down') {
        direction = explicitDirection;
      } else if (contentHeight <= spaceBelow) {
        direction = 'down';
      } else if (spaceAbove > spaceBelow) {
        direction = 'up';
      } else {
        direction = 'down';
      }

      var availableSpace = direction === 'up' ? spaceAbove : spaceBelow;
      surface.style.setProperty('--canvas-popover-available-height', availableSpace + 'px');

      var surfaceWidth = surface.offsetWidth;
      var surfaceHeight = surface.offsetHeight;

      var explicitAlign = this.getAttribute('align');
      var align;
      if (explicitAlign === 'end' || explicitAlign === 'start') {
        align = explicitAlign;
      } else {
        var spaceRight = window.innerWidth - triggerRect.left - viewportEdge;
        var spaceLeft = triggerRect.right - viewportEdge;
        if (spaceRight < surfaceWidth && spaceLeft >= surfaceWidth) {
          align = 'end';
        } else {
          align = 'start';
        }
      }

      var top, left;
      if (direction === 'up') {
        top = triggerRect.top - surfaceHeight - gutter;
      } else {
        top = triggerRect.bottom + gutter;
      }

      if (align === 'end') {
        left = triggerRect.right - surfaceWidth;
      } else {
        left = triggerRect.left;
      }

      // Far edge first, near edge second. When the surface is wider than the
      // viewport minus the edge margin on both sides, the near edge wins and
      // overflow happens on the far side instead of producing a negative left.
      if (left + surfaceWidth > window.innerWidth - viewportEdge) {
        left = window.innerWidth - surfaceWidth - viewportEdge;
      }
      if (left < viewportEdge) left = viewportEdge;
      if (top < viewportEdge) top = viewportEdge;

      surface.style.top = top + 'px';
      surface.style.left = left + 'px';

      if (hasPointer) {
        this._applyPointer(triggerRect, left, top, surfaceWidth, surfaceHeight, direction);
      }
    }

    _applyPointer(triggerRect, surfaceLeft, surfaceTop, surfaceWidth, surfaceHeight, direction) {
      var arrow = this.shadowRoot.querySelector('.pointer-arrow');
      var cover = this.shadowRoot.querySelector('.pointer-cover');
      if (!arrow || !cover) return;

      // The arrow points toward the trigger. direction 'down' means the
      // surface sits below the trigger and the arrow hangs off the top edge
      // pointing up. direction 'up' means the surface sits above the trigger
      // and the arrow hangs off the bottom edge pointing down. 5 px of the
      // 7 px arrow sits outside the surface, 2 px overlaps the surface so the
      // cover can hide the 1 px surface border that the arrow crosses.
      var tipUp = '<svg width="' + ANCHOR_ARROW_SIZE + '" height="' + ANCHOR_ARROW_DEPTH + '" viewBox="0 0 ' + ANCHOR_ARROW_SIZE + ' ' + ANCHOR_ARROW_DEPTH + '"><path d="M0 ' + ANCHOR_ARROW_DEPTH + ' L' + ANCHOR_ARROW_HALF + ' 0 L' + ANCHOR_ARROW_SIZE + ' ' + ANCHOR_ARROW_DEPTH + '"/></svg>';
      var tipDown = '<svg width="' + ANCHOR_ARROW_SIZE + '" height="' + ANCHOR_ARROW_DEPTH + '" viewBox="0 0 ' + ANCHOR_ARROW_SIZE + ' ' + ANCHOR_ARROW_DEPTH + '"><path d="M0 0 L' + ANCHOR_ARROW_HALF + ' ' + ANCHOR_ARROW_DEPTH + ' L' + ANCHOR_ARROW_SIZE + ' 0"/></svg>';
      var svg = direction === 'up' ? tipDown : tipUp;
      arrow.innerHTML = svg;
      cover.innerHTML = svg;

      // Trigger center on the horizontal axis, clamped so the arrow does not
      // slide into the surface border radius. The same clamp math the tooltip
      // uses so a pointer popover near a viewport edge keeps its arrow tip on
      // the trigger while the surface shifts inward.
      var triggerCenterX = triggerRect.left + triggerRect.width / 2;
      var idealLeft = triggerCenterX - ANCHOR_ARROW_HALF;
      var minLeft = surfaceLeft + ANCHOR_ARROW_CORNER_INSET;
      var maxLeft = surfaceLeft + surfaceWidth - ANCHOR_ARROW_CORNER_INSET - ANCHOR_ARROW_SIZE;
      if (maxLeft < minLeft) maxLeft = minLeft;
      if (idealLeft < minLeft) idealLeft = minLeft;
      if (idealLeft > maxLeft) idealLeft = maxLeft;

      var arrowTop;
      var coverTop;
      if (direction === 'up') {
        arrowTop = surfaceTop + surfaceHeight - 2;
        coverTop = surfaceTop + surfaceHeight - 3;
      } else {
        arrowTop = surfaceTop - (ANCHOR_ARROW_DEPTH - 2);
        coverTop = surfaceTop - (ANCHOR_ARROW_DEPTH - 3);
      }

      arrow.style.left = idealLeft + 'px';
      arrow.style.top = arrowTop + 'px';
      cover.style.left = idealLeft + 'px';
      cover.style.top = coverTop + 'px';
    }

    _bindTracking() {
      document.addEventListener('scroll', this._onReposition, { capture: true, passive: true });
      window.addEventListener('resize', this._onReposition, { passive: true });
    }

    _unbindTracking() {
      document.removeEventListener('scroll', this._onReposition, { capture: true });
      window.removeEventListener('resize', this._onReposition);
    }

    _onReposition() {
      if (!this._isActive) return;
      if (this.hasAttribute('dismiss-on-scroll')) {
        this.close();
        return;
      }
      var triggerWrap = this.shadowRoot.querySelector('.trigger-wrap');
      var surface = this.shadowRoot.querySelector('.surface');
      var arrow = this.shadowRoot.querySelector('.pointer-arrow');
      var cover = this.shadowRoot.querySelector('.pointer-cover');
      var triggerRect = triggerWrap.getBoundingClientRect();
      var outOfView = triggerRect.bottom < 0 || triggerRect.top > window.innerHeight;
      if (outOfView) {
        surface.style.visibility = 'hidden';
        if (arrow) arrow.style.visibility = 'hidden';
        if (cover) cover.style.visibility = 'hidden';
        return;
      }
      surface.style.visibility = '';
      if (arrow) arrow.style.visibility = '';
      if (cover) cover.style.visibility = '';
      this._computePlacement();
    }

    _firstFocusable() {
      var sel = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"]), canvas-button, canvas-input, canvas-textarea, canvas-date-input, canvas-dropdown, canvas-combobox, canvas-multi-select, canvas-checkbox, canvas-radio, canvas-toggle, canvas-menu-button';
      return this.querySelector(sel);
    }

    _focusTrigger() {
      var slot = this.shadowRoot.querySelector('slot[name="trigger"]');
      if (!slot) return;
      var assigned = slot.assignedElements();
      if (assigned.length && typeof assigned[0].focus === 'function') {
        assigned[0].focus();
      }
    }

    _onDocClick(e) {
      if (!this._isActive) return;
      if (this.contains(e.target)) return;
      this.dispatchEvent(new CustomEvent('cancel', { bubbles: true, composed: true }));
      this.close();
    }

    _onKeyDown(e) {
      if (!this._isActive) return;
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      this.dispatchEvent(new CustomEvent('cancel', { bubbles: true, composed: true }));
      this.close();
    }

  }

  CanvasUI.register('canvas-popover', CanvasPopover);

  /* ======== canvas-modal ======== */

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
  CanvasUI.register('canvas-modal-header', CanvasModalHeader);

  /* canvas-modal-content: padded content area */
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
  CanvasUI.register('canvas-modal-content', CanvasModalContent);

  /* canvas-modal-footer: actions bar */
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
  CanvasUI.register('canvas-modal-footer', CanvasModalFooter);

  /* canvas-modal: the overlay container */
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
      var children = el.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"]), canvas-button, canvas-input, canvas-dropdown, canvas-combobox, canvas-multi-select, canvas-menu-button, canvas-popover');
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

  CanvasUI.register('canvas-modal', CanvasModal);

  /* ======== canvas-multi-select ======== */

  /* canvas-multi-select: multi-value select with chips, type-to-filter, and form association */
  class CanvasMultiSelect extends HTMLElement {
    static get observedAttributes() {
      return ['label', 'placeholder', 'disabled', 'required', 'error', 'name', 'empty-state'];
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
      if (name === 'label' || name === 'placeholder' || name === 'error' || name === 'disabled' || name === 'empty-state') {
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
      var emptyState = this.getAttribute('empty-state');

      var optionsHtml = '';
      for (var i = 0; i < this._options.length; i++) {
        var o = this._options[i];
        var sel = this._selected.indexOf(o.value) >= 0;
        var attrs = 'role="option" data-value="' + o.value + '" data-index="' + i + '" title="' + o.label.replace(/"/g, '&quot;') + '"';
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
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
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
            <li class="empty"><slot name="empty">${emptyState != null ? emptyState : 'No results'}</slot></li>
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

  CanvasUI.register('canvas-multi-select', CanvasMultiSelect);

  /* ======== canvas-progress ======== */

  class CanvasProgress extends HTMLElement {
    static get observedAttributes() {
      return ['value', 'color', 'size', 'active', 'label'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._render();
    }

    attributeChangedCallback() {
      this._render();
    }

    _render() {
      var value = Math.max(0, Math.min(100, parseFloat(this.getAttribute('value')) || 0));
      var color = this.getAttribute('color') || 'blue';
      var showLabel = this.hasAttribute('label');

      var colorMap = {
        blue: '#2185d0',
        grey: '#767676',
        green: '#21ba45',
        red: '#db2828',
        orange: '#f2711c'
      };

      var barColor = colorMap[color] || colorMap.blue;

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
          }

          .track {
            position: relative;
            max-width: 100%;
            background: var(--canvas-progress-track, rgba(0, 0, 0, 0.1));
            border-radius: var(--radius, .28571429rem);
            overflow: hidden;
          }

          .bar {
            display: block;
            position: relative;
            min-width: 0;
            background: var(--canvas-progress-bar, ${barColor});
            border-radius: var(--radius, .28571429rem);
            transition: width 0.1s ease, background-color 0.1s ease;
          }

          /* Default size */
          .bar { height: 1.75em; }

          /* Size variants */
          :host([size="small"]) .bar { height: 1em; }
          :host([size="tiny"]) .bar { height: 0.5em; }

          /* Label inside bar */
          .label {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 0.92857143em;
            font-weight: 700;
            color: rgba(255, 255, 255, 0.7);
            white-space: nowrap;
            line-height: 1;
            font-family: var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
          }

          :host([size="tiny"]) .label { display: none; }

          /* Active pulsing animation */
          @keyframes progress-active {
            0% { opacity: 0.3; width: 0; }
            100% { opacity: 0; width: 100%; }
          }

          :host([active]) .bar::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: #fff;
            border-radius: var(--radius, .28571429rem);
            animation: progress-active 2s ease infinite;
          }
        </style>
        <div class="track">
          <div class="bar" role="progressbar" aria-valuenow="${value}" aria-valuemin="0" aria-valuemax="100" style="width: ${value}%">
            ${showLabel ? '<span class="label">' + Math.round(value) + '%</span>' : ''}
          </div>
        </div>
      `;
    }
  }

  CanvasUI.register('canvas-progress', CanvasProgress);

  /* ======== canvas-radio ======== */

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
            border: 1px solid rgba(34, 36, 38, 0.15);
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

  CanvasUI.register('canvas-radio', CanvasRadio);

  /* ======== canvas-scroll-area ======== */

  class CanvasScrollArea extends HTMLElement {
    static get observedAttributes() {
      return ['vertical', 'horizontal'];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          :host([vertical])   { overflow-y: auto; }
          :host([horizontal]) { overflow-x: auto; }
        </style>
        <slot></slot>
      `;
    }

    connectedCallback() {
      this._syncTabindex();
    }

    attributeChangedCallback() {
      this._syncTabindex();
    }

    _syncTabindex() {
      var hasDirection = this.hasAttribute('vertical') || this.hasAttribute('horizontal');
      if (hasDirection && !this.hasAttribute('tabindex')) {
        this.setAttribute('tabindex', '0');
      }
    }
  }

  CanvasUI.register('canvas-scroll-area', CanvasScrollArea);

  /* ======== canvas-sidebar-layout ======== */

  /* canvas-sidebar-layout: flex row container for sidebar + content split views */
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
  CanvasUI.register('canvas-sidebar-layout', CanvasSidebarLayout);

  /* canvas-sidebar: scrollable left panel with gray background */
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
  CanvasUI.register('canvas-sidebar', CanvasSidebar);

  /* canvas-content: flexible right panel with white background */
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
  CanvasUI.register('canvas-content', CanvasContent);

  /* ======== canvas-sortable-list ======== */

  /* Polite ARIA live region shared by every sortable list on the page.
     Announces reorder and cross list move outcomes to screen readers. */
  var CanvasSortableAnnouncer = {
    el: null,
    ensure: function () {
      if (this.el) return this.el;
      var el = document.createElement('div');
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      el.style.position = 'absolute';
      el.style.width = '1px';
      el.style.height = '1px';
      el.style.overflow = 'hidden';
      el.style.clip = 'rect(0 0 0 0)';
      el.style.margin = '-1px';
      el.style.padding = '0';
      document.body.appendChild(el);
      this.el = el;
      return el;
    },
    say: function (msg) {
      var el = this.ensure();
      el.textContent = '';
      window.setTimeout(function () { el.textContent = msg; }, 10);
    }
  };

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
      handle.addEventListener('keydown', function (e) {
        var list = self.closest('canvas-sortable-list');
        if (!list) return;

        if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
          e.preventDefault();
          self._keyboardReorder(list, e.key === 'ArrowUp' ? -1 : 1);
          handle.focus();
          return;
        }

        if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
          if (!list._getGroup || !list._getGroup()) return;
          e.preventDefault();
          self._keyboardMoveAcross(list, e.key === 'ArrowLeft' ? -1 : 1);
          handle.focus();
        }
      });
    }

    _keyboardReorder(list, direction) {
      var items = Array.prototype.slice.call(list.querySelectorAll('canvas-sortable-item'));
      var currentIndex = items.indexOf(this);
      var newIndex = currentIndex + direction;
      if (newIndex < 0 || newIndex >= items.length) return;

      if (direction < 0) {
        list.insertBefore(this, items[newIndex]);
      } else {
        list.insertBefore(this, items[newIndex].nextSibling);
      }

      var detail = { oldIndex: currentIndex, newIndex: newIndex, item: this, list: list };
      list.dispatchEvent(new CustomEvent('reorder', { bubbles: true, composed: true, detail: detail }));
      list.dispatchEvent(new CustomEvent('change', {
        bubbles: true, composed: true,
        detail: Object.assign({ type: 'reorder' }, detail)
      }));
      list._announceMove('reorder', detail);
    }

    _keyboardMoveAcross(list, direction) {
      var siblings = list._findSiblingLists();
      if (!siblings.length) return;

      var sourceLeft = list.getBoundingClientRect().left;
      siblings.sort(function (a, b) {
        return a.getBoundingClientRect().left - b.getBoundingClientRect().left;
      });

      var afterSource = siblings.filter(function (s) {
        return s.getBoundingClientRect().left > sourceLeft;
      });
      var beforeSource = siblings.filter(function (s) {
        return s.getBoundingClientRect().left < sourceLeft;
      }).reverse();

      var target = direction > 0 ? afterSource[0] : beforeSource[0];
      if (!target) return;

      var oldIndex = Array.prototype.slice.call(
        list.querySelectorAll('canvas-sortable-item')
      ).indexOf(this);

      target.appendChild(this);

      var targetItems = Array.prototype.slice.call(
        target.querySelectorAll('canvas-sortable-item')
      );
      var newIndex = targetItems.indexOf(this);

      var detail = {
        item: this,
        fromList: list,
        toList: target,
        oldIndex: oldIndex,
        newIndex: newIndex
      };

      target.dispatchEvent(new CustomEvent('move', {
        bubbles: true, composed: true, detail: detail
      }));
      target.dispatchEvent(new CustomEvent('change', {
        bubbles: true, composed: true,
        detail: Object.assign({ type: 'move' }, detail)
      }));
      target._announceMove('move', detail);

      /* Refocus the handle in the new host so arrow keys keep working. */
      var handle = this.shadowRoot && this.shadowRoot.querySelector('.handle');
      if (handle) handle.focus();
    }
  }

  CanvasUI.register('canvas-sortable-item', CanvasSortableItem);

  class CanvasSortableList extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
            position: relative;
            min-height: var(--canvas-sortable-min-height, 0);
          }

          /* Eligible drop target during a cross list drag. Matches the
             canvas-input focus border so the affordance reads as a form
             like receptive field. Uses outline not border, so no layout
             shift on any sibling when the drag starts. */
          :host([data-drop-eligible]) {
            outline: 1px solid var(--canvas-input-focus-border, #85b7d9);
            outline-offset: 0;
            border-radius: var(--canvas-input-radius, var(--radius, .28571429rem));
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
      this._offsetX = 0;
      this._itemHeight = 0;

      /* Cross list state. sourceList is where the drag started, hostList is
         where the placeholder currently lives. Equal for within list drags.
         eligibleLists carries every sibling that can receive from the source
         so the drop eligible outline can be applied at drag start and
         cleared together at drag end. */
      this._sourceList = null;
      this._hostList = null;
      this._eligibleLists = null;

      /* Auto scroll state. Populated while a drag is active. */
      this._scrollAncestor = null;
      this._lastClientY = 0;
      this._lastClientX = 0;
      this._autoScrollRAF = null;
      this._autoScrollSpeed = 0;

      this._onPointerDown = this._onPointerDown.bind(this);
      this._onPointerMove = this._onPointerMove.bind(this);
      this._onPointerUp = this._onPointerUp.bind(this);
      this._autoScrollTick = this._autoScrollTick.bind(this);
    }

    connectedCallback() {
      this.addEventListener('pointerdown', this._onPointerDown);
    }

    disconnectedCallback() {
      this.removeEventListener('pointerdown', this._onPointerDown);
      this._cleanup();
    }

    /* Public snapshot getter. Returns the live array of sortable items in
       document order for consumers that prefer snapshot over delta events. */
    get items() {
      return this._getItems();
    }

    _getItems() {
      return Array.prototype.slice.call(this.querySelectorAll('canvas-sortable-item:not([dragging])'));
    }

    /* ---- group / accept / pull / disabled readers ---- */

    _getGroup() {
      var g = this.getAttribute('group');
      return g ? g.trim() : null;
    }

    _getAccepts() {
      var attr = this.getAttribute('accept');
      if (attr) {
        return attr.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      }
      var g = this._getGroup();
      return g ? [g] : [];
    }

    _getPullMode() {
      return this.getAttribute('pull') === 'clone' ? 'clone' : 'move';
    }

    _isDisabled() {
      return this.hasAttribute('disabled');
    }

    _acceptsFrom(sourceList) {
      if (this._isDisabled()) return false;
      var sourceGroup = sourceList && sourceList._getGroup();
      if (!sourceGroup) return false;
      return this._getAccepts().indexOf(sourceGroup) !== -1;
    }

    _findSiblingLists() {
      var self = this;
      if (!this._getGroup()) return [];
      var all = document.querySelectorAll('canvas-sortable-list');
      var out = [];
      for (var i = 0; i < all.length; i++) {
        var other = all[i];
        if (other === self) continue;
        if (other._acceptsFrom(self)) out.push(other);
      }
      return out;
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
      if (this._isDisabled()) return;
      if (this._dragging) return;

      var handle = this._getHandleFromEvent(e);
      if (!handle) return;

      var item = this._getItemFromHandle(handle);
      if (!item) return;

      e.preventDefault();

      var items = this._getItems();
      this._dragSourceIndex = items.indexOf(item);
      this._dragItem = item;
      this._sourceList = this;
      this._hostList = this;

      var rect = item.getBoundingClientRect();
      this._itemHeight = rect.height;
      this._startY = e.clientY;
      this._offsetY = e.clientY - rect.top;
      this._offsetX = e.clientX - rect.left;

      /* Measure all item positions before we start moving things */
      this._itemRects = [];
      for (var i = 0; i < items.length; i++) {
        this._itemRects.push(items[i].getBoundingClientRect());
      }

      /* Create a placeholder that holds space and renders an insertion bar */
      this._placeholder = document.createElement('div');
      this._placeholder.className = 'canvas-sortable-placeholder';
      this._placeholder.style.height = rect.height + 'px';
      this._placeholder.style.transition = 'height 0.2s ease';
      item.parentNode.insertBefore(this._placeholder, item);

      /* Position the dragged item as fixed overlay */
      item.setAttribute('dragging', '');
      item.style.position = 'fixed';
      item.style.left = rect.left + 'px';
      item.style.top = rect.top + 'px';
      item.style.width = rect.width + 'px';
      item.style.transition = 'none';

      this._scrollAncestor = this._findScrollableAncestor();
      this._lastClientY = e.clientY;
      this._lastClientX = e.clientX;

      this._dragging = true;

      /* Mark every eligible sibling so the user sees where the item can
         land for the whole duration of the drag. Source list keeps the
         data-drop-active marker for consumer custom styling. */
      if (this._getGroup()) {
        this.setAttribute('data-drop-active', '');
        this._eligibleLists = this._findSiblingLists();
        for (var s = 0; s < this._eligibleLists.length; s++) {
          this._eligibleLists[s].setAttribute('data-drop-eligible', '');
        }
      }

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

      this._lastClientY = e.clientY;
      this._lastClientX = e.clientX;

      /* Route to a sibling list if the cursor has crossed into one. */
      var nextHost = this._resolveHost(e.clientX, e.clientY);
      if (nextHost !== this._hostList) {
        this._migrateTo(nextHost);
      }

      this._hostList._updatePlaceholder(e.clientY, this);
      this._evaluateAutoScroll(e.clientY);
    }

    /* Return a larger hit zone than the sortable list's own rect. Using the
       nearest wrapping canvas-card or the immediate parent expands detection
       to the full column the user visually perceives, so cross list drag
       works even when the destination list holds only one or zero items
       and its own rect is much shorter than the source list. */
    _getHitRect() {
      var card = this.closest('canvas-card');
      if (card) return card.getBoundingClientRect();
      var parent = this.parentElement;
      if (parent) return parent.getBoundingClientRect();
      return this.getBoundingClientRect();
    }

    /* Find which list the cursor is currently over, out of the source list
       and any sibling lists in the same group. Three passes so kanban
       layouts with different column heights still catch drops reliably.

       Pass 1. Strict containment in the list's own rect. Works for any
       drop that lands inside the actual list area.

       Pass 2. Column wide rect from _getHitRect. Catches drops in the
       card body padding or above an empty list's short rect.

       Pass 3. Column x range plus the union y range of every candidate's
       hit rect. Handles horizontal kanban rows where the tallest column
       defines the effective drop zone for all columns. Without this,
       dragging from a tall column into a short sibling column fails
       because the cursor y is below the short column's own bottom. */
    _resolveHost(clientX, clientY) {
      if (!this._getGroup()) return this;
      var candidates = [this].concat(this._findSiblingLists());

      for (var i = 0; i < candidates.length; i++) {
        var rect = candidates[i].getBoundingClientRect();
        if (clientX >= rect.left && clientX <= rect.right &&
            clientY >= rect.top && clientY <= rect.bottom) {
          return candidates[i];
        }
      }

      for (var j = 0; j < candidates.length; j++) {
        var hit = candidates[j]._getHitRect();
        if (clientX >= hit.left && clientX <= hit.right &&
            clientY >= hit.top && clientY <= hit.bottom) {
          return candidates[j];
        }
      }

      var rowTop = Infinity, rowBottom = -Infinity;
      for (var m = 0; m < candidates.length; m++) {
        var mh = candidates[m]._getHitRect();
        if (mh.top < rowTop) rowTop = mh.top;
        if (mh.bottom > rowBottom) rowBottom = mh.bottom;
      }

      if (clientY >= rowTop && clientY <= rowBottom) {
        for (var k = 0; k < candidates.length; k++) {
          var kh = candidates[k]._getHitRect();
          if (clientX >= kh.left && clientX <= kh.right) {
            return candidates[k];
          }
        }
      }

      return this._hostList || this;
    }

    /* Move the placeholder into a new host list and update the drop active
       highlight. The source list stays authoritative for pointer events. */
    _migrateTo(nextHost) {
      var prev = this._hostList;
      if (prev && prev !== nextHost) {
        prev.removeAttribute('data-drop-active');
      }
      if (this._placeholder && this._placeholder.parentNode !== nextHost) {
        nextHost.appendChild(this._placeholder);
      }
      nextHost.setAttribute('data-drop-active', '');
      this._hostList = nextHost;
      this._scrollAncestor = nextHost._findScrollableAncestor();
    }

    /* Optional driver arg keeps the auto scroll tick able to reach the real
       source list when it recomputes the placeholder while the pointer is
       stationary. */
    _updatePlaceholder(clientY, driver) {
      driver = driver || this;
      if (!driver._dragging || !driver._dragItem || !driver._placeholder) return;

      /* Move the dragged item to follow the cursor. Track x so the ghost
         follows horizontal drags across kanban columns. */
      var newTop = clientY - driver._offsetY;
      driver._dragItem.style.top = newTop + 'px';
      var newLeft = driver._lastClientX - driver._offsetX;
      driver._dragItem.style.left = newLeft + 'px';

      /* Find where the placeholder should be in this host based on cursor Y */
      var items = this._getItems();
      var targetIndex = -1;

      for (var i = 0; i < items.length; i++) {
        var rect = items[i].getBoundingClientRect();
        var midY = rect.top + rect.height / 2;
        if (clientY < midY) {
          targetIndex = i;
          break;
        }
      }

      /* If cursor is below all items, place at the end */
      if (targetIndex === -1) {
        targetIndex = items.length;
      }

      /* Figure out which item the placeholder is currently next to */
      var currentNext = driver._placeholder.nextElementSibling;
      var desiredNext = (targetIndex < items.length) ? items[targetIndex] : null;

      /* If placeholder is already in the right spot, nothing to do */
      if (driver._placeholder.parentNode === this && currentNext === desiredNext) return;

      /* FLIP animation. Record positions before DOM change. */
      var rects = {};
      for (var i = 0; i < items.length; i++) {
        rects[i] = items[i].getBoundingClientRect();
      }

      /* Move the placeholder in the DOM */
      if (desiredNext) {
        this.insertBefore(driver._placeholder, desiredNext);
      } else {
        this.appendChild(driver._placeholder);
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

    /* Walk up from the list to find the nearest element that actually scrolls.
       If no element qualifies, fall back to the document scroller so the page
       itself will scroll when the list is directly inside body. Traverses
       through shadow roots by jumping to host, so the list works when placed
       inside a consumer's shadow DOM. */
    _findScrollableAncestor() {
      var node = this.parentNode;
      while (node && node !== document) {
        if (node.nodeType === Node.ELEMENT_NODE) {
          var styles = window.getComputedStyle(node);
          var overflowY = styles.overflowY;
          if ((overflowY === 'auto' || overflowY === 'scroll') &&
              node.scrollHeight > node.clientHeight) {
            return node;
          }
          node = node.parentNode;
        } else if (node.host) {
          node = node.host;
        } else {
          node = node.parentNode;
        }
      }
      return document.scrollingElement || document.documentElement;
    }

    _isDocumentScroller(el) {
      return el === document.scrollingElement ||
             el === document.documentElement ||
             el === document.body;
    }

    _getScrollEdges(ancestor) {
      if (this._isDocumentScroller(ancestor)) {
        return { top: 0, bottom: window.innerHeight };
      }
      var rect = ancestor.getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom };
    }

    _getScrollTop(ancestor) {
      if (this._isDocumentScroller(ancestor)) {
        return window.scrollY || window.pageYOffset || 0;
      }
      return ancestor.scrollTop;
    }

    _getMaxScrollTop(ancestor) {
      if (this._isDocumentScroller(ancestor)) {
        var doc = document.documentElement;
        return Math.max(0, doc.scrollHeight - window.innerHeight);
      }
      return Math.max(0, ancestor.scrollHeight - ancestor.clientHeight);
    }

    _setScrollTop(ancestor, value) {
      if (this._isDocumentScroller(ancestor)) {
        window.scrollTo(window.scrollX || 0, value);
      } else {
        ancestor.scrollTop = value;
      }
    }

    /* Decide whether the cursor is inside a top or bottom hotspot and set
       a signed speed for the rAF tick. Positive speed scrolls down, negative
       scrolls up, zero stops. */
    _evaluateAutoScroll(clientY) {
      var ancestor = this._scrollAncestor;
      if (!ancestor) return;

      var edges = this._getScrollEdges(ancestor);
      var height = edges.bottom - edges.top;
      if (height <= 0) {
        this._autoScrollSpeed = 0;
        this._stopAutoScroll();
        return;
      }

      var HOTSPOT_PX = 48;
      var MAX_SPEED = 12;
      var hotspot = Math.min(HOTSPOT_PX, height / 3);

      var topDistance = (edges.top + hotspot) - clientY;
      var bottomDistance = clientY - (edges.bottom - hotspot);
      var speed = 0;

      if (topDistance > 0) {
        speed = -Math.min(topDistance / hotspot, 1) * MAX_SPEED;
      } else if (bottomDistance > 0) {
        speed = Math.min(bottomDistance / hotspot, 1) * MAX_SPEED;
      }

      this._autoScrollSpeed = speed;

      if (speed === 0) {
        this._stopAutoScroll();
      } else {
        this._startAutoScroll();
      }
    }

    _startAutoScroll() {
      if (this._autoScrollRAF !== null) return;
      this._autoScrollRAF = window.requestAnimationFrame(this._autoScrollTick);
    }

    _stopAutoScroll() {
      if (this._autoScrollRAF !== null) {
        window.cancelAnimationFrame(this._autoScrollRAF);
        this._autoScrollRAF = null;
      }
      this._autoScrollSpeed = 0;
    }

    _autoScrollTick() {
      this._autoScrollRAF = null;

      if (!this._dragging || !this._scrollAncestor) return;

      var speed = this._autoScrollSpeed;
      if (speed === 0) return;

      var ancestor = this._scrollAncestor;
      var current = this._getScrollTop(ancestor);
      var max = this._getMaxScrollTop(ancestor);
      var next = Math.max(0, Math.min(max, current + speed));

      if (next !== current) {
        this._setScrollTop(ancestor, next);
        /* Items just slid under a stationary cursor. Recompute placeholder
           and move the overlay so the ghost stays under the pointer. */
        this._hostList._updatePlaceholder(this._lastClientY, this);
      }

      /* Keep the loop alive. If the cursor later leaves the hotspot, the next
         pointermove will zero the speed and stopAutoScroll will cancel. */
      this._autoScrollRAF = window.requestAnimationFrame(this._autoScrollTick);
    }

    _onPointerUp(e) {
      if (!this._dragging || !this._dragItem) {
        this._cleanup();
        return;
      }

      var source = this._sourceList;
      var host = this._hostList;
      var item = this._dragItem;
      var placeholder = this._placeholder;
      var oldIndex = this._dragSourceIndex;
      var isCrossList = host !== source;
      var pullMode = source._getPullMode();

      /* Clone mode hands out copies of the item to other lists. The original
         stays in the source list, a fresh clone is committed into the host. */
      var commitItem = (isCrossList && pullMode === 'clone') ? item.cloneNode(true) : item;

      /* Where the placeholder currently sits in the host, measured by the
         sibling right after it. This is the intended new index. */
      var hostItems = Array.prototype.slice.call(
        host.querySelectorAll('canvas-sortable-item:not([dragging])')
      );
      var after = placeholder ? placeholder.nextElementSibling : null;
      var placeholderIndex = after ? hostItems.indexOf(after) : -1;
      var newIndex = placeholderIndex === -1 ? hostItems.length : placeholderIndex;

      var eventType = isCrossList ? 'move' : 'reorder';
      var detail = isCrossList
        ? { item: commitItem, fromList: source, toList: host, oldIndex: oldIndex, newIndex: newIndex }
        : { item: commitItem, oldIndex: oldIndex, newIndex: newIndex, list: host };

      /* Cancelable pre commit events. A handler can preventDefault to snap
         the item back to the source position with no success event fired. */
      var before = new CustomEvent('before' + eventType, {
        bubbles: true, composed: true, cancelable: true, detail: detail
      });
      host.dispatchEvent(before);

      var beforeChange = new CustomEvent('beforechange', {
        bubbles: true, composed: true, cancelable: true,
        detail: Object.assign({ type: eventType }, detail)
      });
      if (!before.defaultPrevented) host.dispatchEvent(beforeChange);

      if (before.defaultPrevented || beforeChange.defaultPrevented) {
        this._revertToSource();
        this._cleanup();
        return;
      }

      /* No op within list drag at the same index. Snap back, no event. */
      if (!isCrossList && oldIndex === newIndex) {
        this._revertToSource();
        this._cleanup();
        return;
      }

      /* Commit. Insert the committed item at the placeholder position. */
      host.insertBefore(commitItem, placeholder);
      if (placeholder && placeholder.parentNode) {
        placeholder.parentNode.removeChild(placeholder);
      }
      this._placeholder = null;

      commitItem.removeAttribute('dragging');
      commitItem.style.position = '';
      commitItem.style.left = '';
      commitItem.style.top = '';
      commitItem.style.width = '';
      commitItem.style.transition = '';
      commitItem.style.transform = '';

      /* Clone mode also resets styles on the original so it returns to its
         resting state in the source list. */
      if (isCrossList && pullMode === 'clone') {
        item.removeAttribute('dragging');
        item.style.position = '';
        item.style.left = '';
        item.style.top = '';
        item.style.width = '';
        item.style.transition = '';
        item.style.transform = '';
      }

      host.dispatchEvent(new CustomEvent(eventType, {
        bubbles: true, composed: true, detail: detail
      }));
      host.dispatchEvent(new CustomEvent('change', {
        bubbles: true, composed: true,
        detail: Object.assign({ type: eventType }, detail)
      }));
      host._announceMove(eventType, detail);

      this._cleanup();
    }

    /* Put the dragged item back at its original index in the source list
       without firing any success event. Used for cancel and no op paths. */
    _revertToSource() {
      var source = this._sourceList;
      var item = this._dragItem;
      var placeholder = this._placeholder;

      if (placeholder && placeholder.parentNode) {
        placeholder.parentNode.removeChild(placeholder);
      }
      this._placeholder = null;

      var siblings = Array.prototype.slice.call(
        source.querySelectorAll('canvas-sortable-item:not([dragging])')
      );
      var anchor = siblings[this._dragSourceIndex] || null;
      if (anchor) {
        source.insertBefore(item, anchor);
      } else {
        source.appendChild(item);
      }

      item.removeAttribute('dragging');
      item.style.position = '';
      item.style.left = '';
      item.style.top = '';
      item.style.width = '';
      item.style.transition = '';
      item.style.transform = '';
    }

    /* Resolve a human readable label for a list for ARIA announcements. */
    _labelFor(list) {
      var labelled = list.getAttribute('aria-labelledby');
      if (labelled) {
        var el = document.getElementById(labelled);
        if (el) return el.textContent.trim();
      }
      var label = list.getAttribute('aria-label');
      if (label) return label;
      if (list.id) return list.id;
      return 'list';
    }

    _announceMove(type, detail) {
      var host = detail.toList || detail.list || this;
      var size = Array.prototype.slice.call(
        host.querySelectorAll('canvas-sortable-item')
      ).length;
      var position = detail.newIndex + 1;
      if (type === 'move') {
        CanvasSortableAnnouncer.say(
          'Moved item from ' + this._labelFor(detail.fromList) +
          ' to ' + this._labelFor(detail.toList) +
          ', position ' + position + ' of ' + size + '.'
        );
      } else {
        CanvasSortableAnnouncer.say(
          'Moved item to position ' + position + ' of ' + size + ' in ' +
          this._labelFor(detail.list || this) + '.'
        );
      }
    }

    _cleanup() {
      this._stopAutoScroll();

      this.style.pointerEvents = '';
      if (this._cursorStyle && this._cursorStyle.parentNode) {
        this._cursorStyle.parentNode.removeChild(this._cursorStyle);
      }
      this._cursorStyle = null;

      /* Clear drop active on both source and current host lists. */
      if (this._hostList) this._hostList.removeAttribute('data-drop-active');
      if (this._sourceList && this._sourceList !== this._hostList) {
        this._sourceList.removeAttribute('data-drop-active');
      }

      /* Clear drop eligible on every sibling marked at drag start. */
      if (this._eligibleLists) {
        for (var e = 0; e < this._eligibleLists.length; e++) {
          this._eligibleLists[e].removeAttribute('data-drop-eligible');
        }
        this._eligibleLists = null;
      }

      /* Clean up inline transition styles on items in both source and host. */
      var lists = [];
      if (this._sourceList) lists.push(this._sourceList);
      if (this._hostList && this._hostList !== this._sourceList) lists.push(this._hostList);
      for (var j = 0; j < lists.length; j++) {
        var items = lists[j]._getItems();
        for (var i = 0; i < items.length; i++) {
          items[i].style.transition = '';
          items[i].style.transform = '';
        }
      }

      this._dragging = false;
      this._dragItem = null;
      this._dragSourceIndex = -1;
      this._itemRects = null;
      this._scrollAncestor = null;
      this._lastClientY = 0;
      this._sourceList = null;
      this._hostList = null;

      if (this._placeholder && this._placeholder.parentNode) {
        this._placeholder.parentNode.removeChild(this._placeholder);
      }
      this._placeholder = null;

      document.removeEventListener('pointermove', this._onPointerMove);
      document.removeEventListener('pointerup', this._onPointerUp);
    }
  }

  CanvasUI.register('canvas-sortable-list', CanvasSortableList);

  /* ======== canvas-table ======== */

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

  CanvasUI.register('canvas-table', CanvasTable);
  CanvasUI.register('canvas-table-head', CanvasTableHead);
  CanvasUI.register('canvas-table-body', CanvasTableBody);
  CanvasUI.register('canvas-table-row', CanvasTableRow);
  CanvasUI.register('canvas-table-cell', CanvasTableCell);

  /* ======== canvas-tabs ======== */

  /* canvas-tab-panel: simple content container, visibility managed by canvas-tabs */
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
  CanvasUI.register('canvas-tab-panel', CanvasTabPanel);

  /* canvas-tab-label: text label inside a canvas-tab. Truncates with ellipsis and sets title automatically. */
  class CanvasTabLabel extends HTMLElement {
    constructor() { super(); }
    connectedCallback() { this.style.display = 'none'; }
  }
  CanvasUI.register('canvas-tab-label', CanvasTabLabel);

  /* canvas-tab: a single tab button inside canvas-tabs. Rich content via slot. */
  class CanvasTab extends HTMLElement {
    constructor() { super(); }
    connectedCallback() {
      this.style.display = 'none';
      if (!this.querySelector('canvas-tab-label')) {
        console.warn('canvas-tab: missing <canvas-tab-label>. Wrap your tab text in <canvas-tab-label> for truncation and tooltip support.');
      }
    }
  }
  CanvasUI.register('canvas-tab', CanvasTab);

  /* canvas-tabs: tab bar container that manages active state, keyboard nav, and panel visibility */
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

  CanvasUI.register('canvas-tabs', CanvasTabs);

  /* ======== canvas-textarea ======== */

  class CanvasTextarea extends HTMLElement {
    static get observedAttributes() {
      return ['label', 'placeholder', 'rows', 'max-rows', 'required', 'error', 'disabled', 'value', 'name', 'maxlength', 'auto-resize', 'no-resize'];
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
            min-width: 0;
          }

          label {
            display: none;
            margin: 0 0 .28571429rem 0;
            font-size: var(--canvas-textarea-label-font-size, var(--canvas-input-label-font-size, .92857143em));
            font-weight: var(--canvas-textarea-label-font-weight, var(--font-weight-bold, 700));
            font-family: var(--canvas-textarea-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
            color: var(--canvas-textarea-label-color, var(--color-text, rgba(0, 0, 0, 0.87)));
            text-transform: none;
            line-height: 1em;
          }

          :host([label]) label { display: block; }

          .wrap {
            position: relative;
            min-width: 0;
          }

          .auto-wrap {
            display: grid;
            min-width: 0;
          }

          .auto-wrap::after {
            content: attr(data-value) " ";
            white-space: pre-wrap;
            word-wrap: break-word;
            visibility: hidden;
            padding: var(--canvas-textarea-padding, var(--canvas-input-padding, .67857143em 1em));
            font-size: var(--canvas-textarea-font-size, var(--canvas-input-font-size, 1em));
            font-family: var(--canvas-textarea-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
            line-height: var(--canvas-textarea-line-height, var(--canvas-input-line-height, 1.21428571em));
            border: var(--canvas-textarea-border, var(--canvas-input-border, 1px solid rgba(34, 36, 38, 0.15)));
            grid-area: 1 / 1 / 2 / 2;
          }

          .auto-wrap textarea {
            grid-area: 1 / 1 / 2 / 2;
            overflow: hidden;
          }

          .auto-wrap.has-max-rows {
            max-height: var(--_max-height);
            overflow: hidden;
          }

          .auto-wrap.has-max-rows textarea {
            overflow-y: auto;
          }

          textarea {
            width: 100%;
            padding: var(--canvas-textarea-padding, var(--canvas-input-padding, .67857143em 1em));
            font-size: var(--canvas-textarea-font-size, var(--canvas-input-font-size, 1em));
            font-family: var(--canvas-textarea-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
            line-height: var(--canvas-textarea-line-height, var(--canvas-input-line-height, 1.21428571em));
            color: var(--canvas-textarea-color, var(--color-text, rgba(0, 0, 0, 0.87)));
            background: var(--canvas-textarea-bg, var(--color-surface, #FFFFFF));
            border: var(--canvas-textarea-border, var(--canvas-input-border, 1px solid rgba(34, 36, 38, 0.15)));
            border-radius: var(--canvas-textarea-radius, var(--canvas-input-radius, var(--radius, .28571429rem)));
            transition: border-color 0.1s ease, box-shadow 0.1s ease;
            box-shadow: none;
            outline: 0;
            box-sizing: border-box;
            resize: vertical;
          }

          :host([no-resize]) textarea,
          :host([auto-resize]) textarea {
            resize: none;
          }

          textarea:focus {
            border-color: var(--canvas-textarea-focus-border, var(--canvas-input-focus-border, #85b7d9));
            background: var(--canvas-textarea-bg, var(--color-surface, #FFFFFF));
            color: rgba(0, 0, 0, 0.8);
            box-shadow: none;
            outline: none;
          }

          textarea::placeholder {
            color: var(--canvas-textarea-placeholder, var(--canvas-input-placeholder, rgba(191, 191, 191, 0.87)));
          }

          textarea:focus::placeholder {
            color: var(--canvas-textarea-focus-placeholder, var(--canvas-input-focus-placeholder, rgba(115, 115, 115, 0.87)));
          }

          textarea:disabled {
            background: var(--canvas-textarea-disabled-bg, var(--canvas-input-disabled-bg, var(--color-bg, #F5F5F5)));
            cursor: not-allowed;
          }

          /* Error state */
          .error-msg {
            display: none;
            font-size: .92857143em;
            color: var(--canvas-textarea-error-text, var(--canvas-input-error-text, #9f3a38));
            line-height: 1em;
            font-weight: var(--canvas-textarea-label-font-weight, var(--font-weight-bold, 700));
            font-family: var(--canvas-textarea-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
            margin-top: .28571429rem;
          }

          :host([error]) .error-msg { display: block; }

          :host([error]) label {
            color: var(--canvas-textarea-error-text, var(--canvas-input-error-text, #9f3a38));
          }

          :host([error]) textarea {
            background: var(--canvas-textarea-error-bg, var(--canvas-input-error-bg, #fff6f6));
            border-color: var(--canvas-textarea-error-border, var(--canvas-input-error-border, #e0b4b4));
            color: var(--canvas-textarea-error-text, var(--canvas-input-error-text, #9f3a38));
          }

          :host([error]) textarea::placeholder {
            color: var(--canvas-textarea-error-border, var(--canvas-input-error-border, #e0b4b4));
          }

          /* Counter */
          .counter {
            display: none;
            font-size: .85714286em;
            color: var(--canvas-textarea-counter-color, var(--color-text-muted, #767676));
            text-align: right;
            margin-top: .28571429rem;
            font-family: var(--canvas-textarea-font-family, var(--font-family, lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif));
          }

          :host([maxlength]) .counter { display: block; }

          .counter.at-limit {
            color: var(--canvas-textarea-error-text, var(--canvas-input-error-text, #9f3a38));
            font-weight: 700;
          }
        </style>
        <label part="label"></label>
        <div class="wrap">
          <textarea part="textarea" rows="4"></textarea>
        </div>
        <span class="counter" part="counter"></span>
        <span class="error-msg" part="error" aria-live="polite"></span>
      `;
      this._label = this.shadowRoot.querySelector('label');
      this._textarea = this.shadowRoot.querySelector('textarea');
      this._wrap = this.shadowRoot.querySelector('.wrap');
      this._counter = this.shadowRoot.querySelector('.counter');
      this._errorMsg = this.shadowRoot.querySelector('.error-msg');
      this._boundOnInput = this._onInput.bind(this);
      this._boundOnChange = this._onChange.bind(this);
    }

    connectedCallback() {
      this._textarea.addEventListener('input', this._boundOnInput);
      this._textarea.addEventListener('change', this._boundOnChange);
      this._syncAll();
    }

    disconnectedCallback() {
      this._textarea.removeEventListener('input', this._boundOnInput);
      this._textarea.removeEventListener('change', this._boundOnChange);
    }

    attributeChangedCallback(name, oldVal, newVal) {
      switch (name) {
        case 'label':
          this._label.textContent = newVal || '';
          break;
        case 'placeholder':
          this._textarea.placeholder = newVal || '';
          break;
        case 'rows':
          this._textarea.rows = newVal || 4;
          break;
        case 'required':
          var req = this.hasAttribute('required');
          this._textarea.required = req;
          this._textarea.setAttribute('aria-required', req);
          break;
        case 'disabled':
          var dis = this.hasAttribute('disabled');
          this._textarea.disabled = dis;
          break;
        case 'error':
          this._syncError();
          break;
        case 'value':
          if (newVal !== null) {
            this._textarea.value = newVal;
            this._internals.setFormValue(newVal);
            this._syncAutoResize();
            this._syncCounter();
          }
          break;
        case 'maxlength':
          if (newVal) {
            this._textarea.maxLength = parseInt(newVal, 10);
          } else {
            this._textarea.removeAttribute('maxlength');
          }
          this._syncCounter();
          break;
        case 'auto-resize':
          this._syncAutoResizeMode();
          break;
        case 'max-rows':
          this._syncMaxRows();
          break;
        case 'name':
          break;
        case 'no-resize':
          break;
      }
    }

    get value() {
      return this._textarea.value;
    }

    set value(v) {
      this._textarea.value = v;
      this._internals.setFormValue(v);
      this._syncAutoResize();
      this._syncCounter();
    }

    get name() {
      return this.getAttribute('name');
    }

    _syncAll() {
      this._label.textContent = this.getAttribute('label') || '';
      this._textarea.placeholder = this.getAttribute('placeholder') || '';
      this._textarea.rows = this.getAttribute('rows') || 4;

      var req = this.hasAttribute('required');
      this._textarea.required = req;
      this._textarea.setAttribute('aria-required', req);

      var dis = this.hasAttribute('disabled');
      this._textarea.disabled = dis;

      var maxlen = this.getAttribute('maxlength');
      if (maxlen) this._textarea.maxLength = parseInt(maxlen, 10);

      var val = this.getAttribute('value');
      if (val !== null) {
        this._textarea.value = val;
        this._internals.setFormValue(val);
      }

      this._syncError();
      this._syncAutoResizeMode();
      this._syncMaxRows();
      this._syncCounter();
    }

    _syncError() {
      var err = this.getAttribute('error');
      if (err) {
        this._errorMsg.textContent = err;
        this._textarea.setAttribute('aria-invalid', 'true');
        this._errorMsg.id = 'err';
        this._textarea.setAttribute('aria-describedby', 'err');
      } else {
        this._errorMsg.textContent = '';
        this._textarea.removeAttribute('aria-invalid');
        this._textarea.removeAttribute('aria-describedby');
      }
    }

    _syncAutoResizeMode() {
      if (this.hasAttribute('auto-resize')) {
        this._wrap.classList.add('auto-wrap');
        this._wrap.setAttribute('data-value', this._textarea.value);
      } else {
        this._wrap.classList.remove('auto-wrap');
        this._wrap.removeAttribute('data-value');
      }
    }

    _syncAutoResize() {
      if (this.hasAttribute('auto-resize')) {
        this._wrap.setAttribute('data-value', this._textarea.value);
      }
    }

    _syncMaxRows() {
      var maxRows = this.getAttribute('max-rows');
      if (maxRows && this.hasAttribute('auto-resize')) {
        this._wrap.classList.add('has-max-rows');
        requestAnimationFrame(() => {
          this._computeMaxHeight(parseInt(maxRows, 10));
        });
      } else {
        this._wrap.classList.remove('has-max-rows');
        this._wrap.style.removeProperty('--_max-height');
        this._textarea.style.removeProperty('max-height');
      }
    }

    _computeMaxHeight(maxRows) {
      var ta = this._textarea;
      var style = getComputedStyle(ta);
      var lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.2;
      var paddingTop = parseFloat(style.paddingTop) || 0;
      var paddingBottom = parseFloat(style.paddingBottom) || 0;
      var borderTop = parseFloat(style.borderTopWidth) || 0;
      var borderBottom = parseFloat(style.borderBottomWidth) || 0;
      var maxHeight = (lineHeight * maxRows) + paddingTop + paddingBottom + borderTop + borderBottom;
      this._wrap.style.setProperty('--_max-height', maxHeight + 'px');
      ta.style.maxHeight = maxHeight + 'px';
    }

    _syncCounter() {
      var maxlen = this.getAttribute('maxlength');
      if (maxlen) {
        var current = this._textarea.value.length;
        var max = parseInt(maxlen, 10);
        this._counter.textContent = current + ' / ' + max;
        if (current >= max) {
          this._counter.classList.add('at-limit');
        } else {
          this._counter.classList.remove('at-limit');
        }
      }
    }

    _onInput(e) {
      e.stopPropagation();
      this._internals.setFormValue(this._textarea.value);
      this._syncAutoResize();
      this._syncCounter();
      this.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    }

    _onChange(e) {
      e.stopPropagation();
      this._internals.setFormValue(this._textarea.value);
      this.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    }
  }

  CanvasUI.register('canvas-textarea', CanvasTextarea);

  /* ======== canvas-toggle ======== */

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

  CanvasUI.register('canvas-toggle', CanvasToggle);

  /* ======== canvas-tooltip ======== */

  class CanvasTooltip extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = '<style>:host { display: none; }</style>';
      this._tooltip = null;
      this._inner = null;
      this._arrow = null;
      this._currentTrigger = null;
      this._showTimeout = null;
      this._boundEnter = this._onEnter.bind(this);
      this._boundLeave = this._onLeave.bind(this);
      this._boundScroll = this._onScroll.bind(this);
      this._trackedElements = new Set();
    }

    connectedCallback() {
      this._createTooltip();
      this._bindAll();
      this._observer = new MutationObserver(() => this._bindAll());
      this._observer.observe(document.body, { childList: true, subtree: true });
      document.addEventListener('scroll', this._boundScroll, true);
    }

    disconnectedCallback() {
      if (this._observer) {
        this._observer.disconnect();
        this._observer = null;
      }
      document.removeEventListener('scroll', this._boundScroll, true);
      this._unbindAll();
      if (this._tooltip && this._tooltip.parentNode) {
        this._tooltip.parentNode.removeChild(this._tooltip);
      }
      this._tooltip = null;
    }

    _bindAll() {
      var elements = document.querySelectorAll('[data-canvas-tooltip]');
      elements.forEach(function(el) {
        if (!this._trackedElements.has(el)) {
          el.addEventListener('mouseenter', this._boundEnter);
          el.addEventListener('mouseleave', this._boundLeave);
          this._trackedElements.add(el);
        }
      }, this);
    }

    _unbindAll() {
      this._trackedElements.forEach(function(el) {
        el.removeEventListener('mouseenter', this._boundEnter);
        el.removeEventListener('mouseleave', this._boundLeave);
      }, this);
      this._trackedElements.clear();
    }

    _createTooltip() {
      if (this._tooltip) return;

      var style = document.createElement('style');
      style.textContent = `
        .canvas-tooltip-container {
          position: fixed;
          z-index: 1900;
          pointer-events: none;
          display: none;
          max-width: 250px;
          filter: drop-shadow(0 2px 4px rgba(34, 36, 38, 0.12)) drop-shadow(0 2px 10px rgba(34, 36, 38, 0.15));
        }

        .canvas-tooltip-container.visible {
          display: block;
        }

        .canvas-tooltip-inner {
          position: relative;
          z-index: 1;
          background: #fff;
          border: 1px solid #d4d4d5;
          border-radius: .28571429rem;
          padding: .833em 1em;
          font-family: lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
          font-size: 1rem;
          font-weight: 400;
          line-height: 1.4285em;
          color: rgba(0, 0, 0, 0.87);
          word-wrap: break-word;
        }

        .canvas-tooltip-container.inverted {
          filter: none;
        }

        .canvas-tooltip-container.inverted .canvas-tooltip-inner {
          background: #1b1c1d;
          color: #fff;
          border: none;
        }

        .canvas-tooltip-arrow {
          position: absolute;
          z-index: 0;
          line-height: 0;
        }

        .canvas-tooltip-arrow svg {
          display: block;
          fill: #d4d4d5;
          stroke: none;
        }

        .canvas-tooltip-arrow-cover {
          position: absolute;
          z-index: 2;
          line-height: 0;
        }

        .canvas-tooltip-arrow-cover svg {
          display: block;
          fill: #fff;
          stroke: none;
        }

        .canvas-tooltip-container.inverted .canvas-tooltip-arrow svg {
          fill: #1b1c1d;
        }

        .canvas-tooltip-container.inverted .canvas-tooltip-arrow-cover svg {
          fill: #1b1c1d;
        }

        .canvas-tooltip-container.pos-top .canvas-tooltip-arrow {
          bottom: -5px;
          left: 50%;
          margin-left: -7px;
        }
        .canvas-tooltip-container.pos-top .canvas-tooltip-arrow-cover {
          bottom: -4px;
          left: 50%;
          margin-left: -7px;
        }

        .canvas-tooltip-container.pos-bottom .canvas-tooltip-arrow {
          top: -5px;
          left: 50%;
          margin-left: -7px;
        }
        .canvas-tooltip-container.pos-bottom .canvas-tooltip-arrow-cover {
          top: -4px;
          left: 50%;
          margin-left: -7px;
        }

        .canvas-tooltip-container.pos-left .canvas-tooltip-arrow {
          right: -5px;
          top: 50%;
          margin-top: -7px;
        }
        .canvas-tooltip-container.pos-left .canvas-tooltip-arrow-cover {
          right: -4px;
          top: 50%;
          margin-top: -7px;
        }

        .canvas-tooltip-container.pos-right .canvas-tooltip-arrow {
          left: -5px;
          top: 50%;
          margin-top: -7px;
        }
        .canvas-tooltip-container.pos-right .canvas-tooltip-arrow-cover {
          left: -4px;
          top: 50%;
          margin-top: -7px;
        }
      `;

      var container = document.createElement('div');
      container.className = 'canvas-tooltip-container';
      container.setAttribute('role', 'tooltip');
      container.setAttribute('aria-hidden', 'true');

      var inner = document.createElement('div');
      inner.className = 'canvas-tooltip-inner';

      var arrow = document.createElement('div');
      arrow.className = 'canvas-tooltip-arrow';

      var arrowCover = document.createElement('div');
      arrowCover.className = 'canvas-tooltip-arrow-cover';

      container.appendChild(arrow);
      container.appendChild(inner);
      container.appendChild(arrowCover);

      document.head.appendChild(style);
      document.body.appendChild(container);
      this._tooltip = container;
      this._inner = inner;
      this._arrow = arrow;
      this._arrowCover = arrowCover;
    }

    _onEnter(e) {
      var trigger = e.currentTarget;
      var text = trigger.getAttribute('data-canvas-tooltip');
      if (!text) return;

      this._clearPending();
      this._currentTrigger = trigger;

      var delay = parseInt(trigger.getAttribute('data-canvas-tooltip-delay') || '0', 10);
      if (delay > 0) {
        this._showTimeout = setTimeout(() => {
          if (this._currentTrigger === trigger) this._show(trigger);
        }, delay);
      } else {
        this._show(trigger);
      }
    }

    _onLeave(e) {
      this._clearPending();
      this._currentTrigger = null;
      this._hide();
    }

    _onScroll() {
      if (this._currentTrigger) {
        this._clearPending();
        this._currentTrigger = null;
        this._hide();
      }
    }

    _clearPending() {
      if (this._showTimeout) {
        clearTimeout(this._showTimeout);
        this._showTimeout = null;
      }
    }

    _show(trigger) {
      if (!this._tooltip) return;

      var text = trigger.getAttribute('data-canvas-tooltip');
      if (!text) return;

      var position = trigger.getAttribute('data-canvas-tooltip-position') || 'top';
      var inverted = trigger.hasAttribute('data-canvas-tooltip-inverted');

      this._inner.textContent = text;
      this._setArrow(position);
      this._tooltip.className = 'canvas-tooltip-container' +
        (inverted ? ' inverted' : '') +
        ' pos-' + position;

      this._tooltip.setAttribute('aria-hidden', 'false');
      this._tooltip.style.left = '-9999px';
      this._tooltip.style.top = '-9999px';
      this._tooltip.classList.add('visible');

      requestAnimationFrame(() => {
        var triggerRect = trigger.getBoundingClientRect();
        var tipRect = this._tooltip.getBoundingClientRect();
        var coords = this._calcPosition(position, triggerRect, tipRect);

        if (coords.flipped) {
          this._setArrow(coords.position);
          this._tooltip.className = 'canvas-tooltip-container visible' +
            (inverted ? ' inverted' : '') +
            ' pos-' + coords.position;
        }

        this._tooltip.style.left = coords.left + 'px';
        this._tooltip.style.top = coords.top + 'px';
        this._applyArrowOffset(coords);
      });
    }

    _setArrow(position) {
      var svgs = {
        top: '<svg width="14" height="7" viewBox="0 0 14 7"><path d="M0 0 L7 7 L14 0" vector-effect="non-scaling-stroke"/></svg>',
        bottom: '<svg width="14" height="7" viewBox="0 0 14 7"><path d="M0 7 L7 0 L14 7" vector-effect="non-scaling-stroke"/></svg>',
        left: '<svg width="7" height="14" viewBox="0 0 7 14"><path d="M0 0 L7 7 L0 14" vector-effect="non-scaling-stroke"/></svg>',
        right: '<svg width="7" height="14" viewBox="0 0 7 14"><path d="M7 0 L0 7 L7 14" vector-effect="non-scaling-stroke"/></svg>'
      };
      this._arrow.innerHTML = svgs[position] || svgs.top;
      this._arrowCover.innerHTML = svgs[position] || svgs.top;
    }

    _applyArrowOffset(coords) {
      // Clear prior inline positioning so the CSS defaults do not mix with a
      // new decoupled offset when orientation changes across successive shows.
      this._arrow.style.left = '';
      this._arrow.style.top = '';
      this._arrow.style.marginLeft = '';
      this._arrow.style.marginTop = '';
      this._arrowCover.style.left = '';
      this._arrowCover.style.top = '';
      this._arrowCover.style.marginLeft = '';
      this._arrowCover.style.marginTop = '';

      if (coords.arrowX != null) {
        this._arrow.style.left = coords.arrowX + 'px';
        this._arrow.style.marginLeft = '0';
        this._arrowCover.style.left = coords.arrowX + 'px';
        this._arrowCover.style.marginLeft = '0';
      } else if (coords.arrowY != null) {
        this._arrow.style.top = coords.arrowY + 'px';
        this._arrow.style.marginTop = '0';
        this._arrowCover.style.top = coords.arrowY + 'px';
        this._arrowCover.style.marginTop = '0';
      }
    }

    _hide() {
      if (!this._tooltip) return;
      this._tooltip.classList.remove('visible');
      this._tooltip.setAttribute('aria-hidden', 'true');
    }

    _calcPosition(position, triggerRect, tipRect) {
      var gap = ANCHOR_GAP;
      var edge = ANCHOR_EDGE;
      var arrowHalf = ANCHOR_ARROW_HALF;
      var arrowInset = ANCHOR_ARROW_CORNER_INSET;
      var left, top;
      var flipped = false;

      switch (position) {
        case 'top':
          left = triggerRect.left + (triggerRect.width - tipRect.width) / 2;
          top = triggerRect.top - tipRect.height - gap;
          if (top < 0) { top = triggerRect.bottom + gap; position = 'bottom'; flipped = true; }
          break;
        case 'bottom':
          left = triggerRect.left + (triggerRect.width - tipRect.width) / 2;
          top = triggerRect.bottom + gap;
          if (top + tipRect.height > window.innerHeight) { top = triggerRect.top - tipRect.height - gap; position = 'top'; flipped = true; }
          break;
        case 'left':
          left = triggerRect.left - tipRect.width - gap;
          top = triggerRect.top + (triggerRect.height - tipRect.height) / 2;
          if (left < 0) { left = triggerRect.right + gap; position = 'right'; flipped = true; }
          break;
        case 'right':
          left = triggerRect.right + gap;
          top = triggerRect.top + (triggerRect.height - tipRect.height) / 2;
          if (left + tipRect.width > window.innerWidth) { left = triggerRect.left - tipRect.width - gap; position = 'left'; flipped = true; }
          break;
      }

      // Clamp tooltip box to viewport with an edge margin on all sides.
      // Apply the far-edge clamp first, then the near-edge clamp, so that
      // when the tooltip is wider or taller than the viewport allows, the
      // box stays flush against the near edge instead of going negative.
      if (left + tipRect.width > window.innerWidth - edge) {
        left = window.innerWidth - tipRect.width - edge;
      }
      if (left < edge) left = edge;
      if (top + tipRect.height > window.innerHeight - edge) {
        top = window.innerHeight - tipRect.height - edge;
      }
      if (top < edge) top = edge;

      // Compute arrow offset so the tip of the arrow sits over the trigger's
      // center, independent of where the clamped tooltip box ended up.
      // Clamp the arrow inside the box so it never slides into the rounded
      // corner. Horizontal arrow for top/bottom tooltips, vertical for left/right.
      var arrowX = null;
      var arrowY = null;
      if (position === 'top' || position === 'bottom') {
        var triggerCenterX = triggerRect.left + triggerRect.width / 2;
        var idealX = triggerCenterX - left - arrowHalf;
        var minX = arrowInset;
        var maxX = tipRect.width - arrowInset - arrowHalf * 2;
        if (maxX < minX) maxX = minX;
        if (idealX < minX) idealX = minX;
        if (idealX > maxX) idealX = maxX;
        arrowX = idealX;
      } else {
        var triggerCenterY = triggerRect.top + triggerRect.height / 2;
        var idealY = triggerCenterY - top - arrowHalf;
        var minY = arrowInset;
        var maxY = tipRect.height - arrowInset - arrowHalf * 2;
        if (maxY < minY) maxY = minY;
        if (idealY < minY) idealY = minY;
        if (idealY > maxY) idealY = maxY;
        arrowY = idealY;
      }

      return {
        left: left,
        top: top,
        position: position,
        flipped: flipped,
        arrowX: arrowX,
        arrowY: arrowY
      };
    }
  }

  CanvasUI.register('canvas-tooltip', CanvasTooltip);

})();
