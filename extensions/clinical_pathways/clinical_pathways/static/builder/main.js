(function () {
  'use strict';

  const apiBase = document.body.dataset.apiBase;
  // Boot marker — verifiable from devtools console to confirm the new bundle
  // is loaded (cache-bust hand-check).
  console.log('clinical_pathways builder v0.2.4 loaded');

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
    rootPickerHost: document.getElementById('root-picker-host'),
    treeHost: document.getElementById('tree-host'),
    validation: document.getElementById('validation-issues'),
    validationList: document.getElementById('validation-list'),
    saveStatus: document.getElementById('save-status'),
  };

  const state = {
    pathway: null, // {dbid, title, description, status, definition: {version, root}}
    questionnaires: [], // typeahead cache: [{id, name, code}]
    questionnaireDetails: {}, // id -> {questions: [{id, name, response_set_type, options}]}
    terminalCommands: [], // [{key, schema_key, name, fields}]
  };

  // ---------- Status pill ----------

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

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), ms);
    };
  }

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
    if (_saveTimer) {
      clearTimeout(_saveTimer);
      _saveTimer = null;
    }
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
      // Critical: do NOT assign `state.pathway = serverResponse` here. Every
      // DOM closure (terminal editor, condition rows, radio handlers) holds
      // direct references into the pathway tree; replacing the root object
      // would detach them, causing the very next keystroke or click to land
      // on an orphan and silently lose data.
      flashStatus('Saved');
      await reloadList();
    } catch (_) {
      /* flashStatus already shown */
    }
  }
  // Backward-compatible alias used throughout the file.
  const savePathway = scheduleSave;

  // ---------- ID helpers (local) ----------

  function newNodeId() {
    return 'n_' + Math.random().toString(36).slice(2, 12);
  }
  function newBranchId() {
    return 'b_' + Math.random().toString(36).slice(2, 12);
  }

  // ---------- List + load + create + delete ----------

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
    state.pathway = await api('/pathways/' + dbid);
    renderEditor();
    await reloadList();
  }

  async function createPathway() {
    const pw = await api('/pathways', { method: 'POST', body: { title: 'Untitled pathway' } });
    state.pathway = pw;
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

  // ---------- Editor render ----------

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
    renderRootPicker();
    renderTree();
    els.validation.classList.add('hidden');
  }

  // ---------- Root picker ----------

  async function renderRootPicker() {
    els.rootPickerHost.innerHTML = '';
    const def = state.pathway.definition || { version: 1, root: null };
    const wrap = document.createElement('div');
    const select = document.createElement('select');
    select.id = 'root-questionnaire-select';
    wrap.appendChild(select);

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '— Choose a starting questionnaire —';
    select.appendChild(placeholder);

    // Pre-populate with the currently-selected questionnaire's snapshot so it
    // shows even if the typeahead cache hasn't loaded it yet.
    const currentId = def.root && def.root.questionnaire_id;
    if (currentId) {
      const opt = document.createElement('option');
      opt.value = currentId;
      opt.selected = true;
      opt.textContent = (def.root.questionnaire_name_snapshot || 'Selected') + ' (' + currentId.slice(0, 8) + '…)';
      select.appendChild(opt);
    }

    await searchQuestionnaires('');
    state.questionnaires.forEach((q) => {
      if (currentId && q.id === currentId) return; // already added
      const opt = document.createElement('option');
      opt.value = q.id;
      opt.textContent = q.name + (q.code ? ' (' + q.code + ')' : '');
      select.appendChild(opt);
    });

    select.addEventListener('change', async (ev) => {
      const id = ev.target.value;
      if (!id) {
        state.pathway.definition.root = null;
        savePathway();
        renderTree();
        return;
      }
      const detail = await getQuestionnaireDetail(id);
      state.pathway.definition.root = {
        node_id: (def.root && def.root.node_id) || newNodeId(),
        type: 'questionnaire',
        questionnaire_id: id,
        questionnaire_name_snapshot: detail.name,
        match_mode: 'first',
        branches: (def.root && def.root.branches) || [],
      };
      savePathway();
      renderTree();
    });

    els.rootPickerHost.appendChild(wrap);
  }

  // ---------- Tree ----------

  function renderTree() {
    els.treeHost.innerHTML = '';
    const root = state.pathway.definition && state.pathway.definition.root;
    if (!root) {
      const empty = document.createElement('div');
      empty.className = 'hint';
      empty.textContent = 'Pick a starting questionnaire above to begin defining branches.';
      els.treeHost.appendChild(empty);
      return;
    }
    const tree = renderNode(root, /*ancestors*/ []);
    els.treeHost.appendChild(tree);
  }

  function renderNode(node, ancestors) {
    if (node.type === 'terminal') return renderTerminalNode(node, ancestors);
    const el = document.createElement('div');
    el.className = 'node';
    el.dataset.nodeId = node.node_id;

    const header = document.createElement('div');
    header.className = 'node-header';
    const badge = document.createElement('span');
    badge.className = 'node-type-badge';
    badge.textContent = 'Questionnaire';
    header.appendChild(badge);
    const title = document.createElement('div');
    title.className = 'node-title';
    title.textContent = node.questionnaire_name_snapshot || '(no questionnaire selected)';
    header.appendChild(title);
    el.appendChild(header);

    const hint = document.createElement('div');
    hint.className = 'node-auto-insert-hint';
    hint.textContent = 'Auto-inserts into the note when the pathway reaches this step.';
    el.appendChild(hint);

    // Branches
    const branchesSection = document.createElement('div');
    branchesSection.className = 'branches-section';
    const label = document.createElement('div');
    label.className = 'branches-label';
    label.textContent = 'Branches (top to bottom, first match wins)';
    branchesSection.appendChild(label);

    (node.branches || []).forEach((b, idx) => {
      branchesSection.appendChild(renderBranch(node, b, idx, ancestors));
    });

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'secondary small';
    addBtn.textContent = '+ Add branch';
    addBtn.addEventListener('click', () => {
      const newBranch = {
        branch_id: newBranchId(),
        label: '',
        when: { kind: 'group', combinator: 'all', children: [] },
        then: null,
      };
      node.branches = node.branches || [];
      node.branches.push(newBranch);
      savePathway();
      renderTree();
    });
    branchesSection.appendChild(addBtn);

    el.appendChild(branchesSection);
    return el;
  }

  function renderTerminalNode(node, ancestors) {
    const el = document.createElement('div');
    el.className = 'node terminal';
    el.dataset.nodeId = node.node_id;

    const header = document.createElement('div');
    header.className = 'node-header';
    const badge = document.createElement('span');
    badge.className = 'node-type-badge';
    badge.textContent = 'Terminal';
    header.appendChild(badge);
    const title = document.createElement('div');
    title.className = 'node-title';
    const cmd = state.terminalCommands.find((c) => c.key === node.command_key);
    title.textContent = cmd ? cmd.name : '(pick a command)';
    header.appendChild(title);
    el.appendChild(header);

    const hint = document.createElement('div');
    hint.className = 'node-auto-insert-hint';
    hint.textContent = 'Inserts as the leaf command on this arm.';
    el.appendChild(hint);

    el.appendChild(renderTerminalEditor(node, ancestors));
    return el;
  }

  function renderBranch(parentNode, branch, idx, ancestors) {
    const el = document.createElement('div');
    el.className = 'branch';
    el.dataset.branchId = branch.branch_id;

    const header = document.createElement('div');
    header.className = 'branch-header';
    const lbl = document.createElement('strong');
    lbl.textContent = 'Branch ' + (idx + 1);
    header.appendChild(lbl);
    const labelInput = document.createElement('input');
    labelInput.type = 'text';
    labelInput.className = 'branch-label-input';
    labelInput.placeholder = 'Branch label (optional)';
    labelInput.value = branch.label || '';
    labelInput.addEventListener('input', (ev) => {
      branch.label = ev.target.value;
      savePathway();
    });
    header.appendChild(labelInput);

    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'ghost small';
    delBtn.textContent = '×';
    delBtn.title = 'Delete branch';
    delBtn.addEventListener('click', () => {
      if (!confirm('Delete this branch?')) return;
      parentNode.branches.splice(idx, 1);
      savePathway();
      renderTree();
    });
    header.appendChild(delBtn);
    el.appendChild(header);

    // When
    const whenSec = document.createElement('div');
    whenSec.className = 'branch-section';
    const whenH = document.createElement('h4');
    whenH.textContent = 'When';
    whenSec.appendChild(whenH);
    const ctx = collectQuestionnaireContext(parentNode, ancestors);
    whenSec.appendChild(
      renderCondition(branch.when || { kind: 'group', combinator: 'all', children: [] }, ctx, /*depth*/ 1, (newWhen, shouldRerender) => {
        branch.when = newWhen;
        savePathway();
        if (shouldRerender) renderTree();
      })
    );
    el.appendChild(whenSec);

    // Then
    const thenSec = document.createElement('div');
    thenSec.className = 'branch-section';
    const thenH = document.createElement('h4');
    thenH.textContent = 'Then';
    thenSec.appendChild(thenH);
    thenSec.appendChild(renderThenPicker(branch, ancestors.concat([parentNode])));
    el.appendChild(thenSec);

    return el;
  }

  function collectQuestionnaireContext(node, ancestors) {
    // Returns [{id, name}] of questionnaires whose questions are available to
    // condition on at this point in the tree: the current node + all ancestors.
    const out = [];
    const seen = new Set();
    [node, ...ancestors].forEach((n) => {
      if (n && n.type === 'questionnaire' && n.questionnaire_id && !seen.has(n.questionnaire_id)) {
        seen.add(n.questionnaire_id);
        out.push({ id: n.questionnaire_id, name: n.questionnaire_name_snapshot || '(unknown)' });
      }
    });
    return out;
  }

  // ---------- Then picker ----------

  function renderThenPicker(branch, ancestorsIncludingParent) {
    const wrap = document.createElement('div');
    const then = branch.then;
    const currentType = then ? then.type : null;

    const picker = document.createElement('div');
    picker.className = 'then-picker';

    const optQ = document.createElement('label');
    const rQ = document.createElement('input');
    rQ.type = 'radio';
    rQ.name = 'then-' + branch.branch_id;
    rQ.checked = currentType === 'questionnaire';
    rQ.addEventListener('change', () => {
      // Guard: only reset the subtree when the user is actually switching
      // type. Re-clicking the already-selected radio must not wipe data.
      if (branch.then && branch.then.type === 'questionnaire') return;
      branch.then = {
        node_id: newNodeId(),
        type: 'questionnaire',
        questionnaire_id: '',
        questionnaire_name_snapshot: '',
        match_mode: 'first',
        branches: [],
      };
      savePathway();
      renderTree();
    });
    optQ.appendChild(rQ);
    optQ.appendChild(document.createTextNode('Continue to questionnaire'));
    picker.appendChild(optQ);

    const optT = document.createElement('label');
    const rT = document.createElement('input');
    rT.type = 'radio';
    rT.name = 'then-' + branch.branch_id;
    rT.checked = currentType === 'terminal';
    rT.addEventListener('change', async () => {
      if (branch.then && branch.then.type === 'terminal') return;
      await loadTerminalCommands();
      const first = state.terminalCommands[0];
      branch.then = {
        node_id: newNodeId(),
        type: 'terminal',
        command_key: first ? first.key : '',
        params: {},
      };
      savePathway();
      renderTree();
    });
    optT.appendChild(rT);
    optT.appendChild(document.createTextNode('End pathway with custom command'));
    picker.appendChild(optT);

    wrap.appendChild(picker);

    if (currentType === 'questionnaire') {
      wrap.appendChild(renderNestedQuestionnairePicker(branch.then, ancestorsIncludingParent));
      // After the nested picker, recursively render the subtree node so the
      // user can add deeper branches.
      wrap.appendChild(renderNode(branch.then, ancestorsIncludingParent));
    } else if (currentType === 'terminal') {
      wrap.appendChild(renderTerminalNode(branch.then, ancestorsIncludingParent));
    } else {
      const hint = document.createElement('div');
      hint.className = 'hint';
      hint.textContent = 'Choose where this branch leads.';
      wrap.appendChild(hint);
    }
    return wrap;
  }

  function renderNestedQuestionnairePicker(node, ancestors) {
    const wrap = document.createElement('div');
    wrap.className = 'block';
    const lbl = document.createElement('div');
    lbl.className = 'field-label';
    lbl.textContent = 'Questionnaire';
    wrap.appendChild(lbl);
    const select = document.createElement('select');

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '— Choose a questionnaire —';
    select.appendChild(placeholder);

    if (node.questionnaire_id) {
      const opt = document.createElement('option');
      opt.value = node.questionnaire_id;
      opt.selected = true;
      opt.textContent = (node.questionnaire_name_snapshot || 'Selected') + ' (' + node.questionnaire_id.slice(0, 8) + '…)';
      select.appendChild(opt);
    }
    state.questionnaires.forEach((q) => {
      if (q.id === node.questionnaire_id) return;
      const opt = document.createElement('option');
      opt.value = q.id;
      opt.textContent = q.name + (q.code ? ' (' + q.code + ')' : '');
      select.appendChild(opt);
    });
    select.addEventListener('change', async (ev) => {
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
      renderTree();
    });
    wrap.appendChild(select);
    return wrap;
  }

  // ---------- Condition builder ----------

  function renderCondition(cond, contextQuestionnaires, depth, onChange) {
    if (!cond || cond.kind !== 'group') {
      cond = { kind: 'group', combinator: 'all', children: [] };
      onChange(cond);
    }
    const group = document.createElement('div');
    group.className = 'condition-group depth-' + depth;

    const headerRow = document.createElement('div');
    headerRow.className = 'group-header';
    const combSel = document.createElement('select');
    [['all', 'ALL of'], ['any', 'ANY of'], ['none', 'NONE of']].forEach(([v, lbl]) => {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = lbl;
      if (cond.combinator === v) opt.selected = true;
      combSel.appendChild(opt);
    });
    combSel.addEventListener('change', (ev) => {
      cond.combinator = ev.target.value;
      onChange(cond);
    });
    headerRow.appendChild(combSel);
    group.appendChild(headerRow);

    (cond.children || []).forEach((child, idx) => {
      if (child.kind === 'group') {
        group.appendChild(
          renderCondition(child, contextQuestionnaires, depth + 1, (updated, shouldRerender) => {
            cond.children[idx] = updated;
            onChange(cond, shouldRerender);
          })
        );
      } else {
        group.appendChild(renderComparison(child, contextQuestionnaires, (updated) => {
          if (updated === null) {
            cond.children.splice(idx, 1);
            onChange(cond, true);
          } else {
            cond.children[idx] = updated;
            onChange(cond, false);
          }
        }));
      }
    });

    const actions = document.createElement('div');
    actions.className = 'condition-actions';
    const addCompBtn = document.createElement('button');
    addCompBtn.type = 'button';
    addCompBtn.className = 'ghost small';
    addCompBtn.textContent = '+ condition';
    addCompBtn.addEventListener('click', () => {
      cond.children = cond.children || [];
      cond.children.push({
        kind: 'comparison',
        questionnaire_id: contextQuestionnaires[0] ? contextQuestionnaires[0].id : '',
        question_id: '',
        operator: 'eq',
        value_option_id: '',
        value_text: '',
      });
      onChange(cond, true);
    });
    actions.appendChild(addCompBtn);
    const addGroupBtn = document.createElement('button');
    addGroupBtn.type = 'button';
    addGroupBtn.className = 'ghost small';
    addGroupBtn.textContent = '+ nested group';
    addGroupBtn.addEventListener('click', () => {
      cond.children = cond.children || [];
      cond.children.push({ kind: 'group', combinator: 'all', children: [] });
      onChange(cond, true);
    });
    actions.appendChild(addGroupBtn);
    group.appendChild(actions);

    return group;
  }

  function renderComparison(comp, contextQuestionnaires, onChange) {
    const row = document.createElement('div');
    row.className = 'comparison';

    // Questionnaire dropdown
    const qSel = document.createElement('select');
    qSel.className = 'questionnaire-select';
    contextQuestionnaires.forEach((q) => {
      const opt = document.createElement('option');
      opt.value = q.id;
      opt.textContent = q.name;
      qSel.appendChild(opt);
    });
    qSel.value = comp.questionnaire_id || '';
    qSel.addEventListener('change', async (ev) => {
      comp.questionnaire_id = ev.target.value;
      comp.question_id = '';
      onChange(comp);
    });
    row.appendChild(qSel);

    // Question dropdown — populated asynchronously
    const questionSel = document.createElement('select');
    questionSel.className = 'question-select';
    const ph = document.createElement('option');
    ph.value = '';
    ph.textContent = '— question —';
    questionSel.appendChild(ph);
    row.appendChild(questionSel);

    // Operator dropdown
    const opSel = document.createElement('select');
    row.appendChild(opSel);

    // Value cell (input/select/etc — type-aware)
    const valueCell = document.createElement('span');
    valueCell.className = 'value-cell';
    row.appendChild(valueCell);

    // Delete
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'ghost small delete-comparison';
    del.textContent = '×';
    del.addEventListener('click', () => onChange(null));
    row.appendChild(del);

    // Hydrate the question + operator + value asynchronously
    (async () => {
      if (!comp.questionnaire_id) return;
      const detail = await getQuestionnaireDetail(comp.questionnaire_id);
      detail.questions.forEach((q) => {
        const opt = document.createElement('option');
        opt.value = q.id;
        opt.textContent = q.name;
        questionSel.appendChild(opt);
      });
      questionSel.value = comp.question_id || '';
      const currentQuestion = detail.questions.find((q) => q.id === comp.question_id);
      renderOperatorAndValue(opSel, valueCell, comp, currentQuestion, onChange);

      questionSel.onchange = (ev) => {
        comp.question_id = ev.target.value;
        comp.operator = 'eq';
        comp.value_option_id = '';
        comp.value_option_ids = [];
        comp.value_text = '';
        comp.value_number = null;
        const q = detail.questions.find((qq) => qq.id === comp.question_id);
        renderOperatorAndValue(opSel, valueCell, comp, q, onChange);
        onChange(comp);
      };
    })();

    return row;
  }

  function renderOperatorAndValue(opSel, valueCell, comp, question, onChange) {
    opSel.innerHTML = '';
    valueCell.innerHTML = '';
    const type = (question && question.response_set_type) || 'TXT';

    const ops = operatorsForType(type);
    const validOpKeys = ops.map(([v]) => v);
    if (!validOpKeys.includes(comp.operator)) {
      // The persisted operator isn't valid for this question's type (e.g.,
      // the question was changed in a prior session); fall back to the first
      // operator so the dropdown shows something meaningful.
      comp.operator = ops[0] ? ops[0][0] : 'eq';
    }
    ops.forEach(([v, lbl]) => {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = lbl;
      opSel.appendChild(opt);
    });
    opSel.value = comp.operator;
    // Replace any prior change handler — opSel may be re-decorated when the
    // question changes, and we don't want duplicate listeners stacking up.
    opSel.onchange = (ev) => {
      comp.operator = ev.target.value;
      renderValueWidget(valueCell, comp, question, onChange);
      onChange(comp);
    };
    renderValueWidget(valueCell, comp, question, onChange);
  }

  function operatorsForType(type) {
    if (type === 'SING') {
      return [
        ['eq', 'equals'],
        ['neq', 'does not equal'],
        ['any_answer', 'any answer'],
        ['no_answer', 'no answer'],
      ];
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
      return [
        ['eq', '='],
        ['neq', '≠'],
        ['lt', '<'],
        ['lte', '≤'],
        ['gt', '>'],
        ['gte', '≥'],
        ['any_answer', 'any answer'],
        ['no_answer', 'no answer'],
      ];
    }
    return [
      ['eq', 'equals'],
      ['neq', 'does not equal'],
      ['contains', 'contains'],
      ['any_answer', 'any answer'],
      ['no_answer', 'no answer'],
    ];
  }

  function renderValueWidget(host, comp, question, onChange) {
    host.innerHTML = '';
    if (comp.operator === 'any_answer' || comp.operator === 'no_answer') return;
    const type = (question && question.response_set_type) || 'TXT';
    const options = (question && question.options) || [];

    if (type === 'SING') {
      console.log('clinical_pathways: renderValueWidget SING', {
        value_option_id: comp.value_option_id,
        option_ids: options.map((o) => o.id),
      });
      const sel = document.createElement('select');
      const ph = document.createElement('option');
      ph.value = '';
      ph.textContent = '— value —';
      sel.appendChild(ph);
      options.forEach((o) => {
        const opt = document.createElement('option');
        opt.value = o.id;
        opt.textContent = o.name || o.value;
        // Belt: set the `selected` attribute on the matching option.
        if (o.id === comp.value_option_id) opt.selected = true;
        sel.appendChild(opt);
      });
      // Suspenders: also set sel.value after appending.
      sel.value = comp.value_option_id || '';
      sel.addEventListener('change', (ev) => {
        comp.value_option_id = ev.target.value;
        onChange(comp);
      });
      host.appendChild(sel);
      // Microtask fallback: some browser builds re-evaluate select state on
      // DOM attachment; re-apply once the current microtask queue drains.
      queueMicrotask(() => {
        if (comp.value_option_id && sel.value !== comp.value_option_id) {
          sel.value = comp.value_option_id;
        }
      });
      return;
    }
    if (type === 'MULT') {
      const wrap = document.createElement('span');
      const ids = comp.value_option_ids || (comp.value_option_id ? [comp.value_option_id] : []);
      options.forEach((o) => {
        const lbl = document.createElement('label');
        lbl.style.marginRight = '6px';
        lbl.style.fontSize = '12px';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = ids.includes(o.id);
        cb.addEventListener('change', () => {
          const next = new Set(comp.value_option_ids || []);
          if (cb.checked) next.add(o.id);
          else next.delete(o.id);
          comp.value_option_ids = Array.from(next);
          onChange(comp);
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
      inp.value = comp.value_number != null ? comp.value_number : '';
      inp.addEventListener('input', (ev) => {
        comp.value_number = ev.target.value === '' ? null : Number(ev.target.value);
        onChange(comp);
      });
      host.appendChild(inp);
      return;
    }
    // TEXT
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.value = comp.value_text || '';
    inp.addEventListener('input', (ev) => {
      comp.value_text = ev.target.value;
      onChange(comp);
    });
    host.appendChild(inp);
  }

  // ---------- Terminal editor ----------

  function renderTerminalEditor(node, ancestors) {
    const host = document.createElement('div');
    host.className = 'terminal-editor';

    const cmdRow = document.createElement('div');
    cmdRow.className = 'terminal-field';
    const cmdLbl = document.createElement('div');
    cmdLbl.className = 'field-label';
    cmdLbl.textContent = 'Command';
    cmdRow.appendChild(cmdLbl);
    const cmdSel = document.createElement('select');
    state.terminalCommands.forEach((c) => {
      const opt = document.createElement('option');
      opt.value = c.key;
      opt.textContent = c.name;
      if (c.key === node.command_key) opt.selected = true;
      cmdSel.appendChild(opt);
    });
    cmdSel.addEventListener('change', (ev) => {
      node.command_key = ev.target.value;
      node.params = {};
      savePathway();
      renderTree();
    });
    cmdRow.appendChild(cmdSel);
    host.appendChild(cmdRow);

    const cmd = state.terminalCommands.find((c) => c.key === node.command_key);
    if (cmd) {
      cmd.fields.forEach((field) => {
        const row = document.createElement('div');
        row.className = 'terminal-field';
        const lbl = document.createElement('div');
        lbl.className = 'field-label';
        lbl.textContent = field.label + (field.required ? ' *' : '');
        row.appendChild(lbl);
        node.params = node.params || {};
        const v = node.params[field.key] != null ? node.params[field.key] : '';
        let input;
        if (field.type === 'textarea') {
          input = document.createElement('textarea');
          input.rows = 3;
        } else if (field.type === 'select') {
          input = document.createElement('select');
          (field.options || []).forEach((opt) => {
            const o = document.createElement('option');
            o.value = opt.value;
            o.textContent = opt.label;
            if (opt.value === v) o.selected = true;
            input.appendChild(o);
          });
        } else {
          input = document.createElement('input');
          input.type = 'text';
        }
        if (field.type !== 'select') input.value = v;
        input.addEventListener('input', (ev) => {
          node.params[field.key] = ev.target.value;
          savePathway();
        });
        if (field.type === 'select') {
          input.addEventListener('change', (ev) => {
            node.params[field.key] = ev.target.value;
            savePathway();
          });
        }
        row.appendChild(input);
        const hint = document.createElement('div');
        hint.className = 'field-hint';
        hint.textContent = 'Tip: use {{question_id}} to interpolate an answer from earlier in this pathway.';
        row.appendChild(hint);
        host.appendChild(row);
      });
    }
    return host;
  }

  // ---------- Top-level field handlers ----------

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

  els.publishBtn.addEventListener('click', async () => {
    if (!state.pathway || !state.pathway.dbid) return;
    // Flush any pending debounced edits so the server validates against
    // the user's latest state, not an in-flight stale version.
    await flushSave();
    try {
      const res = await api('/pathways/' + state.pathway.dbid + '/publish', {
        method: 'POST',
        body: {},
      });
      if (res.published) {
        state.pathway.status = 'published';
        flashStatus('Published');
        renderEditor();
        await reloadList();
      }
      renderValidation(res.issues || []);
    } catch (err) {
      // Try to parse JSON error body for issues
      let issues = [];
      try {
        const parsed = JSON.parse(err.message);
        issues = parsed.issues || [];
      } catch (_) {
        /* leave issues empty */
      }
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
    await loadTerminalCommands();
    await reloadList();
    renderEditor();
  })();
})();
