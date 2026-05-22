(function () {
  'use strict';

  const apiBase = document.body.dataset.apiBase;
  console.log('clinical_pathways builder v0.4.5 loaded');

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
    stepsHost: document.getElementById('steps-host'),
    validation: document.getElementById('validation-issues'),
    validationList: document.getElementById('validation-list'),
    saveStatus: document.getElementById('save-status'),
    addQSelect: document.getElementById('add-questionnaire-select'),
    addQBtn: document.getElementById('add-questionnaire-btn'),
    loadedQ: document.getElementById('loaded-questionnaires'),
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

  function newId(prefix) { return prefix + Math.random().toString(36).slice(2, 12); }
  const newStepId = () => newId('s_');
  const newRuleId = () => newId('r_');
  const newRecommendationId = () => newId('rec_');

  // ---------- Persistence ----------

  let _saveTimer = null;
  function scheduleSave() {
    if (_saveTimer) clearTimeout(_saveTimer);
    _saveTimer = setTimeout(() => { _saveTimer = null; void flushSave(); }, 400);
  }
  async function flushSave() {
    if (_saveTimer) { clearTimeout(_saveTimer); _saveTimer = null; }
    if (!state.pathway || !state.pathway.dbid) return;
    try {
      // Keep start_step_id in sync with the first step.
      const def = state.pathway.definition;
      if (def && def.steps && def.steps[0]) {
        def.start_step_id = def.steps[0].step_id;
      } else if (def) {
        def.start_step_id = null;
      }
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
    // Preload details for any loaded questionnaires so the rail can render
    // their questions immediately.
    await Promise.all(
      (state.pathway.definition.loaded_questionnaires || []).map(
        (q) => getQuestionnaireDetail(q.questionnaire_id).catch(() => null),
      ),
    );
    renderEditor();
    await reloadList();
  }

  function upgradeDefinitionIfNeeded(pw) {
    if (!pw.definition || pw.definition.version !== 3) {
      pw.definition = {
        version: 3,
        start_step_id: null,
        loaded_questionnaires: [],
        steps: [],
        recommendations: [],
      };
    }
    pw.definition.loaded_questionnaires = pw.definition.loaded_questionnaires || [];
    pw.definition.steps = pw.definition.steps || [];
    pw.definition.recommendations = pw.definition.recommendations || [];
    // v0.4.5: the standalone "Name" field on recommendations is gone —
    // title doubles as the rail label. Backfill title from name for legacy
    // records so the form input isn't blank, and fold any prior
    // recommended_action text into the body so it isn't lost.
    (pw.definition.recommendations || []).forEach((rec) => {
      rec.params = rec.params || {};
      if (!rec.params.title && rec.name) {
        rec.params.title = rec.name;
      }
      if (rec.params.recommended_action) {
        const action = String(rec.params.recommended_action).trim();
        if (action) {
          const existing = String(rec.params.body || '').trim();
          rec.params.body = existing
            ? existing + '\n\nRecommended action: ' + action
            : 'Recommended action: ' + action;
        }
        delete rec.params.recommended_action;
      }
      // Keep rail label in sync with title.
      if (rec.params.title) rec.name = rec.params.title;
    });
    // v0.4.4: per-rule combinator → per-condition connector. Translate
    // 'any' → 'or' on every non-first condition, 'all' (or absent) → 'and',
    // then drop the rule-level field. New rules write the new shape only.
    (pw.definition.steps || []).forEach((step) => {
      (step.rules || []).forEach((rule) => {
        const conds = rule.conditions || [];
        const legacy = rule.combinator === 'any' ? 'or' : 'and';
        conds.forEach((cond, idx) => {
          if (idx === 0) {
            delete cond.connector;
          } else if (!cond.connector) {
            cond.connector = legacy;
          }
        });
        delete rule.combinator;
      });
    });
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
    if (!id) return null;
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
    renderSteps();
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

  // ---------- Steps ----------

  function renderSteps() {
    els.stepsHost.innerHTML = '';
    const def = state.pathway.definition;
    const steps = def.steps || [];
    if (!steps.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-steps';
      empty.textContent = 'Add a question from the Questionnaires panel on the right to create your first step.';
      els.stepsHost.appendChild(empty);
      return;
    }
    steps.forEach((step, idx) => {
      els.stepsHost.appendChild(renderStepCard(step, idx));
    });
  }

  function renderStepCard(step, idx) {
    const def = state.pathway.definition;
    const card = document.createElement('article');
    card.className = 'step-card';
    if (idx === 0) card.classList.add('is-start');

    const header = document.createElement('header');
    header.className = 'step-card-header';
    const letter = document.createElement('span');
    letter.className = 'step-card-letter';
    letter.textContent = letterFor(idx);
    header.appendChild(letter);

    const titleBlock = document.createElement('div');
    titleBlock.className = 'step-card-title';
    const qText = document.createElement('div');
    qText.className = 'question-text';
    qText.textContent = step.question_name_snapshot || '(unknown question)';
    titleBlock.appendChild(qText);
    const qnMeta = document.createElement('div');
    qnMeta.className = 'questionnaire-meta';
    qnMeta.textContent = 'From: ' + (step.questionnaire_name_snapshot || '(unknown questionnaire)');
    titleBlock.appendChild(qnMeta);
    header.appendChild(titleBlock);

    if (idx === 0) {
      const startMarker = document.createElement('span');
      startMarker.className = 'start-marker';
      startMarker.textContent = 'Start';
      header.appendChild(startMarker);
    }

    const actions = document.createElement('div');
    actions.className = 'step-card-actions';
    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.className = 'ghost small';
    upBtn.textContent = '↑';
    upBtn.title = 'Move up';
    upBtn.disabled = idx === 0;
    upBtn.addEventListener('click', () => moveStep(idx, idx - 1));
    actions.appendChild(upBtn);
    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.className = 'ghost small';
    downBtn.textContent = '↓';
    downBtn.title = 'Move down';
    downBtn.disabled = idx === def.steps.length - 1;
    downBtn.addEventListener('click', () => moveStep(idx, idx + 1));
    actions.appendChild(downBtn);
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'ghost small';
    delBtn.textContent = '×';
    delBtn.title = 'Remove step';
    delBtn.addEventListener('click', () => removeStep(step));
    actions.appendChild(delBtn);
    header.appendChild(actions);

    card.appendChild(header);

    // Each step has exactly one implicit rule — auto-create if missing
    // (e.g., legacy data). No "Add rule" or "Delete rule" affordance.
    if (!step.rules || !step.rules.length) {
      step.rules = [
        {
          rule_id: newRuleId(),
          conditions: [
            {
              question_id: step.question_id || '',
              operator: 'eq',
              value_option_id: '',
              value_option_ids: [],
              value_text: '',
              value_number: null,
            },
          ],
          then: null,
        },
      ];
    }
    const rule = step.rules[0];
    card.appendChild(renderRuleBody(step, rule));

    // Otherwise row
    const otherwiseRow = document.createElement('div');
    otherwiseRow.className = 'otherwise-row';
    const otherwiseLabel = document.createElement('span');
    otherwiseLabel.className = 'then-label';
    otherwiseLabel.textContent = 'Otherwise go to';
    otherwiseRow.appendChild(otherwiseLabel);
    const otherwiseSel = buildTargetSelect(step, step.otherwise, /*includeNoneOption*/ true);
    otherwiseSel.addEventListener('change', (ev) => {
      step.otherwise = parseTargetValue(ev.target.value);
      savePathway();
    });
    otherwiseRow.appendChild(otherwiseSel);
    card.appendChild(otherwiseRow);

    return card;
  }

  function moveStep(fromIdx, toIdx) {
    const def = state.pathway.definition;
    const steps = def.steps || [];
    if (toIdx < 0 || toIdx >= steps.length) return;
    const [moved] = steps.splice(fromIdx, 1);
    steps.splice(toIdx, 0, moved);
    savePathway();
    renderEditor();
  }

  function removeStep(step) {
    if (!confirm('Remove this step?')) return;
    const def = state.pathway.definition;
    def.steps = (def.steps || []).filter((s) => s.step_id !== step.step_id);
    // Drop any rule.then / step.otherwise that pointed at the removed step.
    (def.steps || []).forEach((s) => {
      if (s.otherwise && s.otherwise.type === 'step' && s.otherwise.target_id === step.step_id) {
        s.otherwise = null;
      }
      (s.rules || []).forEach((r) => {
        if (r.then && r.then.type === 'step' && r.then.target_id === step.step_id) {
          r.then = null;
        }
      });
    });
    savePathway();
    renderEditor();
  }

  // ---------- Target selectors (used by Then and Otherwise) ----------

  function buildTargetSelect(step, currentTarget, includeNoneOption) {
    const def = state.pathway.definition;
    const sel = document.createElement('select');
    if (includeNoneOption) {
      const noneOpt = document.createElement('option');
      noneOpt.value = '';
      noneOpt.textContent = '— end of pathway —';
      sel.appendChild(noneOpt);
    } else {
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = '— Choose target —';
      sel.appendChild(placeholder);
    }
    const stepGroup = document.createElement('optgroup');
    stepGroup.label = 'Next step';
    (def.steps || []).forEach((s, idx) => {
      if (s.step_id === step.step_id) return;
      const o = document.createElement('option');
      o.value = 'step:' + s.step_id;
      o.textContent = letterFor(idx) + ' — ' + (s.question_name_snapshot || '(unnamed)');
      stepGroup.appendChild(o);
    });
    if (stepGroup.children.length) sel.appendChild(stepGroup);

    const recGroup = document.createElement('optgroup');
    recGroup.label = 'Recommendation';
    (def.recommendations || []).forEach((r) => {
      const o = document.createElement('option');
      o.value = 'rec:' + r.recommendation_id;
      o.textContent = r.name || '(unnamed)';
      recGroup.appendChild(o);
    });
    if (recGroup.children.length) sel.appendChild(recGroup);

    if (currentTarget && currentTarget.type && currentTarget.target_id) {
      const prefix = currentTarget.type === 'step' ? 'step:' : 'rec:';
      sel.value = prefix + currentTarget.target_id;
    } else {
      sel.value = '';
    }
    return sel;
  }

  function parseTargetValue(v) {
    if (!v) return null;
    if (v.startsWith('step:')) return { type: 'step', target_id: v.slice(5) };
    if (v.startsWith('rec:')) return { type: 'recommendation', target_id: v.slice(4) };
    return null;
  }

  // ---------- Rules ----------

  function renderRuleBody(step, rule) {
    const card = document.createElement('div');
    card.className = 'rule-card';
    card.dataset.ruleId = rule.rule_id;

    const header = document.createElement('header');
    header.className = 'rule-header';

    const ifSpan = document.createElement('span');
    ifSpan.className = 'rule-if-label';
    ifSpan.textContent = 'If';
    header.appendChild(ifSpan);
    card.appendChild(header);

    const condsHost = document.createElement('div');
    condsHost.className = 'conditions-host';
    (rule.conditions || []).forEach((cond, idx) => {
      if (idx > 0) condsHost.appendChild(renderConnectorRadios(rule, cond, idx));
      condsHost.appendChild(renderConditionRow(rule, cond, idx));
    });
    card.appendChild(condsHost);

    const addCondBtn = document.createElement('button');
    addCondBtn.type = 'button';
    addCondBtn.className = 'ghost small';
    addCondBtn.textContent = '+ condition';
    addCondBtn.addEventListener('click', () => {
      rule.conditions = rule.conditions || [];
      const allQs = collectAvailableQuestions();
      // Default condition references this step's own question if available.
      const defaultQid = step.question_id || (allQs[0] ? allQs[0].question_id : '');
      rule.conditions.push({
        question_id: defaultQid,
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
    const thenSel = buildTargetSelect(step, rule.then, /*includeNoneOption*/ false);
    thenSel.addEventListener('change', (ev) => {
      rule.then = parseTargetValue(ev.target.value);
      savePathway();
    });
    thenRow.appendChild(thenSel);
    card.appendChild(thenRow);

    return card;
  }

  // ---------- Conditions ----------

  function collectAvailableQuestions() {
    // All questions from all loaded questionnaires, regardless of whether
    // they've been added as steps. Rule conditions can reference any
    // captured-by-the-time-it-runs question.
    const out = [];
    const seen = new Set();
    (state.pathway.definition.loaded_questionnaires || []).forEach((lq) => {
      const detail = state.questionnaireDetails[lq.questionnaire_id];
      if (!detail || !detail.questions) return;
      detail.questions.forEach((q) => {
        if (seen.has(q.id)) return;
        seen.add(q.id);
        out.push({
          question_id: q.id,
          question_name: q.name,
          questionnaire_id: lq.questionnaire_id,
          questionnaire_name: detail.name,
          response_set_type: q.response_set_type,
          options: q.options || [],
        });
      });
    });
    return out;
  }

  function renderConnectorRadios(rule, cond, idx) {
    const wrap = document.createElement('div');
    wrap.className = 'connector-radios';
    const groupName = 'conn-' + rule.rule_id + '-' + idx;
    const current = cond.connector === 'or' ? 'or' : 'and';
    [['and', 'and'], ['or', 'or']].forEach(([v, lbl]) => {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = groupName;
      input.value = v;
      if (v === current) input.checked = true;
      input.addEventListener('change', () => {
        if (!input.checked) return;
        cond.connector = v;
        savePathway();
      });
      label.appendChild(input);
      label.appendChild(document.createTextNode(' ' + lbl));
      wrap.appendChild(label);
    });
    return wrap;
  }

  function renderConditionRow(rule, cond, idx) {
    const row = document.createElement('div');
    row.className = 'condition-row';

    const allQs = collectAvailableQuestions();

    const qSel = document.createElement('select');
    if (!cond.question_id) {
      const ph = document.createElement('option');
      ph.value = ''; ph.textContent = '— question —';
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
    if (!validKeys.includes(cond.operator)) cond.operator = ops[0] ? ops[0][0] : 'eq';
    ops.forEach(([v, lbl]) => {
      const o = document.createElement('option');
      o.value = v; o.textContent = lbl;
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
    if (type === 'SING') return [['eq', 'equals'], ['neq', 'does not equal'], ['any_answer', 'any answer'], ['no_answer', 'no answer']];
    if (type === 'MULT') return [['contains_any', 'contains any of'], ['contains_all', 'contains all of'], ['contains_none', 'contains none of'], ['any_answer', 'any answer'], ['no_answer', 'no answer']];
    if (type === 'INT') return [['eq', '='], ['neq', '≠'], ['lt', '<'], ['lte', '≤'], ['gt', '>'], ['gte', '≥'], ['any_answer', 'any answer'], ['no_answer', 'no answer']];
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
      sel.addEventListener('change', (ev) => { cond.value_option_id = ev.target.value; onChange(); });
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
      inp.addEventListener('input', (ev) => { cond.value_number = ev.target.value === '' ? null : Number(ev.target.value); onChange(); });
      host.appendChild(inp);
      return;
    }
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.value = cond.value_text || '';
    inp.addEventListener('input', (ev) => { cond.value_text = ev.target.value; onChange(); });
    host.appendChild(inp);
  }

  // ---------- Right rail: questionnaires + recommendations ----------

  function renderRightRail() {
    renderAddQuestionnaireSelect();
    renderLoadedQuestionnaires();
    renderRecommendationsList();
  }

  function renderAddQuestionnaireSelect() {
    els.addQSelect.innerHTML = '';
    const def = state.pathway.definition;
    const loadedIds = new Set((def.loaded_questionnaires || []).map((q) => q.questionnaire_id));
    const ph = document.createElement('option');
    ph.value = '';
    ph.textContent = '— Pick a questionnaire —';
    els.addQSelect.appendChild(ph);
    state.questionnaires.forEach((q) => {
      if (loadedIds.has(q.id)) return;
      const o = document.createElement('option');
      o.value = q.id;
      o.textContent = q.name + (q.code ? ' (' + q.code + ')' : '');
      els.addQSelect.appendChild(o);
    });
    els.addQSelect.value = '';
    els.addQBtn.disabled = els.addQSelect.options.length <= 1;
  }

  function renderLoadedQuestionnaires() {
    els.loadedQ.innerHTML = '';
    const def = state.pathway.definition;
    const loaded = def.loaded_questionnaires || [];
    if (!loaded.length) {
      const empty = document.createElement('div');
      empty.className = 'rail-list';
      const li = document.createElement('div');
      li.className = 'empty-message';
      li.textContent = 'No questionnaires loaded yet.';
      empty.appendChild(li);
      els.loadedQ.appendChild(empty);
      return;
    }
    loaded.forEach((lq) => {
      const detail = state.questionnaireDetails[lq.questionnaire_id];
      const card = document.createElement('div');
      card.className = 'loaded-questionnaire';

      const header = document.createElement('div');
      header.className = 'loaded-questionnaire-header';
      const name = document.createElement('span');
      name.className = 'name';
      name.textContent = lq.questionnaire_name_snapshot || (detail ? detail.name : '(loading…)');
      header.appendChild(name);
      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'ghost small';
      removeBtn.textContent = '×';
      removeBtn.title = 'Remove from rail';
      removeBtn.addEventListener('click', () => removeLoadedQuestionnaire(lq.questionnaire_id));
      header.appendChild(removeBtn);
      card.appendChild(header);

      const qList = document.createElement('ul');
      qList.className = 'loaded-questionnaire-questions';
      if (detail && detail.questions) {
        detail.questions.forEach((q) => {
          const li = document.createElement('li');
          const text = document.createElement('span');
          text.className = 'q-text';
          text.textContent = q.name;
          text.title = q.name;
          const addBtn = document.createElement('button');
          addBtn.type = 'button';
          addBtn.className = 'ghost small';
          addBtn.textContent = '+';
          addBtn.title = 'Add as step';
          addBtn.addEventListener('click', () => addStepFromQuestion(lq, detail, q));
          li.appendChild(addBtn);
          li.appendChild(text);
          qList.appendChild(li);
        });
      } else {
        const li = document.createElement('li');
        li.className = 'empty-message';
        li.textContent = 'Loading questions…';
        qList.appendChild(li);
      }
      card.appendChild(qList);
      els.loadedQ.appendChild(card);
    });
  }

  async function addQuestionnaireFromSelect() {
    const id = els.addQSelect.value;
    if (!id) return;
    const detail = await getQuestionnaireDetail(id);
    const def = state.pathway.definition;
    def.loaded_questionnaires = def.loaded_questionnaires || [];
    if (!def.loaded_questionnaires.find((lq) => lq.questionnaire_id === id)) {
      def.loaded_questionnaires.push({
        questionnaire_id: id,
        questionnaire_name_snapshot: detail ? detail.name : '',
      });
    }
    savePathway();
    renderEditor();
  }

  function removeLoadedQuestionnaire(questionnaire_id) {
    if (!confirm('Remove this questionnaire from the rail? Any steps using its questions stay but lose their snapshot.')) return;
    const def = state.pathway.definition;
    def.loaded_questionnaires = (def.loaded_questionnaires || []).filter(
      (lq) => lq.questionnaire_id !== questionnaire_id,
    );
    savePathway();
    renderEditor();
  }

  function addStepFromQuestion(loaded, detail, question) {
    const def = state.pathway.definition;
    def.steps = def.steps || [];
    // Auto-create one rule with one condition that references this step's
    // own question. Users can fill in the operator and value (and route) —
    // no separate "Add rule" click needed.
    def.steps.push({
      step_id: newStepId(),
      questionnaire_id: loaded.questionnaire_id,
      questionnaire_name_snapshot: detail.name || loaded.questionnaire_name_snapshot || '',
      question_id: question.id,
      question_name_snapshot: question.name || '',
      rules: [
        {
          rule_id: newRuleId(),
          conditions: [
            {
              question_id: question.id,
              operator: 'eq',
              value_option_id: '',
              value_option_ids: [],
              value_text: '',
              value_number: null,
            },
          ],
          then: null,
        },
      ],
      otherwise: null,
    });
    savePathway();
    renderEditor();
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
    recs.forEach((r) => {
      const li = document.createElement('li');
      li.className = 'recommendation-item';
      const text = document.createElement('span');
      text.className = 'item-text';
      text.textContent = r.name || '(unnamed recommendation)';
      const meta = document.createElement('span');
      meta.className = 'item-meta';
      if (r.params && r.params.severity) meta.textContent = r.params.severity;
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

    const cmd = state.terminalCommands.find((c) => c.key === rec.command_key) || state.terminalCommands[0];
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
        input.rows = 3; input.value = v;
      } else if (field.type === 'select') {
        input = document.createElement('select');
        (field.options || []).forEach((opt) => {
          const o = document.createElement('option');
          o.value = opt.value; o.textContent = opt.label;
          input.appendChild(o);
        });
        input.value = v;
      } else {
        input = document.createElement('input');
        input.type = 'text'; input.value = v;
      }
      const evt = field.type === 'select' ? 'change' : 'input';
      input.addEventListener(evt, (ev) => {
        rec.params[field.key] = ev.target.value;
        // Title doubles as the rail label, so keep rec.name in sync.
        if (field.key === 'title') rec.name = ev.target.value;
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
      params: { title: 'New recommendation' },
    };
    state.pathway.definition.recommendations = state.pathway.definition.recommendations || [];
    state.pathway.definition.recommendations.push(rec);
    savePathway();
    renderEditor();
    openRecommendationModal(rec.recommendation_id);
  }

  function deleteCurrentRecommendation() {
    const recId = state.editingRecommendationId;
    if (!recId) return;
    if (!confirm('Delete this recommendation? Any rules pointing to it will lose their target.')) return;
    const def = state.pathway.definition;
    def.recommendations = (def.recommendations || []).filter((r) => r.recommendation_id !== recId);
    (def.steps || []).forEach((s) => {
      if (s.otherwise && s.otherwise.type === 'recommendation' && s.otherwise.target_id === recId) {
        s.otherwise = null;
      }
      (s.rules || []).forEach((r) => {
        if (r.then && r.then.type === 'recommendation' && r.then.target_id === recId) {
          r.then = null;
        }
      });
    });
    savePathway();
    closeRecommendationModal();
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
  els.addQBtn.addEventListener('click', addQuestionnaireFromSelect);
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
      try { const parsed = JSON.parse(err.message); issues = parsed.issues || []; } catch (_) {}
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
    if (!issues.length) { els.validation.classList.add('hidden'); return; }
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
