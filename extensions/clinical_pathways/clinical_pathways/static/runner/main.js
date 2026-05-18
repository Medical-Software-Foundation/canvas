(function () {
  'use strict';

  const apiBase = document.body.dataset.apiBase;
  const params = new URLSearchParams(window.location.search);
  const noteUuid = params.get('note_uuid') || '';

  const els = {
    searchView: document.getElementById('search-view'),
    runView: document.getElementById('run-view'),
    completeView: document.getElementById('complete-view'),
    searchInput: document.getElementById('search-input'),
    results: document.getElementById('results'),
    pathwayName: document.getElementById('pathway-name'),
    segmentView: document.getElementById('segment-view'),
    nextBtn: document.getElementById('next-btn'),
    recommendationText: document.getElementById('recommendation-text'),
    commitBtn: document.getElementById('commit-btn'),
    commitStatus: document.getElementById('commit-status'),
    restartBtn: document.getElementById('restart-btn'),
  };

  let state = {
    pathway: null,
    currentSegment: null,
    trail: [],
    recommendation: '',
  };

  async function api(path, options = {}) {
    const opts = Object.assign({ headers: { 'Content-Type': 'application/json' } }, options);
    if (opts.body && typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
    const res = await fetch(apiBase + path, opts);
    if (!res.ok) throw new Error((await res.text()) || res.statusText);
    return res.status === 204 ? null : res.json();
  }

  // ---------- Search ----------

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), ms);
    };
  }

  async function runSearch(q) {
    const { pathways } = await api('/pathways?q=' + encodeURIComponent(q));
    els.results.innerHTML = '';
    if (!pathways.length) {
      const empty = document.createElement('li');
      empty.className = 'empty';
      empty.textContent = q ? 'No pathways match that title.' : 'No pathways found.';
      els.results.appendChild(empty);
      return;
    }
    pathways.forEach((pw) => {
      const li = document.createElement('li');
      li.textContent = pw.title + (pw.description ? ' — ' + pw.description : '');
      li.addEventListener('click', () => startPathway(pw.dbid));
      els.results.appendChild(li);
    });
  }

  els.searchInput.addEventListener('input', debounce((ev) => runSearch(ev.target.value), 250));

  // ---------- Run ----------

  async function startPathway(pathwayDbid) {
    const data = await api('/pathways/' + pathwayDbid + '/entry');
    state.pathway = data.pathway || null;
    state.recommendation =
      (data.pathway && data.pathway.recommendation) || data.recommendation || '';
    state.trail = [];
    els.searchView.classList.add('hidden');
    els.restartBtn.classList.remove('hidden');
    if (data.done) {
      els.runView.classList.add('hidden');
      finishRun(state.recommendation);
      return;
    }
    state.currentSegment = data.segment;
    els.runView.classList.remove('hidden');
    els.pathwayName.textContent = state.pathway.title;
    renderSegment();
  }

  function renderSegment() {
    const seg = state.currentSegment;
    els.segmentView.innerHTML = '';
    const title = document.createElement('div');
    title.className = 'segment-title';
    title.textContent = seg.title;
    els.segmentView.appendChild(title);

    seg.questions.forEach((q) => {
      const tpl = document.getElementById('question-template').content.cloneNode(true);
      const root = tpl.querySelector('.question');
      root.dataset.questionDbid = q.dbid;
      root.querySelector('.question-text').textContent =
        q.text + (q.required ? ' *' : '');
      const wrap = root.querySelector('.input-wrap');
      wrap.appendChild(buildInput(q));
      els.segmentView.appendChild(tpl);
    });
  }

  function buildInput(q) {
    if (q.response_type === 'yes_no' || q.response_type === 'multi') {
      const container = document.createElement('div');
      q.options.forEach((opt, i) => {
        const id = 'q' + q.dbid + '_o' + opt.dbid;
        const label = document.createElement('label');
        const input = document.createElement('input');
        input.type = 'radio';
        input.name = 'q' + q.dbid;
        input.id = id;
        input.value = opt.label;
        if (i === 0) input.dataset.first = '1';
        label.appendChild(input);
        label.appendChild(document.createTextNode(opt.label));
        container.appendChild(label);
      });
      return container;
    }
    if (q.response_type === 'numeric') {
      const inp = document.createElement('input');
      inp.type = 'number';
      inp.dataset.qInput = '1';
      return inp;
    }
    const ta = document.createElement('textarea');
    ta.dataset.qInput = '1';
    return ta;
  }

  function collectResponses() {
    const responses = [];
    els.segmentView.querySelectorAll('.question').forEach((qEl) => {
      const qid = Number(qEl.dataset.questionDbid);
      const radios = qEl.querySelectorAll('input[type=radio]');
      let answer = '';
      if (radios.length) {
        radios.forEach((r) => {
          if (r.checked) answer = r.value;
        });
      } else {
        const input = qEl.querySelector('[data-q-input]');
        if (input) answer = input.value;
      }
      const qText = qEl.querySelector('.question-text').textContent.replace(/ \*$/, '');
      responses.push({
        question_dbid: qid,
        question_text: qText,
        answer: answer,
      });
    });
    return responses;
  }

  els.nextBtn.addEventListener('click', async () => {
    const segId = state.currentSegment.dbid;
    const segTitle = state.currentSegment.title;
    const responses = collectResponses();
    responses.forEach((r) =>
      state.trail.push({
        segment_dbid: segId,
        segment_title: segTitle,
        question_dbid: r.question_dbid,
        question_text: r.question_text,
        answer: r.answer,
      }),
    );
    const result = await api('/segments/' + segId + '/next', {
      method: 'POST',
      body: { responses: responses.map((r) => ({ question_dbid: r.question_dbid, answer: r.answer })) },
    });
    if (result.done) {
      finishRun(result.recommendation || state.recommendation);
    } else {
      state.currentSegment = result.segment;
      renderSegment();
    }
  });

  function finishRun(recText) {
    state.recommendation = recText || '';
    els.runView.classList.add('hidden');
    els.completeView.classList.remove('hidden');
    els.recommendationText.textContent = state.recommendation || '(No recommendation configured.)';
  }

  // ---------- Commit ----------

  els.commitBtn.addEventListener('click', async () => {
    els.commitStatus.textContent = '';
    els.commitStatus.className = 'status';
    if (!noteUuid) {
      els.commitStatus.className = 'status err';
      els.commitStatus.textContent = 'Cannot commit: no note context (open from a note).';
      return;
    }
    if (!state.pathway || !state.pathway.dbid) {
      els.commitStatus.className = 'status err';
      els.commitStatus.textContent = 'Cannot commit: no pathway loaded.';
      return;
    }
    try {
      await api('/complete', {
        method: 'POST',
        body: {
          pathway_dbid: state.pathway.dbid,
          note_uuid: noteUuid,
          responses_trail: state.trail,
          recommendation: state.recommendation,
        },
      });
      els.commitStatus.className = 'status ok';
      els.commitStatus.innerHTML =
        '✓ Inserted into the note. <br/>' +
        'Close this panel to view the new commands on the chart.';
      els.commitBtn.disabled = true;
    } catch (err) {
      els.commitStatus.className = 'status err';
      els.commitStatus.textContent = 'Commit failed: ' + (err.message || err);
    }
  });

  // ---------- Restart ----------

  els.restartBtn.addEventListener('click', () => {
    state = { pathway: null, currentSegment: null, trail: [], recommendation: '' };
    els.commitBtn.disabled = false;
    els.commitStatus.textContent = '';
    els.completeView.classList.add('hidden');
    els.runView.classList.add('hidden');
    els.restartBtn.classList.add('hidden');
    els.searchView.classList.remove('hidden');
    els.searchInput.value = '';
    els.results.innerHTML = '';
    els.searchInput.focus();
  });

  // ---------- Boot ----------

  runSearch('');
})();
