"""Form-based admin template builder (served by GET /admin/ui).

Staff build/edit the group therapy templates entirely through form
controls - template + section CRUD, a shared/per-patient toggle, a type
dropdown, and a questionnaire picker. The JSON config document is the storage
format only; it is never shown to or edited by a user. The form loads the
config from GET /admin/config, the questionnaire list from
GET /admin/questionnaires, and saves via POST /admin/config.
"""


def build_admin_html() -> str:
    """Return the full HTML page for the admin template builder."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Group Therapy Setup</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Round" rel="stylesheet">
    <style>
        :root {
            --bg-page: #f5f6f8; --bg-2: #eef2f6; --bg-3: #e8edf3;
            --text-heading: #111827; --text-body: #1f2933; --text-muted: #6b7280; --text-label: #475569;
            --primary: #2185D0; --primary-hover: #1a6aae; --teal: #4a9fe0; --accent: #d97706;
            --line: #e5e7eb; --radius-lg: 14px; --radius-md: 10px; --radius-full: 9999px;
            --shadow-card: 0 1px 2px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06);
            --font: 'Lato', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; -webkit-font-smoothing: antialiased; }
        body { font-family: var(--font); color: var(--text-body); min-height: 100vh; font-size: 14px; line-height: 1.5;
            background: radial-gradient(1100px 520px at 88% -8%, var(--bg-3), rgba(232,237,243,0) 60%), var(--bg-page); }
        .wrap { max-width: 920px; margin: 0 auto; padding: 3rem 2rem 6rem; }
        h1 { font-weight: 900; font-size: 26px; color: var(--text-heading); letter-spacing: -0.02em; }
        .sub { color: var(--text-muted); margin-bottom: 1.5rem; }
        .label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-label); margin-bottom: 5px; display: block; }
        input, select { font-family: var(--font); font-size: 14px; color: var(--text-body); }
        .inp, .sel { width: 100%; background: #fff; border: 1px solid #e2e8f0; border-radius: var(--radius-md); padding: 9px 12px; }
        .inp:focus, .sel:focus { outline: none; border-color: var(--teal); box-shadow: 0 0 0 3px rgba(33,133,208,0.15); }
        .topbar { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 22px; }
        .topbar .grow { flex: 1; }
        .tmpl { background: #fff; border: 1px solid var(--line); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); margin-bottom: 18px; overflow: hidden; }
        .tmpl-head { display: grid; grid-template-columns: 1fr 1fr 120px auto; gap: 12px; align-items: end; padding: 16px 18px; background: #fafbfc; border-bottom: 1px solid var(--line); }
        .sections { padding: 12px 18px 18px; }
        .sec-row { display: grid; grid-template-columns: 1fr 150px 160px 1fr auto; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid #f1f5f9; }
        .sec-row:last-child { border-bottom: none; }
        .sec-head { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); }
        .icon-btn { background: none; border: none; color: var(--text-muted); cursor: pointer; padding: 4px; border-radius: 6px; display: inline-flex; }
        .icon-btn:hover { background: #eef2f6; color: var(--primary); }
        .icon-btn.danger:hover { background: #fdecec; color: #c0392b; }
        .btn { padding: 9px 16px; border-radius: 10px; font-weight: 800; font-size: 13px; cursor: pointer; border: none; font-family: var(--font); }
        .btn-primary { background: var(--primary); color: #fff; }
        .btn-primary:hover { background: var(--primary-hover); }
        .btn-ghost { background: #fff; color: var(--primary); border: 1px dashed #bcd6ee; width: 100%; padding: 12px; }
        .btn-ghost:hover { background: #eef5fc; }
        .addsec { background: #eef5fc; color: var(--primary); border: none; font-weight: 700; font-size: 12px; padding: 7px 12px; border-radius: var(--radius-full); cursor: pointer; margin-top: 10px; }
        /* controls sit bottom-LEFT (Save first) so they clear the Canvas chat widget (bottom-right) */
        .footer { position: fixed; bottom: 0; left: 0; right: 0; background: #fff; border-top: 1px solid var(--line); padding: 14px 2rem; display: flex; justify-content: flex-start; gap: 14px; align-items: center; z-index: 60; }
        .saved { color: #1a7f4b; font-weight: 700; font-size: 13px; }
        .muted { color: var(--text-muted); font-size: 12px; }
    </style>
</head>
<body>
    <div class="wrap">
        <h1>Group Therapy Setup</h1>
        <p class="sub">Build the note templates documenters use. Set whether each section is shared across the group or unique per patient, and map it to a questionnaire or free text.</p>
        <div class="topbar">
            <div style="width:260px;">
                <span class="label">Billing mode</span>
                <select class="sel" id="billing-mode" onchange="setBilling(this.value)">
                    <option value="per_participant">Per participant</option>
                    <option value="group">Group (one CPT line per session)</option>
                </select>
            </div>
        </div>
        <div id="templates"></div>
        <button class="btn-ghost" onclick="addTemplate()"><span class="material-icons-round" style="font-size:16px;vertical-align:middle;">add</span> Add template</button>
    </div>
    <div class="footer">
        <button class="btn btn-primary" onclick="save()">Save templates</button>
        <span class="muted" id="status"></span>
    </div>
    <script>
        const BASE = '/plugin-io/api/group_therapy';
        const TYPES = [['free_text','Free text'],['options','Multiple choice'],['questionnaire','Questionnaire'],['diagnosis','Diagnosis'],['billing','Billing'],['medications','Medications (read-only)']];
        let config = { billing_mode: 'per_participant', templates: [] };
        let QLIST = [];

        function esc(s) { return (s == null ? '' : String(s)).split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;').split('"').join('&quot;').split("'").join('&#39;'); }

        async function load() {
            try { config = (await (await fetch(BASE + '/admin/config')).json()).config || config; } catch (e) {}
            try { QLIST = (await (await fetch(BASE + '/admin/questionnaires')).json()).questionnaires || []; } catch (e) {}
            if (!config.billing_mode) config.billing_mode = 'per_participant';
            if (!Array.isArray(config.templates)) config.templates = [];
            document.getElementById('billing-mode').value = config.billing_mode;
            render();
        }
        document.addEventListener('DOMContentLoaded', load);

        function setBilling(v) { config.billing_mode = v; }
        function setStatus(t, ok) { const s = document.getElementById('status'); s.textContent = t; s.className = ok ? 'saved' : 'muted'; }

        function addTemplate() { config.templates.push({ name: 'New template', rfv_codes: [], cpt_code: '', sections: [] }); render(); }
        function removeTemplate(ti) { config.templates.splice(ti, 1); render(); }
        function tplField(ti, field, value) {
            if (field === 'rfv_codes') config.templates[ti].rfv_codes = value.split(',').map(c => c.trim()).filter(Boolean);
            else config.templates[ti][field] = value;
        }
        function addSection(ti) { config.templates[ti].sections.push({ label: 'New section', scope: 'per_patient', type: 'free_text', code: '' }); render(); }
        function removeSection(ti, si) { config.templates[ti].sections.splice(si, 1); render(); }
        function moveSection(ti, si, dir) {
            const arr = config.templates[ti].sections; const ni = si + dir;
            if (ni < 0 || ni >= arr.length) return;
            const tmp = arr[si]; arr[si] = arr[ni]; arr[ni] = tmp; render();
        }
        function secField(ti, si, field, value, rerender) {
            const sec = config.templates[ti].sections[si];
            if (field === 'choices') sec.choices = value.split(',').map(c => c.trim()).filter(Boolean);
            else if (field === 'multi') sec.multi = (value === 'multi' || value === true);
            else sec[field] = value;
            if (rerender) render();
        }

        function qOptions(selected) {
            let opts = '<option value="">Select questionnaire...</option>';
            QLIST.forEach(q => { opts += '<option value="' + esc(q.code) + '"' + (q.code === selected ? ' selected' : '') + '>' + esc(q.name + ' (' + (q.use_case || '') + ' / ' + q.code + ')') + '</option>'; });
            return opts;
        }
        function typeOptions(selected) {
            return TYPES.map(t => '<option value="' + t[0] + '"' + (t[0] === selected ? ' selected' : '') + '>' + t[1] + '</option>').join('');
        }

        function render() {
            const host = document.getElementById('templates');
            host.innerHTML = config.templates.map((t, ti) => {
                const sectionsHtml = (t.sections || []).map((s, si) => {
                    let detail;
                    if (s.type === 'questionnaire') {
                        detail = '<select class="sel" onchange="secField(' + ti + ',' + si + ',\\'code\\',this.value)">' + qOptions(s.code) + '</select>';
                    } else if (s.type === 'options') {
                        detail = '<span style="display:flex;gap:6px;align-items:center;">'
                            + '<input class="inp" style="flex:1;" value="' + esc((s.choices || []).join(', ')) + '" oninput="secField(' + ti + ',' + si + ',\\'choices\\',this.value)" placeholder="Engaged, Supportive, ...">'
                            + '<select class="sel" style="width:92px;" onchange="secField(' + ti + ',' + si + ',\\'multi\\',this.value)"><option value="single"' + (s.multi ? '' : ' selected') + '>Single</option><option value="multi"' + (s.multi ? ' selected' : '') + '>Multi</option></select></span>';
                    } else {
                        detail = '<span class="muted">' + (s.type === 'free_text' ? 'shows in group therapy note' : '') + '</span>';
                    }
                    return '<div class="sec-row">'
                        + '<input class="inp" value="' + esc(s.label) + '" oninput="secField(' + ti + ',' + si + ',\\'label\\',this.value)">'
                        + '<select class="sel" onchange="secField(' + ti + ',' + si + ',\\'scope\\',this.value)"><option value="shared"' + (s.scope === 'shared' ? ' selected' : '') + '>Shared</option><option value="per_patient"' + (s.scope !== 'shared' ? ' selected' : '') + '>Per patient</option></select>'
                        + '<select class="sel" onchange="secField(' + ti + ',' + si + ',\\'type\\',this.value,true)">' + typeOptions(s.type) + '</select>'
                        + detail
                        + '<span style="white-space:nowrap;">'
                        + '<button class="icon-btn" title="Move up" onclick="moveSection(' + ti + ',' + si + ',-1)"><span class="material-icons-round" style="font-size:18px;">arrow_upward</span></button>'
                        + '<button class="icon-btn" title="Move down" onclick="moveSection(' + ti + ',' + si + ',1)"><span class="material-icons-round" style="font-size:18px;">arrow_downward</span></button>'
                        + '<button class="icon-btn danger" title="Remove" onclick="removeSection(' + ti + ',' + si + ')"><span class="material-icons-round" style="font-size:18px;">close</span></button>'
                        + '</span></div>';
                }).join('');
                return '<div class="tmpl"><div class="tmpl-head">'
                    + '<div><span class="label">Template name</span><input class="inp" value="' + esc(t.name) + '" oninput="tplField(' + ti + ',\\'name\\',this.value)"></div>'
                    + '<div><span class="label">Reason-for-visit code(s)</span><input class="inp" value="' + esc((t.rfv_codes || []).join(', ')) + '" oninput="tplField(' + ti + ',\\'rfv_codes\\',this.value)" placeholder="Group_Therapy"></div>'
                    + '<div><span class="label">CPT</span><input class="inp" value="' + esc(t.cpt_code || '') + '" oninput="tplField(' + ti + ',\\'cpt_code\\',this.value)" placeholder="90853"></div>'
                    + '<button class="icon-btn danger" title="Remove template" onclick="removeTemplate(' + ti + ')"><span class="material-icons-round">delete</span></button>'
                    + '</div><div class="sections">'
                    + '<div class="sec-row"><span class="sec-head">Section</span><span class="sec-head">Scope</span><span class="sec-head">Type</span><span class="sec-head">Questionnaire</span><span></span></div>'
                    + sectionsHtml
                    + '<button class="addsec" onclick="addSection(' + ti + ')">+ Add section</button>'
                    + '</div></div>';
            }).join('');
        }

        async function save() {
            setStatus('Saving...', false);
            try {
                const resp = await fetch(BASE + '/admin/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ config }) });
                const data = await resp.json();
                setStatus(data.success ? 'Saved' : ('Error: ' + (data.error || 'could not save')), !!data.success);
            } catch (e) { setStatus('Error saving', false); }
        }
    </script>
</body>
</html>"""
