(function () {
  'use strict';

  const apiBase = document.body.dataset.apiBase;
  const params = new URLSearchParams(window.location.search);
  const noteUuid = params.get('note_uuid') || '';

  const els = {
    input: document.getElementById('search-input'),
    results: document.getElementById('results'),
    status: document.getElementById('status'),
  };

  // ---------- Modal close handshake (INIT_CHANNEL / CLOSE_MODAL) ----------

  let messagePort = null;
  window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'INIT_CHANNEL' && event.ports && event.ports[0]) {
      messagePort = event.ports[0];
      messagePort.start();
    }
  });
  function closeModal() {
    if (messagePort) {
      try {
        messagePort.postMessage({ type: 'CLOSE_MODAL' });
        return;
      } catch (_) {
        /* fall through */
      }
    }
    try {
      window.close();
    } catch (_) {
      /* nothing more to do */
    }
  }

  // ---------- HTTP ----------

  async function api(path, options = {}) {
    const opts = Object.assign({ headers: { 'Content-Type': 'application/json' } }, options);
    if (opts.body && typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
    const res = await fetch(apiBase + path, opts);
    if (!res.ok) throw new Error((await res.text()) || res.statusText);
    return res.status === 204 ? null : res.json();
  }

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), ms);
    };
  }

  // ---------- Render ----------

  function setStatus(text, kind) {
    els.status.textContent = text;
    els.status.className = 'status' + (kind ? ' ' + kind : '');
  }

  function renderResults(pathways) {
    els.results.innerHTML = '';
    if (!pathways.length) {
      const li = document.createElement('li');
      li.className = 'empty';
      li.textContent = els.input.value
        ? 'No published pathways match that title.'
        : 'No published pathways yet. Use the Pathway Builder to create one.';
      els.results.appendChild(li);
      return;
    }
    pathways.forEach((pw) => {
      const li = document.createElement('li');
      const title = document.createElement('div');
      title.className = 'title';
      title.textContent = pw.title;
      li.appendChild(title);
      if (pw.description) {
        const desc = document.createElement('div');
        desc.className = 'desc';
        desc.textContent = pw.description;
        li.appendChild(desc);
      }
      li.addEventListener('click', () => startPathway(pw, li));
      els.results.appendChild(li);
    });
  }

  async function runSearch(q) {
    try {
      const { pathways } = await api('/pathways?q=' + encodeURIComponent(q));
      renderResults(pathways);
    } catch (err) {
      setStatus('Search failed: ' + (err.message || err), 'err');
    }
  }

  async function startPathway(pw, li) {
    if (!noteUuid) {
      setStatus('Cannot start: no note context (open this from a note).', 'err');
      return;
    }
    li.classList.add('busy');
    setStatus('Starting "' + pw.title + '"…', 'ok');
    try {
      await api('/start', {
        method: 'POST',
        body: { pathway_dbid: pw.dbid, note_uuid: noteUuid },
      });
      setStatus('Inserted into the note. Closing…', 'ok');
      setTimeout(closeModal, 400);
    } catch (err) {
      li.classList.remove('busy');
      setStatus('Could not start pathway: ' + (err.message || err), 'err');
    }
  }

  els.input.addEventListener('input', debounce((ev) => runSearch(ev.target.value), 200));

  // ---------- Boot ----------

  runSearch('');
})();
