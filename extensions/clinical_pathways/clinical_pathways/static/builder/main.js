(function () {
  'use strict';

  const apiBase = document.body.dataset.apiBase;
  const els = {
    list: document.getElementById('pathway-list-items'),
    newBtn: document.getElementById('new-pathway-btn'),
    empty: document.getElementById('empty-state'),
    form: document.getElementById('pathway-form'),
    dbid: document.getElementById('pathway-dbid'),
    title: document.getElementById('pathway-title'),
    description: document.getElementById('pathway-description'),
    recommendation: document.getElementById('pathway-recommendation'),
    deleteBtn: document.getElementById('delete-pathway-btn'),
    segmentsContainer: document.getElementById('segments-container'),
    addSegmentBtn: document.getElementById('add-segment-btn'),
    saveStatus: document.getElementById('save-status'),
  };

  let state = { pathway: null };
  let _statusTimer = null;

  function flashStatus(text, kind) {
    if (!els.saveStatus) return;
    els.saveStatus.textContent = text;
    els.saveStatus.className = 'save-status ' + (kind || 'ok');
    if (_statusTimer) clearTimeout(_statusTimer);
    _statusTimer = setTimeout(() => {
      els.saveStatus.textContent = '';
      els.saveStatus.className = 'save-status';
    }, kind === 'err' ? 5000 : 2000);
  }

  // ---------- HTTP helpers ----------

  async function api(path, options = {}) {
    const opts = Object.assign({ headers: { 'Content-Type': 'application/json' } }, options);
    if (opts.body && typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
    const res = await fetch(apiBase + path, opts);
    if (!res.ok) {
      const text = await res.text();
      flashStatus('Save failed: ' + (text || res.statusText), 'err');
      throw new Error(text || res.statusText);
    }
    return res.status === 204 ? null : res.json();
  }

  // ---------- Pathway list ----------

  async function loadPathwayList() {
    const { pathways } = await api('/pathways');
    els.list.innerHTML = '';
    pathways.forEach((pw) => {
      const li = document.createElement('li');
      li.textContent = pw.title;
      li.dataset.dbid = pw.dbid;
      if (state.pathway && state.pathway.dbid === pw.dbid) li.classList.add('active');
      li.addEventListener('click', () => loadPathway(pw.dbid));
      els.list.appendChild(li);
    });
  }

  async function loadPathway(dbid) {
    const pw = await api('/pathways/' + dbid);
    state.pathway = pw;
    renderPathwayForm();
    await loadPathwayList();
  }

  async function newPathway() {
    // Auto-create a pathway server-side so the segments section is immediately
    // usable. The user can then rename / fill in details on top of the default.
    const pw = await api('/pathways', {
      method: 'POST',
      body: { title: 'New Pathway', description: '', recommendation: '' },
    });
    state.pathway = pw;
    await loadPathwayList();
    renderPathwayForm();
    flashStatus('New pathway created');
    els.title.focus();
    els.title.select();
  }

  function renderPathwayForm() {
    const pw = state.pathway;
    if (!pw) {
      els.empty.classList.remove('hidden');
      els.form.classList.add('hidden');
      return;
    }
    els.empty.classList.add('hidden');
    els.form.classList.remove('hidden');
    els.dbid.value = pw.dbid || '';
    els.title.value = pw.title || '';
    els.description.value = pw.description || '';
    els.recommendation.value = pw.recommendation || '';
    els.deleteBtn.classList.toggle('hidden', !pw.dbid);
    renderSegments();
  }

  // ---------- Form save (pathway top-level) ----------

  async function savePathwayFields() {
    if (!state.pathway || !state.pathway.dbid) return;
    const body = {
      title: els.title.value,
      description: els.description.value,
      recommendation: els.recommendation.value,
    };
    const pw = await api('/pathways/' + state.pathway.dbid, { method: 'PATCH', body });
    state.pathway = pw;
    await loadPathwayList();
    flashStatus('Saved');
  }

  els.form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    await savePathwayFields();
  });

  // Auto-save top-level fields on blur so the user doesn't need to remember
  // to click "Save pathway" before adding segments.
  els.title.addEventListener('blur', savePathwayFields);
  els.description.addEventListener('blur', savePathwayFields);
  els.recommendation.addEventListener('blur', savePathwayFields);

  els.newBtn.addEventListener('click', newPathway);

  els.deleteBtn.addEventListener('click', async () => {
    if (!state.pathway || !state.pathway.dbid) return;
    if (!confirm('Delete this pathway? (It will be marked inactive.)')) return;
    await api('/pathways/' + state.pathway.dbid, { method: 'DELETE' });
    state.pathway = null;
    await loadPathwayList();
    renderPathwayForm();
    flashStatus('Pathway deleted');
  });

  // ---------- Segments / questions / options ----------

  async function refreshPathway() {
    state.pathway = await api('/pathways/' + state.pathway.dbid);
    renderSegments();
  }

  function renderSegments() {
    els.segmentsContainer.innerHTML = '';
    if (!state.pathway || !state.pathway.dbid) {
      els.addSegmentBtn.classList.add('hidden');
      return;
    }
    els.addSegmentBtn.classList.remove('hidden');
    (state.pathway.segments || []).forEach((seg) => {
      els.segmentsContainer.appendChild(renderSegmentEl(seg));
    });
  }

  function renderSegmentEl(seg) {
    const tpl = document.getElementById('segment-template').content.cloneNode(true);
    const root = tpl.querySelector('.segment');
    root.dataset.segmentDbid = seg.dbid;
    root.querySelector('.segment-title').value = seg.title || '';
    const entryInput = root.querySelector('.is-entry');
    entryInput.checked = !!seg.is_entry;
    entryInput.addEventListener('change', async () => {
      await api('/segments/' + seg.dbid, { method: 'PATCH', body: { is_entry: true } });
      await refreshPathway();
    });
    root.querySelector('.segment-title').addEventListener('blur', async (ev) => {
      await api('/segments/' + seg.dbid, { method: 'PATCH', body: { title: ev.target.value } });
    });
    root.querySelector('.delete-segment').addEventListener('click', async () => {
      if (!confirm('Delete this segment and its questions?')) return;
      await api('/segments/' + seg.dbid, { method: 'DELETE' });
      await refreshPathway();
    });

    const qList = root.querySelector('.questions');
    (seg.questions || []).forEach((q) => qList.appendChild(renderQuestionEl(q)));

    root.querySelector('.add-question').addEventListener('click', async () => {
      await api('/segments/' + seg.dbid + '/questions', {
        method: 'POST',
        body: { text: '', response_type: 'free_text' },
      });
      await refreshPathway();
    });

    const branchList = root.querySelector('.branch-list');
    (seg.branches || []).forEach((b) => branchList.appendChild(renderBranchEl(seg, b)));
    root.querySelector('.add-branch').addEventListener('click', async () => {
      const otherSegments = (state.pathway.segments || []).filter((s) => s.dbid !== seg.dbid);
      if (!otherSegments.length) {
        alert('Add another segment before creating a branch rule.');
        return;
      }
      const rule = await api('/segments/' + seg.dbid + '/branches', {
        method: 'POST',
        body: {
          to_segment_dbid: otherSegments[0].dbid,
          conditions: [],
          priority: (seg.branches || []).length,
          label: '',
        },
      });
      await refreshPathway();
    });

    return tpl;
  }

  function renderQuestionEl(q) {
    const tpl = document.getElementById('question-template').content.cloneNode(true);
    const root = tpl.querySelector('.question');
    root.dataset.questionDbid = q.dbid;
    root.querySelector('.q-text').value = q.text || '';
    root.querySelector('.q-response-type').value = q.response_type;
    root.querySelector('.q-required').checked = !!q.required;

    const optionsList = root.querySelector('.options');
    const addOptionBtn = root.querySelector('.add-option');
    const showOptions = q.response_type === 'multi' || q.response_type === 'yes_no';
    optionsList.classList.toggle('hidden', !showOptions);
    addOptionBtn.classList.toggle('hidden', q.response_type !== 'multi');

    (q.options || []).forEach((o) => optionsList.appendChild(renderOptionEl(q, o)));

    root.querySelector('.q-text').addEventListener('blur', async (ev) => {
      await api('/questions/' + q.dbid, { method: 'PATCH', body: { text: ev.target.value } });
    });
    root.querySelector('.q-response-type').addEventListener('change', async (ev) => {
      await api('/questions/' + q.dbid, { method: 'PATCH', body: { response_type: ev.target.value } });
      await refreshPathway();
    });
    root.querySelector('.q-required').addEventListener('change', async (ev) => {
      await api('/questions/' + q.dbid, { method: 'PATCH', body: { required: ev.target.checked } });
    });
    root.querySelector('.delete-question').addEventListener('click', async () => {
      if (!confirm('Delete this question?')) return;
      await api('/questions/' + q.dbid, { method: 'DELETE' });
      await refreshPathway();
    });
    addOptionBtn.addEventListener('click', async () => {
      await api('/questions/' + q.dbid + '/options', { method: 'POST', body: { label: '' } });
      await refreshPathway();
    });
    return tpl;
  }

  function renderOptionEl(q, opt) {
    const tpl = document.getElementById('option-template').content.cloneNode(true);
    const root = tpl.querySelector('.option');
    root.dataset.optionDbid = opt.dbid;
    root.querySelector('.opt-label').value = opt.label || '';
    root.querySelector('.opt-label').addEventListener('blur', async (ev) => {
      await api('/options/' + opt.dbid, { method: 'PATCH', body: { label: ev.target.value } });
    });
    root.querySelector('.delete-option').addEventListener('click', async () => {
      if (q.response_type === 'yes_no') {
        alert('Yes/No questions require both options.');
        return;
      }
      await api('/options/' + opt.dbid, { method: 'DELETE' });
      await refreshPathway();
    });
    return tpl;
  }

  // ---------- Branch rules ----------

  function renderBranchEl(seg, rule) {
    const tpl = document.getElementById('branch-template').content.cloneNode(true);
    const root = tpl.querySelector('.branch');
    root.dataset.branchDbid = rule.dbid;
    const target = (state.pathway.segments || []).find((s) => s.dbid === rule.to_segment_dbid);
    root.querySelector('.branch-label-display').textContent =
      (rule.label || 'Rule') + ' → ' + (target ? target.title : '?') + '  (priority ' + rule.priority + ')';

    const editor = root.querySelector('.branch-editor');
    root.querySelector('.edit-branch').addEventListener('click', () => {
      hydrateBranchEditor(seg, rule, editor);
      editor.classList.toggle('hidden');
    });
    root.querySelector('.delete-branch').addEventListener('click', async () => {
      if (!confirm('Delete this rule?')) return;
      await api('/branches/' + rule.dbid, { method: 'DELETE' });
      await refreshPathway();
    });
    return tpl;
  }

  function hydrateBranchEditor(seg, rule, editor) {
    editor.querySelector('.b-label').value = rule.label || '';
    const targetSel = editor.querySelector('.b-target');
    targetSel.innerHTML = '';
    (state.pathway.segments || [])
      .filter((s) => s.dbid !== seg.dbid)
      .forEach((s) => {
        const opt = document.createElement('option');
        opt.value = s.dbid;
        opt.textContent = s.title;
        if (s.dbid === rule.to_segment_dbid) opt.selected = true;
        targetSel.appendChild(opt);
      });
    editor.querySelector('.b-priority').value = rule.priority;

    const condsEl = editor.querySelector('.conditions');
    condsEl.innerHTML = '';
    (rule.conditions || []).forEach((c) => condsEl.appendChild(renderConditionEl(seg, c)));

    editor.querySelector('.add-condition').onclick = () => {
      condsEl.appendChild(renderConditionEl(seg, { question_dbid: '', operator: 'eq', value: '' }));
    };
    editor.querySelector('.save-branch').onclick = async () => {
      const conditions = Array.from(condsEl.querySelectorAll('.condition')).map((node) => {
        const op = node.querySelector('.c-operator').value;
        let value = node.querySelector('.c-value').value;
        if (op === 'in') value = value.split(',').map((s) => s.trim()).filter(Boolean);
        return {
          question_dbid: Number(node.querySelector('.c-question').value),
          operator: op,
          value: value,
        };
      });
      await api('/branches/' + rule.dbid, {
        method: 'PATCH',
        body: {
          label: editor.querySelector('.b-label').value,
          to_segment_dbid: Number(targetSel.value),
          priority: Number(editor.querySelector('.b-priority').value),
          conditions: conditions,
        },
      });
      await refreshPathway();
    };
    editor.querySelector('.cancel-branch').onclick = () => editor.classList.add('hidden');
  }

  function renderConditionEl(seg, cond) {
    const tpl = document.getElementById('condition-template').content.cloneNode(true);
    const root = tpl.querySelector('.condition');
    const qSel = root.querySelector('.c-question');
    (seg.questions || []).forEach((q) => {
      const opt = document.createElement('option');
      opt.value = q.dbid;
      opt.textContent = q.text || '(untitled question)';
      if (Number(cond.question_dbid) === q.dbid) opt.selected = true;
      qSel.appendChild(opt);
    });
    root.querySelector('.c-operator').value = cond.operator || 'eq';
    root.querySelector('.c-value').value = Array.isArray(cond.value) ? cond.value.join(', ') : (cond.value || '');
    root.querySelector('.delete-condition').addEventListener('click', () => root.remove());
    return tpl;
  }

  // ---------- Add segment ----------

  els.addSegmentBtn.addEventListener('click', async () => {
    if (!state.pathway || !state.pathway.dbid) return;
    await api('/pathways/' + state.pathway.dbid + '/segments', {
      method: 'POST',
      body: { title: 'New segment' },
    });
    await refreshPathway();
  });

  // ---------- Boot ----------

  loadPathwayList();
})();
