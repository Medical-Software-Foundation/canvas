(function () {
  'use strict';

  const apiBase = document.body.dataset.apiBase;
  console.log('clinical_pathways builder v0.3.1 loaded');

  const els = {
    list: document.getElementById('pathway-list-items'),
    newBtn: document.getElementById('new-pathway-btn'),
    empty: document.getElementById('empty-state'),
    editor: document.getElementById('pathway-editor'),
    title: document.getElementById('pathway-title'),
    description: document.getElementById('pathway-description'),
    statusPill: document.getElementById('status-pill'),
    publishBtn: document.getElementById('publish-btn'),
    unpublishBtn: document.getElementById('unpublish-btn'),
    deleteBtn: document.getElementById('delete-pathway-btn'),
    nodesHost: document.getElementById('nodes-host'),
    addNodeBtn: document.getElementById('add-node-btn'),
    validation: document.getElementById('validation-issues'),
    validationList: document.getElementById('validation-list'),
    saveStatus: document.getElementById('save-status'),
    questionsList: document.getElementById('questions-list'),
    recommendationsList: document.getElementById('recommendations-list'),
    addRecBtn: document.getElementById('add-recommendation-btn'),
    recModal: document.getElementById('recommendation-modal'),
    recForm: document.getElementById('recommendation-form'),
    closeRecModalBtn: document.getElementById('close-recommendation-modal'),
    saveRecBtn: document.getElementById('save-recommendation-btn'),
    deleteRecBtn: document.getElementById('delete-recommendation-btn'),
  };

  const state = {
    pathway: null,
    questionnaires: [],
    questionnaireDetails: {},
    terminalCommands: [],
    editingRecommendationId: null,
  };

  // ---------- Status banner ----------

  let _statusTimer = null;
  function flashStatus(text, kind) {
    els.saveStatus.textContent = text;
    els.saveStatus.className = 'save-status ' + (kind || 'ok');
    if (_statusTimer) clearTimeout(_statusTimer);
    _statusTimer = setTimeout(() => {
      els.saveStatus.textContent = '';
      els.saveStatus.className = 'save-status';
    }, kind === 'err' ? 6000 : 1800);
  }

  // ---------- HTTP ----------

  async function api(path, options = {}) {
    const opts = Object.assign({ headers: { 'Content-Type': 'application/json' } }, options);
    if (opts.body && typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
    const res = await fetch(apiBase + path, opts);
    if (!res.ok) {
      const text = await res.text();
      flashStatus('Request failed: ' + (text || res.statusText), 'err');
      throw new Error(text || res.statusText);
    }
    return res.status === 204 ? null : res.json();
  }

  // ---------- ID minting ----------

  function newId(prefix) {
    return prefix + Math.random().toString(36).slice(2, 12);
  }
  const newNodeId = () => newId('n_');
  const newRuleId = () => newId('r_');
  const newRecommendationId = () => newId('rec_');

  // ---------- Persistence ----------

  let _saveTimer = null;
  function scheduleSave() {
    if (_saveTimer) clearTimeout(_saveTimer);
    _saveTimer = setTimeout(() => {
      _saveTimer = null;
      void flushSave();
    }, 400);
  }
  async function flushSave() {
    if (_saveTimer) { clearTimeout(_saveTimer); _saveTimer = null; }
    if (!state.pathway || !state.pathway.dbid) return;
    try {
      await api('/pathways/' + state.pathway.dbid, {
        method: 'PUT',
        body: {
          title: state.pathway.title,
          description: state.pathway.description,
          definition: state.pathway.definition,
        },
      });
      flashStatus('Saved');
      await reloadList();
    } catch (_) { /* flashStatus already shown */ }
  }
  const savePathway = scheduleSave;

  // ---------- Pathway list ----------

  async function reloadList() {
    const { pathways } = await api('/pathways');
    els.list.innerHTML = '';
    pathways.forEach((pw) => {
      const li = document.createElement('li');
      const name = document.createElement('span');
      name.className = 'name';
      name.textContent = pw.title;
      li.appendChild(name);
      const badge = document.createElement('span');
      badge.className = 'badge ' + (pw.status === 'published' ? 'published' : 'draft');
      badge.textContent = pw.status;
      li.appendChild(badge);
      if (state.pathway && state.pathway.dbid === pw.dbid) li.classList.add('active');
      li.addEventListener('click', () => loadPathway(pw.dbid));
      els.list.appendChild(li);
    });
  }

  async function loadPathway(dbid) {
    const pw = await api('/pathways/' + dbid);
    state.pathway = upgradeDefinitionIfNeeded(pw);
    renderEditor();
    await reloadList();
  }

  function upgradeDefinitionIfNeeded(pw) {
    // v0.2 pathways have version 1 (or no version). The new builder
    // doesn't migrate them — the user re-authors.
    if (!pw.definition || pw.definition.version !== 2) {
      pw.definition = { version: 2, start_node_id: null, nodes: [], recommendations: [] };
    }
    return pw;
  }

  async function createPathway() {
    const pw = await api('/pathways', { method: 'POST', body: { title: 'Untitled pathway' } });
    state.pathway = upgradeDefinitionIfNeeded(pw);
    flashStatus('New pathway created');
    await reloadList();
    renderEditor();
    els.title.focus();
    els.title.select();
  }

  async function deletePathway() {
    if (!state.pathway || !state.pathway.dbid) return;
    if (!confirm('Delete this pathway? It will be marked inactive and unpublished.')) return;
    await api('/pathways/' + state.pathway.dbid, { method: 'DELETE' });
    state.pathway = null;
    flashStatus('Pathway deleted');
    await reloadList();
    renderEditor();
  }

  // ---------- Catalog ----------

  async function searchQuestionnaires(q) {
    const res = await api('/catalog/questionnaires?q=' + encodeURIComponent(q || ''));
    state.questionnaires = res.questionnaires || [];
    return state.questionnaires;
  }
  async function getQuestionnaireDetail(id) {
    if (state.questionnaireDetails[id]) return state.questionnaireDetails[id];
    const detail = await api('/catalog/questionnaires/' + encodeURIComponent(id));
    state.questionnaireDetails[id] = detail;
    return detail;
  }
  async function loadTerminalCommands() {
    if (state.terminalCommands.length) return state.terminalCommands;
    const res = await api('/catalog/terminal-commands');
    state.terminalCommands = res.terminal_commands || [];
    return state.terminalCommands;
  }

  // ---------- Top-level editor render ----------

  function renderEditor() {
    if (!state.pathway) {
      els.empty.classList.remove('hidden');
      els.editor.classList.add('hidden');
      return;
    }
    els.empty.classList.add('hidden');
    els.editor.classList.remove('hidden');
    els.title.value = state.pathway.title || '';
    els.description.value = state.pathway.description || '';
    const status = state.pathway.status || 'draft';
    els.statusPill.textContent = status;
    els.statusPill.className = 'status-pill ' + status;
    els.publishBtn.classList.toggle('hidden', status === 'published');
    els.unpublishBtn.classList.toggle('hidden', status !== 'published');
    renderNodes();
    renderRightRail();
    els.validation.classList.add('hidden');
  }

  // ---------- Letter labels ----------

  function letterFor(index) {
    if (index < 26) return String.fromCharCode(65 + index);
    const first = Math.floor(index / 26) - 1;
    const second = index % 26;
    return String.fromCharCode(65 + first) + String.fromCharCode(65 + second);
  }

  // ---------- Nodes ----------

  function renderNodes() {
    els.nodesHost.innerHTML = '';
    const definition = state.pathway.definition;
    const nodes = definition.nodes || [];
    if (!nodes.length) {
      const empty = document.createElement('div');
      empty.className = 'hint';
      empty.textContent = 'Add the first questionnaire below to begin.';
      els.nodesHost.appendChild(empty);
      return;
    }
    nodes.forEach((node, idx) => {
      els.nodesHost.appendChild(renderNodeCard(node, idx));
    });
  }

  function renderNodeCard(node, idx) {
    const definition = state.pathway.definition;
    const card = document.createElement('article');
    card.className = 'node-card';
    if (node.node_id === definition.start_node_id) card.classList.add('is-start');

    const header = document.createElement('header');
    header.className = 'node-card-header';

    const letter = document.createElement('span');
    letter.className = 'node-card-letter';
    letter.textContent = letterFor(idx);
    header.appendChild(letter);

    const title = document.createElement('div');
    title.className = 'node-card-title';
    title.textContent = node.questionnaire_name_snapshot || '(no questionnaire picked yet)';
    header.appendChild(title);

    if (node.node_id === definition.start_node_id) {
      const startMarker = document.createElement('span');
      startMarker.className = 'start-marker';
      startMarker.textContent = 'Start';
      header.appendChild(startMarker);
    } else {
      const makeStart = document.createElement('button');
      makeStart.type = 'button';
      makeStart.className = 'ghost small';
      makeStart.textContent = 'Make start';
      makeStart.addEventListener('click', () => {
        definition.start_node_id = node.node_id;
        savePathway();
        renderEditor();
      });
      header.appendChild(makeStart);
    }

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'ghost small';
    removeBtn.textContent = 'Remove';
    removeBtn.title = 'Remove this questionnaire from the pathway';
    removeBtn.addEventListener('click', () => removeNode(node));
    header.appendChild(removeBtn);

    card.appendChild(header);

    // Questionnaire picker
    const pickerRow = document.createElement('div');
    pickerRow.className = 'picker-row';
    const sel = document.createElement('select');
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '— Choose a questionnaire —';
    sel.appendChild(placeholder);
    if (node.questionnaire_id) {
      const opt = document.createElement('option');
      opt.value = node.questionnaire_id;
      opt.textContent = node.questionnaire_name_snapshot || node.questionnaire_id.slice(0, 8);
      sel.appendChild(opt);
    }
    state.questionnaires.forEach((q) => {
      if (q.id === node.questionnaire_id) return;
      const opt = document.createElement('option');
      opt.value = q.id;
      opt.textContent = q.name + (q.code ? ' (' + q.code + ')' : '');
      sel.appendChild(opt);
    });
    sel.value = node.questionnaire_id || '';
    sel.addEventListener('change', async (ev) => {
      const id = ev.target.value;
      if (!id) {
        node.questionnaire_id = '';
        node.questionnaire_name_snapshot = '';
      } else {
        const detail = await getQuestionnaireDetail(id);
        node.questionnaire_id = id;
        node.questionnaire_name_snapshot = detail.name;
      }
      savePathway();
      renderEditor();
    });
    pickerRow.appendChild(sel);
    card.appendChild(pickerRow);

    const hint = document.createElement('p');
    hint.className = 'hint';
    hint.textContent = node.node_id === definition.start_node_id
      ? 'Auto-inserts into the note when the pathway is started.'
      : 'Auto-inserts when a rule on an earlier questionnaire routes here.';
    card.appendChild(hint);

    if (node.questionnaire_id) {
      const rulesHost = document.createElement('div');
      rulesHost.className = 'rules-host';
      (node.rules || []).forEach((rule) => {
        rulesHost.appendChild(renderRuleCard(node, rule));
      });
      card.appendChild(rulesHost);

      const addRule = document.createElement('button');
      addRule.type = 'button';
      addRule.className = 'secondary small';
      addRule.textContent = '+ Add rule';
      addRule.addEventListener('click', () => {
        node.rules = node.rules || [];
        node.rules.push({
          rule_id: newRuleId(),
          label: '',
          combinator: 'all',
          conditions: [],
          then: null,
        });
        savePathway();
        renderEditor();
      });
      card.appendChild(addRule);
    }

    return card;
  }

  function removeNode(node) {
    const definition = state.pathway.definition;
    if (!confirm('Remove this questionnaire and its rules?')) return;
    definition.nodes = (definition.nodes || []).filter((n) => n.node_id !== node.node_id);
    if (definition.start_node_id === node.node_id) {
      definition.start_node_id = definition.nodes[0] ? definition.nodes[0].node_id : null;
    }
    (definition.nodes || []).forEach((n) => {
      (n.rules || []).forEach((r) => {
        if (r.then && r.then.type === 'node' && r.then.target_id === node.node_id) {
          r.then = null;
        }
      });
    });
    savePathway();
    renderEditor();
  }

  // ---------- Rules ----------

  function renderRuleCard(node, rule) {
    const definition = state.pathway.definition;
    const card = document.createElement('div');
    card.className = 'rule-card';
    card.dataset.ruleId = rule.rule_id;

    const header = document.createElement('header');
    header.className = 'rule-header';

    const ifSpan = document.createElement('span');
    ifSpan.className = 'rule-if-label';
    ifSpan.textContent = 'If';
    header.appendChild(ifSpan);

    const combSel = document.createElement('select');
    combSel.className = 'combinator-select';
    [['all', 'All of'], ['any', 'Any of']].forEach(([v, lbl]) => {
      const o = document.createElement('option');
      o.value = v; o.textContent = lbl;
      combSel.appendChild(o);
    });
    combSel.value = rule.combinator === 'any' ? 'any' : 'all';
    combSel.addEventListener('change', (ev) => {
      rule.combinator = ev.target.value;
      savePathway();
      renderEditor();
    });
    header.appendChild(combSel);

    const spacer = document.createElement('span');
    spacer.style.flex = '1';
    header.appendChild(spacer);

    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'ghost small';
    delBtn.textContent = '×';
    delBtn.title = 'Delete rule';
    delBtn.addEventListener('click', () => {
      if (!confirm('Delete this rule?')) return;
      node.rules = (node.rules || []).filter((r) => r.rule_id !== rule.rule_id);
      savePathway();
      renderEditor();
    });
    header.appendChild(delBtn);
    card.appendChild(header);

    const condsHost = document.createElement('div');
    condsHost.className = 'conditions-host';
    (rule.conditions || []).forEach((cond, idx) => {
      condsHost.appendChild(renderConditionRow(rule, cond, idx));
      if (idx < (rule.conditions.length - 1)) {
        const sep = document.createElement('div');
        sep.className = 'connector-label';
        sep.textContent = rule.combinator === 'any' ? 'or' : 'and';
        condsHost.appendChild(sep);
      }
    });
    card.appendChild(condsHost);

    const addCondBtn = document.createElement('button');
    addCondBtn.type = 'button';
    addCondBtn.className = 'ghost small';
    addCondBtn.textContent = '+ condition';
    addCondBtn.addEventListener('click', () => {
      rule.conditions = rule.conditions || [];
      const allQs = collectAvailableQuestions();
      rule.conditions.push({
        question_id: allQs[0] ? allQs[0].question_id : '',
        operator: 'eq',
        value_option_id: '',
        value_option_ids: [],
        value_text: '',
        value_number: null,
      });
      savePathway();
      renderEditor();
    });
    card.appendChild(addCondBtn);

    // Then row
    const thenRow = document.createElement('div');
    thenRow.className = 'then-row';
    const thenLabel = document.createElement('span');
    thenLabel.className = 'then-label';
    thenLabel.textContent = 'Then go to';
    thenRow.appendChild(thenLabel);

    const thenSel = document.createElement('select');
    const placeholderOpt = document.createElement('option');
    placeholderOpt.value = '';
    placeholderOpt.textContent = '— Choose target —';
    thenSel.appendChild(placeholderOpt);

    const nodeGroup = document.createElement('optgroup');
    nodeGroup.label = 'Questionnaires';
    (definition.nodes || []).forEach((n) => {
      if (n.node_id === node.node_id) return;
      const o = document.createElement('option');
      o.value = 'node:' + n.node_id;
      o.textContent = n.questionnaire_name_snapshot || '(unnamed)';
      nodeGroup.appendChild(o);
    });
    if (nodeGroup.children.length) thenSel.appendChild(nodeGroup);

    const recGroup = document.createElement('optgroup');
    recGroup.label = 'Recommendations';
    (definition.recommendations || []).forEach((r) => {
      const o = document.createElement('option');
      o.value = 'rec:' + r.recommendation_id;
      o.textContent = r.name || '(unnamed)';
      recGroup.appendChild(o);
    });
    if (recGroup.children.length) thenSel.appendChild(recGroup);

    if (rule.then && rule.then.type && rule.then.target_id) {
      thenSel.value = rule.then.type === 'node'
        ? 'node:' + rule.then.target_id
        : 'rec:' + rule.then.target_id;
    } else {
      thenSel.value = '';
    }
    thenSel.addEventListener('change', (ev) => {
      const v = ev.target.value;
      if (!v) {
        rule.then = null;
      } else if (v.startsWith('node:')) {
        rule.then = { type: 'node', target_id: v.slice(5) };
      } else if (v.startsWith('rec:')) {
        rule.then = { type: 'recommendation', target_id: v.slice(4) };
      }
      savePathway();
    });
    thenRow.appendChild(thenSel);
    card.appendChild(thenRow);

    return card;
  }

  // ---------- Conditions ----------

  function collectAvailableQuestions() {
    const out = [];
    const seen = new Set();
    (state.pathway.definition.nodes || []).forEach((n) => {
      if (!n.questionnaire_id) return;
      const detail = state.questionnaireDetails[n.questionnaire_id];
      if (!detail || !detail.questions) return;
      detail.questions.forEach((q) => {
        if (seen.has(q.id)) return;
        seen.add(q.id);
        out.push({
          question_id: q.id,
          question_name: q.name,
          questionnaire_id: n.questionnaire_id,
          questionnaire_name: detail.name,
          response_set_type: q.response_set_type,
          options: q.options || [],
        });
      });
    });
    return out;
  }

  function renderConditionRow(rule, cond, idx) {
    const row = document.createElement('div');
    row.className = 'condition-row';

    const allQs = collectAvailableQuestions();

    const qSel = document.createElement('select');
    if (!cond.question_id) {
      const ph = document.createElement('option');
      ph.value = '';
      ph.textContent = '— question —';
      qSel.appendChild(ph);
    }
    allQs.forEach((q) => {
      const o = document.createElement('option');
      o.value = q.question_id;
      o.textContent = q.question_name;
      o.title = q.questionnaire_name + ' — ' + q.question_name;
      qSel.appendChild(o);
    });
    qSel.value = cond.question_id || '';

    const opSel = document.createElement('select');
    const valueCell = document.createElement('span');
    valueCell.className = 'value-cell';

    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'ghost small';
    delBtn.textContent = '×';
    delBtn.title = 'Delete condition';
    delBtn.addEventListener('click', () => {
      rule.conditions = (rule.conditions || []).filter((_, i) => i !== idx);
      savePathway();
      renderEditor();
    });

    row.appendChild(qSel);
    row.appendChild(opSel);
    row.appendChild(valueCell);
    row.appendChild(delBtn);

    const currentQuestion = allQs.find((q) => q.question_id === cond.question_id);
    renderOperatorAndValue(opSel, valueCell, cond, currentQuestion, savePathway);

    qSel.addEventListener('change', (ev) => {
      cond.question_id = ev.target.value;
      cond.operator = 'eq';
      cond.value_option_id = '';
      cond.value_option_ids = [];
      cond.value_text = '';
      cond.value_number = null;
      const q = allQs.find((qq) => qq.question_id === cond.question_id);
      renderOperatorAndValue(opSel, valueCell, cond, q, savePathway);
      savePathway();
    });

    return row;
  }

  function renderOperatorAndValue(opSel, valueCell, cond, question, onChange) {
    opSel.innerHTML = '';
    valueCell.innerHTML = '';
    const type = (question && question.response_set_type) || 'TXT';
    const ops = operatorsForType(type);
    const validKeys = ops.map(([v]) => v);
    if (!validKeys.includes(cond.operator)) {
      cond.operator = ops[0] ? ops[0][0] : 'eq';
    }
    ops.forEach(([v, lbl]) => {
      const o = document.createElement('option');
      o.value = v;
      o.textContent = lbl;
      opSel.appendChild(o);
    });
    opSel.value = cond.operator;
    opSel.onchange = (ev) => {
      cond.operator = ev.target.value;
      renderValueWidget(valueCell, cond, question, onChange);
      onChange();
    };
    renderValueWidget(valueCell, cond, question, onChange);
  }

  function operatorsForType(type) {
    if (type === 'SING') {
      return [['eq', 'equals'], ['neq', 'does not equal'], ['any_answer', 'any answer'], ['no_answer', 'no answer']];
    }
    if (type === 'MULT') {
      return [
        ['contains_any', 'contains any of'],
        ['contains_all', 'contains all of'],
        ['contains_none', 'contains none of'],
        ['any_answer', 'any answer'],
        ['no_answer', 'no answer'],
      ];
    }
    if (type === 'INT') {
      return [['eq', '='], ['neq', '≠'], ['lt', '<'], ['lte', '≤'], ['gt', '>'], ['gte', '≥'], ['any_answer', 'any answer'], ['no_answer', 'no answer']];
    }
    return [['eq', 'equals'], ['neq', 'does not equal'], ['contains', 'contains'], ['any_answer', 'any answer'], ['no_answer', 'no answer']];
  }

  function renderValueWidget(host, cond, question, onChange) {
    host.innerHTML = '';
    if (cond.operator === 'any_answer' || cond.operator === 'no_answer') return;
    const type = (question && question.response_set_type) || 'TXT';
    const options = (question && question.options) || [];

    if (type === 'SING') {
      const sel = document.createElement('select');
      const ph = document.createElement('option');
      ph.value = ''; ph.textContent = '— value —';
      sel.appendChild(ph);
      options.forEach((o) => {
        const opt = document.createElement('option');
        opt.value = o.id;
        opt.textContent = o.name || o.value;
        if (o.id === cond.value_option_id) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.value = cond.value_option_id || '';
      sel.addEventListener('change', (ev) => {
        cond.value_option_id = ev.target.value;
        onChange();
      });
      host.appendChild(sel);
      queueMicrotask(() => {
        if (cond.value_option_id && sel.value !== cond.value_option_id) sel.value = cond.value_option_id;
      });
      return;
    }
    if (type === 'MULT') {
      const wrap = document.createElement('span');
      wrap.style.display = 'flex';
      wrap.style.gap = '6px';
      wrap.style.flexWrap = 'wrap';
      const ids = cond.value_option_ids || (cond.value_option_id ? [cond.value_option_id] : []);
      options.forEach((o) => {
        const lbl = document.createElement('label');
        lbl.style.fontSize = '12px';
        lbl.style.whiteSpace = 'nowrap';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = ids.includes(o.id);
        cb.addEventListener('change', () => {
          const next = new Set(cond.value_option_ids || []);
          if (cb.checked) next.add(o.id); else next.delete(o.id);
          cond.value_option_ids = Array.from(next);
          onChange();
        });
        lbl.appendChild(cb);
        lbl.appendChild(document.createTextNode(' ' + (o.name || o.value)));
        wrap.appendChild(lbl);
      });
      host.appendChild(wrap);
      return;
    }
    if (type === 'INT') {
      const inp = document.createElement('input');
      inp.type = 'number';
      inp.value = cond.value_number != null ? cond.value_number : '';
      inp.addEventListener('input', (ev) => {
        cond.value_number = ev.target.value === '' ? null : Number(ev.target.value);
        onChange();
      });
      host.appendChild(inp);
      return;
    }
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.value = cond.value_text || '';
    inp.addEventListener('input', (ev) => {
      cond.value_text = ev.target.value;
      onChange();
    });
    host.appendChild(inp);
  }

  // ---------- Right rail: questions + recommendations ----------

  function renderRightRail() {
    renderQuestionsList();
    renderRecommendationsList();
  }

  function renderQuestionsList() {
    els.questionsList.innerHTML = '';
    const allQs = collectAvailableQuestions();
    if (!allQs.length) {
      const empty = document.createElement('li');
      empty.className = 'empty-message';
      empty.textContent = 'Pick a questionnaire to populate this list.';
      els.questionsList.appendChild(empty);
      return;
    }
    allQs.forEach((q, idx) => {
      const li = document.createElement('li');
      li.className = 'question-item';
      const letter = document.createElement('span');
      letter.className = 'letter-badge';
      letter.textContent = letterFor(idx);
      const text = document.createElement('span');
      text.className = 'item-text';
      text.textContent = q.question_name;
      text.title = q.questionnaire_name + ' — ' + q.question_name;
      li.appendChild(letter);
      li.appendChild(text);
      els.questionsList.appendChild(li);
    });
  }

  function renderRecommendationsList() {
    els.recommendationsList.innerHTML = '';
    const recs = state.pathway.definition.recommendations || [];
    if (!recs.length) {
      const empty = document.createElement('li');
      empty.className = 'empty-message';
      empty.textContent = 'No recommendations yet.';
      els.recommendationsList.appendChild(empty);
      return;
    }
    recs.forEach((r, idx) => {
      const li = document.createElement('li');
      li.className = 'recommendation-item';
      const letter = document.createElement('span');
      letter.className = 'letter-badge';
      letter.textContent = letterFor(idx);
      const text = document.createElement('span');
      text.className = 'item-text';
      text.textContent = r.name || '(unnamed recommendation)';
      const meta = document.createElement('span');
      meta.className = 'item-meta';
      if (r.params && r.params.severity) meta.textContent = r.params.severity;
      li.appendChild(letter);
      li.appendChild(text);
      if (meta.textContent) li.appendChild(meta);
      li.addEventListener('click', () => openRecommendationModal(r.recommendation_id));
      els.recommendationsList.appendChild(li);
    });
  }

  // ---------- Recommendation modal ----------

  async function openRecommendationModal(recommendationId) {
    await loadTerminalCommands();
    state.editingRecommendationId = recommendationId;
    renderRecommendationForm();
    els.recModal.classList.remove('hidden');
  }
  function closeRecommendationModal() {
    state.editingRecommendationId = null;
    els.recModal.classList.add('hidden');
  }

  function renderRecommendationForm() {
    els.recForm.innerHTML = '';
    const rec = (state.pathway.definition.recommendations || []).find(
      (r) => r.recommendation_id === state.editingRecommendationId,
    );
    if (!rec) return;

    const nameField = document.createElement('label');
    nameField.className = 'field';
    nameField.textContent = 'Name (shown in the right rail)';
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.value = rec.name || '';
    nameInput.addEventListener('input', (ev) => {
      rec.name = ev.target.value;
      savePathway();
      renderRecommendationsList();
    });
    nameField.appendChild(nameInput);
    els.recForm.appendChild(nameField);

    const cmd = state.terminalCommands.find((c) => c.key === rec.command_key)
      || state.terminalCommands[0];
    if (!rec.command_key && cmd) rec.command_key = cmd.key;

    (cmd ? cmd.fields : []).forEach((field) => {
      const lbl = document.createElement('label');
      lbl.className = 'field';
      lbl.textContent = field.label + (field.required ? ' *' : '');

      rec.params = rec.params || {};
      const v = rec.params[field.key] != null ? rec.params[field.key] : '';
      let input;
      if (field.type === 'textarea') {
        input = document.createElement('textarea');
        input.rows = 3;
        input.value = v;
      } else if (field.type === 'select') {
        input = document.createElement('select');
        (field.options || []).forEach((opt) => {
          const o = document.createElement('option');
          o.value = opt.value;
          o.textContent = opt.label;
          input.appendChild(o);
        });
        input.value = v;
      } else {
        input = document.createElement('input');
        input.type = 'text';
        input.value = v;
      }
      const evt = field.type === 'select' ? 'change' : 'input';
      input.addEventListener(evt, (ev) => {
        rec.params[field.key] = ev.target.value;
        savePathway();
        renderRecommendationsList();
      });
      lbl.appendChild(input);

      const hint = document.createElement('div');
      hint.className = 'field-hint';
      hint.textContent = 'Use {{question_id}} to interpolate an answer from earlier in this pathway.';
      lbl.appendChild(hint);

      els.recForm.appendChild(lbl);
    });
  }

  async function addRecommendation() {
    await loadTerminalCommands();
    const cmd = state.terminalCommands[0];
    const rec = {
      recommendation_id: newRecommendationId(),
      name: 'New recommendation',
      command_key: cmd ? cmd.key : '',
      params: {},
    };
    state.pathway.definition.recommendations = state.pathway.definition.recommendations || [];
    state.pathway.definition.recommendations.push(rec);
    savePathway();
    renderRightRail();
    renderNodes();
    openRecommendationModal(rec.recommendation_id);
  }

  function deleteCurrentRecommendation() {
    const recId = state.editingRecommendationId;
    if (!recId) return;
    if (!confirm('Delete this recommendation? Any rules pointing to it will lose their target.')) return;
    const def = state.pathway.definition;
    def.recommendations = (def.recommendations || []).filter((r) => r.recommendation_id !== recId);
    (def.nodes || []).forEach((n) => {
      (n.rules || []).forEach((r) => {
        if (r.then && r.then.type === 'recommendation' && r.then.target_id === recId) {
          r.then = null;
        }
      });
    });
    savePathway();
    closeRecommendationModal();
    renderEditor();
  }

  // ---------- Add node ----------

  async function addNode() {
    await searchQuestionnaires('');
    const def = state.pathway.definition;
    const node = {
      node_id: newNodeId(),
      questionnaire_id: '',
      questionnaire_name_snapshot: '',
      rules: [],
    };
    def.nodes = def.nodes || [];
    def.nodes.push(node);
    if (!def.start_node_id) def.start_node_id = node.node_id;
    savePathway();
    renderEditor();
  }

  // ---------- Top-level handlers ----------

  els.title.addEventListener('input', () => {
    if (!state.pathway) return;
    state.pathway.title = els.title.value;
    savePathway();
    const active = els.list.querySelector('li.active .name');
    if (active) active.textContent = state.pathway.title;
  });
  els.description.addEventListener('input', () => {
    if (!state.pathway) return;
    state.pathway.description = els.description.value;
    savePathway();
  });

  els.newBtn.addEventListener('click', createPathway);
  els.deleteBtn.addEventListener('click', deletePathway);
  els.addNodeBtn.addEventListener('click', addNode);
  els.addRecBtn.addEventListener('click', addRecommendation);
  els.closeRecModalBtn.addEventListener('click', closeRecommendationModal);
  els.saveRecBtn.addEventListener('click', closeRecommendationModal);
  els.deleteRecBtn.addEventListener('click', deleteCurrentRecommendation);
  els.recModal.querySelector('.modal-backdrop').addEventListener('click', closeRecommendationModal);

  els.publishBtn.addEventListener('click', async () => {
    if (!state.pathway || !state.pathway.dbid) return;
    await flushSave();
    try {
      const res = await api('/pathways/' + state.pathway.dbid + '/publish', { method: 'POST', body: {} });
      if (res.published) {
        state.pathway.status = 'published';
        flashStatus('Published');
        renderEditor();
        await reloadList();
      }
      renderValidation(res.issues || []);
    } catch (err) {
      let issues = [];
      try {
        const parsed = JSON.parse(err.message);
        issues = parsed.issues || [];
      } catch (_) { /* leave empty */ }
      renderValidation(issues);
    }
  });
  els.unpublishBtn.addEventListener('click', async () => {
    if (!state.pathway || !state.pathway.dbid) return;
    await api('/pathways/' + state.pathway.dbid + '/unpublish', { method: 'POST', body: {} });
    state.pathway.status = 'draft';
    flashStatus('Unpublished');
    renderEditor();
    await reloadList();
  });

  function renderValidation(issues) {
    els.validationList.innerHTML = '';
    if (!issues.length) {
      els.validation.classList.add('hidden');
      return;
    }
    issues.forEach((i) => {
      const li = document.createElement('li');
      li.className = i.severity || 'error';
      li.textContent = i.message;
      els.validationList.appendChild(li);
    });
    els.validation.classList.remove('hidden');
  }

  // ---------- Boot ----------

  (async () => {
    await Promise.all([searchQuestionnaires(''), loadTerminalCommands()]);
    await reloadList();
    renderEditor();
  })();
})();
