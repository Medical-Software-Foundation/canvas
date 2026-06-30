"""Config-driven documentation modal for Group Therapy (served by GET /ui).

The modal is template-agnostic: on session select it fetches the resolved
template from GET /template?rfv= (sections + each questionnaire section's live
question schema) and renders from it. Free-text and read-only sections render as
simple controls; questionnaire sections render their real questions live; the
diagnosis section uses the condition picker. Shared sections are filled once;
per-patient sections render per attendee. On submit each attendee posts free-text
/ medications as summary sections and questionnaire answers as {code, answers}.
"""


def _attr(value: str) -> str:
    """Escape a value for safe embedding in a double-quoted HTML attribute.
    (The plugin sandbox has no `html` module, so escape by hand.)"""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def build_modal_html(
    logged_in_staff_id: str = "",
    logged_in_name: str = "",
) -> str:
    """Return the full HTML page for the config-driven group therapy modal."""
    staff_id_attr = _attr(logged_in_staff_id)
    staff_name_attr = _attr(logged_in_name)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Group Therapy Session</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Lato:ital,wght@0,300;0,400;0,700;0,900;1,400&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Round" rel="stylesheet">
    <style>
        :root {{
            --bg-page: #f5f6f8; --bg-2: #eef2f6; --bg-3: #e8edf3; --bg-surface: #ffffff;
            --text-heading: #111827; --text-body: #1f2933; --text-label: #475569; --text-muted: #6b7280;
            --primary: #2185D0; --primary-hover: #1a6aae; --teal: #4a9fe0; --accent: #d97706;
            --line: #e5e7eb; --radius-lg: 14px; --radius-md: 10px; --radius-full: 9999px;
            --shadow-card: 0 1px 2px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06);
            --font-sans: 'Lato', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; -webkit-font-smoothing: antialiased; }}
        body {{ font-family: var(--font-sans); color: var(--text-body); height: 100vh; display: flex; overflow: hidden; font-size: 14px; line-height: 1.6;
            background: radial-gradient(1100px 520px at 88% -8%, var(--bg-3) 0%, rgba(232,237,243,0) 60%), radial-gradient(900px 480px at -6% 4%, var(--bg-2) 0%, rgba(238,242,246,0) 55%), var(--bg-page); }}
        .workspace {{ display: grid; grid-template-columns: minmax(340px, 0.85fr) minmax(480px, 1.15fr); width: 100%; height: 100%; }}
        .main-panel {{ padding: 3rem 3.25rem; overflow-y: auto; }}
        .side-panel-wrapper {{ position: relative; overflow: hidden; }}
        .side-panel {{ background: var(--bg-page); padding: 2.5rem 2rem 100px; overflow-y: auto; border-left: 1px solid rgba(0,0,0,0.04); height: 100%; }}
        .hero-title {{ font-weight: 900; font-size: 26px; color: var(--text-heading); letter-spacing: -0.02em; }}
        .hero-meta {{ color: var(--text-muted); font-size: 14px; margin-bottom: 1.5rem; }}
        .label-editorial {{ font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-label); margin-bottom: 8px; display: block; }}
        .label-mini {{ font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); margin-bottom: 4px; display: block; }}
        .input-editorial {{ width: 100%; background: var(--bg-surface); border: 1px solid #e2e8f0; border-radius: var(--radius-lg); padding: 10px 14px; font-family: var(--font-sans); font-size: 14px; color: var(--text-body); }}
        .input-editorial:focus {{ outline: none; border-color: var(--teal); box-shadow: 0 0 0 3px rgba(33,133,208,0.15); }}
        .input-editorial:disabled {{ background: #f1f5f9; color: #94a3b8; }}
        .tmpl-pill {{ display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: var(--radius-full); font-size: 11px; font-weight: 800; background: #eaf2fb; color: var(--primary-hover); margin-bottom: 18px; }}
        .meta-strip {{ display: flex; flex-wrap: wrap; gap: 10px 26px; margin-bottom: 24px; padding: 14px 18px; background: #fff; border: 1px solid var(--line); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); }}
        .meta-strip .ms-k {{ font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); display: block; }}
        .meta-strip .ms-v {{ font-size: 14px; font-weight: 800; color: var(--text-heading); }}
        .field-block {{ margin-bottom: 22px; }}
        .soap-area {{ width: 100%; background: #fff; border: 1px solid #e2e8f0; border-radius: var(--radius-lg); padding: 14px; min-height: 80px; font-family: var(--font-sans); font-size: 14px; color: var(--text-body); line-height: 1.6; resize: vertical; }}
        .soap-area:focus {{ outline: none; border-color: var(--teal); box-shadow: 0 0 0 3px rgba(33,133,208,0.15); }}
        .opt-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
        .opt-pill {{ display: inline-flex; align-items: center; gap: 6px; padding: 7px 13px; border: 1px solid #e2e8f0; border-radius: var(--radius-full); background: #fff; font-size: 12px; font-weight: 700; color: var(--text-muted); cursor: pointer; transition: all 0.15s; user-select: none; }}
        .opt-pill:hover {{ border-color: var(--teal); }}
        .opt-pill.active {{ border-color: var(--primary); background: #eaf2fb; color: var(--primary-hover); }}
        .opt-pill.locked {{ pointer-events: none; opacity: 0.55; }}
        .q-block {{ margin-bottom: 14px; }}
        .q-label {{ font-size: 12px; font-weight: 700; color: var(--text-heading); margin-bottom: 5px; display: block; }}
        .flow-footer {{ display: flex; justify-content: flex-end; gap: 16px; padding-top: 28px; border-top: 1px solid #e5e7eb; }}
        .btn-pill {{ padding: 12px 26px; border-radius: 11px; font-weight: 800; font-size: 14px; cursor: pointer; border: none; font-family: var(--font-sans); transition: .14s; }}
        .btn-pill:disabled {{ opacity: 0.5; cursor: not-allowed; }}
        .btn-primary {{ background: var(--primary); color: #fff; box-shadow: 0 2px 10px rgba(33,133,208,0.30); }}
        .btn-primary:hover:not(:disabled) {{ background: var(--primary-hover); }}
        .btn-secondary {{ background: #fff; color: var(--primary); border: 1px solid #cfe0f2; }}
        .shared-empty {{ text-align: center; padding: 4rem 1rem; color: var(--text-muted); }}
        .shared-empty .material-icons-round {{ font-size: 48px; color: #cbd5e1; display: block; margin-bottom: 12px; }}
        .sidebar-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .sidebar-header .label-editorial {{ color: var(--primary); margin: 0; }}
        .sidebar-header .count {{ font-weight: 700; font-size: 14px; color: var(--primary); }}
        .sidebar-sub {{ font-size: 12px; color: var(--text-muted); margin-bottom: 18px; }}
        .session-banner {{ display: none; align-items: center; gap: 10px; padding: 12px 14px; background: #fff; border: 1px solid var(--primary); border-radius: var(--radius-lg); margin-bottom: 14px; box-shadow: var(--shadow-card); }}
        .session-banner.show {{ display: flex; }}
        .session-banner .material-icons-round {{ color: var(--primary); }}
        .sb-prov {{ font-weight: 800; color: var(--text-heading); font-size: 14px; }}
        .sb-time {{ font-size: 12px; color: var(--text-muted); }}
        .sb-change {{ font-size: 12px; font-weight: 800; color: var(--primary); cursor: pointer; white-space: nowrap; }}
        .audit-banner {{ display: none; gap: 10px; padding: 14px 18px; background: #fff6ef; border: 1px solid #f7d7bb; border-radius: var(--radius-lg); margin-bottom: 14px; font-size: 13px; color: #92400e; }}
        .audit-banner.show {{ display: block; }}
        .audit-banner .ab-row {{ display: flex; gap: 10px; align-items: flex-start; }}
        .audit-banner .material-icons-round {{ color: var(--accent); }}
        .audit-ack {{ display: flex; align-items: center; gap: 8px; margin-top: 10px; font-weight: 700; }}
        .audit-ack input {{ width: 16px; height: 16px; accent-color: var(--accent); cursor: pointer; }}
        .audit-banner.ack .ab-row {{ display: none; }}
        .audit-banner.ack .audit-ack {{ margin-top: 0; font-weight: 400; color: var(--text-muted); }}
        .session-pick {{ margin-bottom: 18px; }}
        .session-option {{ display: flex; align-items: center; gap: 10px; padding: 12px 14px; background: #fff; border: 1px solid #e2e8f0; border-radius: var(--radius-lg); margin-bottom: 8px; cursor: pointer; }}
        .session-option:hover {{ border-color: var(--teal); }}
        .so-time {{ font-weight: 900; font-size: 15px; color: var(--text-heading); }}
        .so-meta {{ font-size: 12px; color: var(--text-muted); }}
        .so-kind {{ font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em; color: var(--accent); }}
        .so-count {{ margin-left: auto; font-size: 12px; font-weight: 700; color: var(--primary); }}
        .p-card {{ background: #fff; border-radius: var(--radius-lg); box-shadow: var(--shadow-card); margin-bottom: 12px; overflow: hidden; }}
        .p-card.locked {{ opacity: 0.6; }}
        .p-header {{ padding: 12px 16px; display: flex; align-items: center; gap: 12px; cursor: pointer; }}
        .p-avatar {{ width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 12px; background: #dce9f7; color: #2185D0; overflow: hidden; flex-shrink: 0; }}
        .p-avatar img {{ width: 100%; height: 100%; object-fit: cover; }}
        .p-info {{ flex: 1; }}
        .p-name {{ font-weight: 700; font-size: 14px; color: var(--text-heading); }}
        .p-meta {{ font-size: 12px; color: var(--text-muted); }}
        .badge-done {{ display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: var(--radius-full); background: #e7f6ee; color: #1a7f4b; font-size: 11px; font-weight: 800; white-space: nowrap; flex-shrink: 0; }}
        .badge-done .material-icons-round {{ font-size: 14px; color: #1a7f4b; }}
        .p-chevron {{ color: #cbd5e1; transition: transform 0.2s; }} .rotated {{ transform: rotate(180deg); }}
        .card-chart {{ color: var(--primary); cursor: pointer; font-size: 18px; }}
        .p-body {{ padding: 0 16px 16px; }} .p-body.collapsed {{ display: none; }}
        .locked-flag {{ display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--accent); margin-top: 6px; }}
        .locked-flag .material-icons-round {{ font-size: 15px; }}
        .checkin-pill {{ display: inline-flex; align-items: center; gap: 4px; font-size: 10px; font-weight: 700; color: var(--accent); margin-top: 6px; }}
        .checkin-pill .material-icons-round {{ font-size: 13px; }}
        .pill-toggle {{ background: #eef2f6; border-radius: var(--radius-md); padding: 4px; display: flex; gap: 2px; margin-top: 4px; }}
        .toggle-opt {{ flex: 1; text-align: center; padding: 6px; font-size: 11px; font-weight: 700; color: var(--text-muted); border-radius: 6px; cursor: pointer; }}
        .toggle-opt.active {{ background: #fff; color: var(--text-heading); box-shadow: 0 1px 2px rgba(0,0,0,0.05); }}
        .field-mini {{ margin-top: 12px; }}
        .select-mini {{ width: 100%; background: #fff; border: 1px solid #e2e8f0; border-radius: var(--radius-md); padding: 8px 10px; font-family: var(--font-sans); font-size: 12px; color: var(--text-body); }}
        .p-note {{ width: 100%; background: #fafafa; border: 1px solid #e2e8f0; border-radius: var(--radius-lg); padding: 10px 12px; margin-top: 6px; font-size: 12px; font-family: inherit; color: var(--text-body); min-height: 52px; resize: vertical; }}
        .meds-list {{ display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }}
        .meds-list .med {{ font-size: 12px; color: var(--text-body); padding: 6px 10px; background: #f8fafc; border: 1px solid #eef2f6; border-radius: 8px; }}
        .stub-line {{ font-size: 12px; color: var(--text-muted); font-style: italic; margin-top: 4px; }}
        .empty-state {{ text-align: center; padding: 3rem 1rem; color: var(--text-muted); }}
        .empty-state .material-icons-round {{ font-size: 48px; color: #cbd5e1; margin-bottom: 12px; display: block; }}
        .session-overlay {{ position: fixed; inset: 0; background: var(--bg-page); display: flex; align-items: flex-start; justify-content: center; z-index: 1000; overflow-y: auto; padding: 4rem 1.5rem 2rem; }}
        .session-container {{ max-width: 560px; width: 100%; }}
        .ov-head {{ text-align: center; margin-bottom: 20px; }}
        .ov-head h2 {{ font-size: 24px; font-weight: 900; color: var(--text-heading); }}
        .ov-card {{ display: flex; align-items: center; gap: 14px; padding: 14px 18px; background: #fff; border-radius: var(--radius-lg); box-shadow: var(--shadow-card); margin-bottom: 8px; }}
        .ov-card .p-meta {{ font-size: 12px; color: var(--text-muted); }}
        .ov-link {{ display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 700; color: var(--primary); cursor: pointer; white-space: nowrap; }}
        .ov-link:hover {{ color: var(--primary-hover); }}
        .ov-link .material-icons-round {{ font-size: 15px; }}
        .ov-actions {{ display: flex; flex-direction: column; align-items: center; gap: 10px; padding-top: 22px; }}
        @media (max-width: 900px) {{ .workspace {{ display: flex; flex-direction: column; height: auto; }} body {{ overflow: auto; height: auto; }} .main-panel, .side-panel {{ height: auto; }} }}
    </style>
</head>
<body>
    <input type="hidden" id="hid-staff-id" value="{staff_id_attr}">
    <input type="hidden" id="hid-staff-name" value="{staff_name_attr}">
    <div class="workspace">
        <main class="main-panel">
            <h1 class="hero-title">Group Therapy Session</h1>
            <p class="hero-meta">Pick a group session from the schedule, document once, and it lands in each attendee's appointment note.</p>
            <div style="max-width:320px;margin-bottom:24px;">
                <span class="label-editorial">Session Date</span>
                <input type="date" class="input-editorial" id="session-date" onchange="loadSessions()">
            </div>
            <div id="shared-form"></div>
            <div class="flow-footer">
                <button class="btn-pill btn-primary" id="submit-btn" onclick="submitSession()" disabled>Document Session</button>
            </div>
        </main>
        <div class="side-panel-wrapper">
            <aside class="side-panel">
                <div class="sidebar-header"><div class="label-editorial">Group Session</div><div class="count" id="att-count"></div></div>
                <div class="sidebar-sub" id="sidebar-sub">Choose a session for the selected date.</div>
                <div class="session-banner" id="session-banner">
                    <span class="material-icons-round">groups</span>
                    <div style="flex:1;"><div class="sb-prov" id="sb-prov"></div><div class="sb-time" id="sb-time"></div></div>
                    <a class="sb-change" onclick="changeSession()">Change</a>
                </div>
                <div class="audit-banner" id="audit-banner">
                    <div class="ab-row"><span class="material-icons-round">warning</span><span id="audit-text"></span></div>
                    <label class="audit-ack"><input type="checkbox" id="audit-ack" onchange="renderRoster()"> <span id="audit-ack-label">I understand</span></label>
                </div>
                <div class="audit-banner" id="dupe-banner">
                    <div class="ab-row"><span class="material-icons-round">lock</span><span id="dupe-text"></span></div>
                    <label class="audit-ack"><input type="checkbox" id="dupe-ack" onchange="renderRoster()"> <span id="dupe-ack-label">Document anyway (creates duplicate commands)</span></label>
                </div>
                <div class="session-pick" id="session-pick"></div>
                <div id="roster-list"></div>
            </aside>
        </div>
    </div>
    <script>
        const BASE = '/plugin-io/api/group_therapy';
        const LOGGED_IN_STAFF_ID = document.getElementById('hid-staff-id').value;
        const LOGGED_IN_NAME = document.getElementById('hid-staff-name').value || 'you';
        let sessions = [];
        let selected = null;       // index into sessions
        let template = null;       // resolved template for the selected session
        let roster = [];           // attendees
        let sharedForm = {{}};       // shared free_text values keyed by section label
        let sharedQ = {{}};          // shared questionnaire answers: label -> {{qname: value}}
        let formLocked = false;

        // Canvas MessageChannel API: the host posts INIT_CHANNEL with a port on
        // load; close the modal by signalling the host over that port.
        let messagePort = null;
        window.addEventListener('message', function (event) {{
            if (event.data && event.data.type === 'INIT_CHANNEL' && event.ports && event.ports[0]) {{
                messagePort = event.ports[0];
                messagePort.start();
            }}
        }});
        function closeModal() {{ if (messagePort) messagePort.postMessage({{ type: 'CLOSE_MODAL' }}); }}

        function esc(s) {{ return (s == null ? '' : String(s)).split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;').split('"').join('&quot;').split("'").join('&#39;'); }}
        // Safe to embed inside a single-quoted JS string within a double-quoted
        // HTML attribute (e.g. onclick): HTML-escapes & < > " and backslash-/
        // quote-escapes \\ and ' so an admin-set label cannot break out. Uses
        // String.fromCharCode(92) for the backslash to keep this readable.
        function jsq(s) {{
            const BS = String.fromCharCode(92);
            s = (s == null) ? '' : String(s);
            s = s.split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;').split('"').join('&quot;');
            s = s.split(BS).join(BS + BS).split("'").join(BS + "'");
            return s;
        }}
        function asText(v) {{ return Array.isArray(v) ? v.join(', ') : (v == null ? '' : String(v)); }}
        function localDateStr(d) {{ return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0'); }}
        function timeLabel(iso) {{ try {{ return new Date(iso).toLocaleTimeString([], {{hour:'numeric', minute:'2-digit'}}); }} catch (e) {{ return iso; }} }}
        function durationLabel(m) {{ const n = parseInt(m,10); return isNaN(n) ? '' : (n + ' min'); }}
        function avatarHtml(a) {{
            if (a.photo_url) {{ return '<div class="p-avatar" data-init="'+esc(a.initials)+'"><img src="'+esc(a.photo_url)+'" alt="" onerror="this.parentNode.textContent=this.parentNode.getAttribute(\\'data-init\\')"></div>'; }}
            return '<div class="p-avatar">'+esc(a.initials)+'</div>';
        }}
        function sections() {{ return (template && template.sections) || []; }}
        function sharedSecs() {{ return sections().filter(s => s.scope === 'shared'); }}
        function patientSecs() {{ return sections().filter(s => s.scope !== 'shared'); }}

        document.addEventListener('DOMContentLoaded', () => {{
            document.getElementById('session-date').value = localDateStr(new Date());
            renderSharedForm();
            loadSessions();
        }});

        async function loadSessions() {{
            selected = null; roster = []; sessions = []; template = null; sharedForm = {{}}; sharedQ = {{}};
            renderSharedForm(); renderRoster();
            const dateVal = document.getElementById('session-date').value;
            const pick = document.getElementById('session-pick');
            pick.innerHTML = '<div class="sidebar-sub">Loading sessions...</div>';
            try {{ const r = await fetch(BASE + '/sessions?date=' + encodeURIComponent(dateVal)); sessions = (await r.json()).sessions || []; }}
            catch (e) {{ sessions = []; }}
            renderSessionPicker();
        }}

        function changeSession() {{ selected = null; roster = []; template = null; sharedForm = {{}}; sharedQ = {{}}; renderSessionPicker(); renderSharedForm(); renderRoster(); }}

        function renderSessionPicker() {{
            const pick = document.getElementById('session-pick'); const sub = document.getElementById('sidebar-sub');
            if (selected !== null) {{ pick.style.display = 'none'; sub.style.display = 'none'; return; }}
            pick.style.display = ''; sub.style.display = '';
            if (!sessions.length) {{ pick.innerHTML = ''; sub.textContent = 'No group sessions scheduled for this date.'; return; }}
            sub.textContent = 'Pick the session you are documenting.';
            pick.innerHTML = sessions.map((s, i) =>
                '<div class="session-option" onclick="selectSession('+i+')"><div><div class="so-time">'+esc(timeLabel(s.start_time))
                + '</div><div class="so-meta">'+esc(s.provider_name || 'Provider')+'</div></div>'
                + '<div class="so-count">'+s.patient_count+' patients</div></div>'
            ).join('');
        }}

        async function selectSession(idx) {{
            selected = idx;
            const s = sessions[idx];
            // resolve the configured template (sections + live questionnaire schema)
            template = null;
            try {{
                const r = await fetch(BASE + '/template?rfv=' + encodeURIComponent((s.rfv_codes || []).join(',')));
                template = (await r.json()).template;
            }} catch (e) {{ template = null; }}
            roster = (s.roster || []).map(r => ({{ ...r, status: 'present', dx: '', conditions: [], medications: [], q: {{}}, fields: {{}}, loading: !r.blocked }}));
            renderSessionPicker(); renderSharedForm(); renderRoster();
            const needsConditions = patientSecs().some(x => x.type === 'diagnosis');
            const needsMeds = patientSecs().some(x => x.type === 'medications');
            await Promise.all(roster.map(async (att) => {{
                if (att.blocked) {{ att.loading = false; return; }}
                if (needsConditions) {{
                    try {{ const d = await (await fetch(BASE + '/patient/conditions?patient_id=' + encodeURIComponent(att.patient_id))).json();
                        att.conditions = d.conditions || []; att.dx = d.default_id || ''; }} catch (e) {{ att.conditions = []; }}
                }}
                if (needsMeds) {{
                    try {{ const m = await (await fetch(BASE + '/patient/medications?patient_id=' + encodeURIComponent(att.patient_id))).json();
                        att.medications = m.medications || []; }} catch (e) {{ att.medications = []; }}
                }}
                att.loading = false;
            }}));
            renderRoster();
        }}

        // ---------- questionnaire control rendering (shared + per-patient) ----------
        // store keys answers under `bag` (an object). onchange handlers mutate bag in place.
        function qControlsHtml(schema, scopeKey, ownerId) {{
            if (!schema || !schema.length) return '<div class="stub-line">Questionnaire has no questions configured.</div>';
            const dis = formLocked ? ' disabled' : '';
            let html = '';
            schema.forEach(q => {{
                html += '<div class="q-block"><span class="q-label">'+esc(q.label)+'</span>';
                const cb = "qAnswer('"+jsq(scopeKey)+"','"+jsq(ownerId)+"','"+jsq(q.name)+"'";
                if (q.kind === 'radio') {{
                    html += '<div class="opt-row">' + (q.options||[]).map(o =>
                        '<div class="opt-pill'+(formLocked?' locked':'')+'" data-q="'+esc(q.name)+'" data-v="'+esc(o.value)+'" onclick="qRadio(\\''+jsq(scopeKey)+'\\',\\''+jsq(ownerId)+'\\',\\''+jsq(q.name)+'\\',\\''+jsq(o.value)+'\\',this)">'+esc(o.label)+'</div>'
                    ).join('') + '</div>';
                }} else if (q.kind === 'checkbox') {{
                    html += '<div class="opt-row">' + (q.options||[]).map(o =>
                        '<div class="opt-pill'+(formLocked?' locked':'')+'" onclick="qCheck(\\''+jsq(scopeKey)+'\\',\\''+jsq(ownerId)+'\\',\\''+jsq(q.name)+'\\',\\''+jsq(o.value)+'\\',this)">'+esc(o.label)+'</div>'
                    ).join('') + '</div>';
                }} else if (q.kind === 'integer') {{
                    html += '<input type="number" class="input-editorial"'+dis+' oninput="'+cb+',this.value)">';
                }} else {{
                    html += '<textarea class="soap-area"'+dis+' oninput="'+cb+',this.value)"></textarea>';
                }}
                html += '</div>';
            }});
            return html;
        }}
        function _bag(scopeKey, ownerId) {{
            if (scopeKey === 'shared') {{ sharedQ[ownerId] = sharedQ[ownerId] || {{}}; return sharedQ[ownerId]; }}
            const a = roster.find(r => r.patient_id === ownerId); a.q[scopeKey] = a.q[scopeKey] || {{}}; return a.q[scopeKey];
        }}
        function qAnswer(scopeKey, ownerId, qname, value) {{ _bag(scopeKey, ownerId)[qname] = value; }}
        function qRadio(scopeKey, ownerId, qname, value, el) {{
            if (formLocked) return;
            const sibs = el.parentNode.querySelectorAll('.opt-pill'); sibs.forEach(s => s.classList.remove('active')); el.classList.add('active');
            _bag(scopeKey, ownerId)[qname] = value;
        }}
        function qCheck(scopeKey, ownerId, qname, value, el) {{
            if (formLocked) return;
            el.classList.toggle('active');
            const bag = _bag(scopeKey, ownerId); const cur = Array.isArray(bag[qname]) ? bag[qname] : [];
            const i = cur.indexOf(value); if (i === -1) cur.push(value); else cur.splice(i, 1); bag[qname] = cur;
        }}

        // ---------- structured options sections (admin-defined choices, no Canvas command) ----------
        function optionsBag(scopeKey, ownerId) {{ return scopeKey === 'shared' ? sharedForm : roster.find(r => r.patient_id === ownerId).fields; }}
        function optionPick(scopeKey, ownerId, label, value, multi, el) {{
            if (formLocked) return;
            const bag = optionsBag(scopeKey, ownerId);
            if (multi) {{
                el.classList.toggle('active');
                const cur = Array.isArray(bag[label]) ? bag[label] : [];
                const i = cur.indexOf(value); if (i === -1) cur.push(value); else cur.splice(i, 1); bag[label] = cur;
            }} else {{
                el.parentNode.querySelectorAll('.opt-pill').forEach(s => s.classList.remove('active')); el.classList.add('active');
                bag[label] = value;
            }}
        }}
        function optionsHtml(sec, scopeKey, ownerId) {{
            const sel = optionsBag(scopeKey, ownerId)[sec.label];
            const isSel = (v) => sec.multi ? (Array.isArray(sel) && sel.indexOf(v) !== -1) : (sel === v);
            const pills = (sec.choices || []).map(c =>
                '<div class="opt-pill' + (isSel(c) ? ' active' : '') + (formLocked ? ' locked' : '')
                + '" onclick="optionPick(\\'' + jsq(scopeKey) + '\\',\\'' + jsq(ownerId) + '\\',\\'' + jsq(sec.label) + '\\',\\'' + jsq(c) + '\\',' + (sec.multi ? 'true' : 'false') + ',this)">' + esc(c) + '</div>'
            ).join('');
            return '<div class="opt-row">' + (pills || '<span class="stub-line">No choices configured</span>') + '</div>';
        }}

        // ---------- shared form (main panel) ----------
        function updateShared(label, v) {{ sharedForm[label] = v; }}
        function renderSharedForm() {{
            const host = document.getElementById('shared-form');
            document.getElementById('session-date').disabled = formLocked;
            if (selected === null || !template) {{
                host.innerHTML = '<div class="shared-empty"><span class="material-icons-round">event_note</span><p>Pick a group session on the right to start documenting.</p></div>';
                return;
            }}
            const s = sessions[selected]; const dis = formLocked ? ' disabled' : '';
            let html = '<div class="tmpl-pill"><span class="material-icons-round" style="font-size:14px;">description</span>'+esc(template.name || 'Template')+(template.cpt_code ? ' \\u00b7 CPT '+esc(template.cpt_code) : '')+'</div>';
            html += '<div class="meta-strip">'
                + '<div><span class="ms-k">Provider</span><span class="ms-v">'+esc(s.provider_name || 'Provider')+'</span></div>'
                + '<div><span class="ms-k">Facilitator</span><span class="ms-v">'+esc(s.facilitator || s.provider_name || '-')+'</span></div>'
                + '<div><span class="ms-k">Duration</span><span class="ms-v">'+esc(durationLabel(s.duration_minutes) || '-')+'</span></div>'
                + '<div><span class="ms-k">Attendees</span><span class="ms-v">'+s.patient_count+'</span></div></div>';
            sharedSecs().forEach(sec => {{
                html += '<div class="field-block"><span class="label-editorial">'+esc(sec.label)+'</span>';
                if (sec.type === 'questionnaire') {{ html += qControlsHtml(sec.schema, 'shared', sec.label); }}
                else if (sec.type === 'options') {{ html += optionsHtml(sec, 'shared', sec.label); }}
                else {{ html += '<textarea class="soap-area"'+dis+' oninput="updateShared(\\''+jsq(sec.label)+'\\', this.value)">'+esc(asText(sharedForm[sec.label]))+'</textarea>'; }}
                html += '</div>';
            }});
            host.innerHTML = html;
        }}

        // ---------- roster (per-patient) ----------
        function updateStatus(id, st) {{ const a = roster.find(r => r.patient_id === id); if (a) {{ a.status = st; renderRoster(); }} }}
        function updateDx(id, v) {{ const a = roster.find(r => r.patient_id === id); if (a) a.dx = v; }}
        function updateField(id, label, v) {{ const a = roster.find(r => r.patient_id === id); if (a) a.fields[label] = v; }}
        function toggleCard(id) {{ const a = roster.find(r => r.patient_id === id); if (a) {{ a.expanded = !a.expanded; renderRoster(); }} }}

        function patientSectionHtml(a, sec) {{
            const dis = formLocked ? ' disabled' : '';
            if (sec.type === 'diagnosis') {{
                if (!a.conditions.length) return '<div class="field-mini"><span class="label-mini">'+esc(sec.label)+'</span><div class="stub-line">No active diagnoses on chart</div></div>';
                let opts = '<option value="">No diagnosis</option>';
                a.conditions.forEach(c => {{ opts += '<option value="'+esc(c.id)+'"'+(c.id===a.dx?' selected':'')+'>'+esc(c.icd10_code+' - '+c.display)+'</option>'; }});
                return '<div class="field-mini"><span class="label-mini">'+esc(sec.label)+'</span><select class="select-mini"'+dis+' onchange="updateDx(\\''+a.patient_id+'\\', this.value)">'+opts+'</select></div>';
            }}
            if (sec.type === 'medications') {{
                const meds = a.medications || [];
                const inner = meds.length ? '<div class="meds-list">'+meds.map(m => '<div class="med">'+esc(m)+'</div>').join('')+'</div>' : '<div class="stub-line">No active medications on chart</div>';
                return '<div class="field-mini"><span class="label-mini">'+esc(sec.label)+'</span>'+inner+'</div>';
            }}
            if (sec.type === 'billing') {{
                return '<div class="field-mini"><span class="label-mini">'+esc(sec.label)+'</span><div class="stub-line">CPT '+esc((template && template.cpt_code) || '')+' applied per billing rule</div></div>';
            }}
            if (sec.type === 'questionnaire') {{
                return '<div class="field-mini"><span class="label-mini">'+esc(sec.label)+'</span>'+qControlsHtml(sec.schema, sec.label, a.patient_id)+'</div>';
            }}
            if (sec.type === 'options') {{
                return '<div class="field-mini"><span class="label-mini">'+esc(sec.label)+'</span>'+optionsHtml(sec, 'patient', a.patient_id)+'</div>';
            }}
            // free_text
            return '<div class="field-mini"><span class="label-mini">'+esc(sec.label)+'</span><textarea class="p-note"'+dis+' placeholder="'+esc(sec.label)+'..." oninput="updateField(\\''+a.patient_id+'\\', \\''+jsq(sec.label)+'\\', this.value)">'+esc(asText(a.fields[sec.label]))+'</textarea></div>';
        }}

        function cardBody(a) {{
            if (a.noshow) return '<div class="locked-flag" style="color:var(--text-muted);"><span class="material-icons-round">event_busy</span>Marked no-show</div>';
            if (a.blocked) return '<div class="locked-flag"><span class="material-icons-round">lock</span>Appointment note is signed/locked - cannot document.</div>';
            let body = '';
            if (a.needs_checkin) body += '<div class="checkin-pill"><span class="material-icons-round">how_to_reg</span>Will be checked in when documented</div>';
            const lockStyle = formLocked ? ' style="pointer-events:none;opacity:0.6;"' : '';
            body += '<div class="pill-toggle"'+lockStyle+'>'
                + '<div class="toggle-opt '+(a.status==='present'?'active':'')+'" onclick="updateStatus(\\''+a.patient_id+'\\', \\'present\\')">In Person</div>'
                + '<div class="toggle-opt '+(a.status==='virtual'?'active':'')+'" onclick="updateStatus(\\''+a.patient_id+'\\', \\'virtual\\')">Virtual</div>'
                + '<div class="toggle-opt '+(a.status==='absent'?'active':'')+'" onclick="updateStatus(\\''+a.patient_id+'\\', \\'absent\\')">Absent</div></div>';
            if (a.loading) return body + '<div class="label-mini" style="margin-top:12px;">Loading chart...</div>';
            if (a.status !== 'absent') {{ patientSecs().forEach(sec => {{ body += patientSectionHtml(a, sec); }}); }}
            return body;
        }}

        function renderSessionInfo() {{
            const banner = document.getElementById('session-banner'); const audit = document.getElementById('audit-banner'); const dupe = document.getElementById('dupe-banner');
            if (selected === null) {{ banner.classList.remove('show'); audit.classList.remove('show','ack'); dupe.classList.remove('show','ack'); return; }}
            const s = sessions[selected];
            document.getElementById('sb-prov').textContent = 'Provider: ' + (s.provider_name || 'Provider');
            document.getElementById('sb-time').textContent = timeLabel(s.start_time) + ' \\u00b7 ' + s.patient_count + ' attendees \\u00b7 ' + ((template && template.name) || '');
            banner.classList.add('show');
            const notProvider = LOGGED_IN_STAFF_ID && s.provider_id && LOGGED_IN_STAFF_ID !== s.provider_id;
            if (notProvider) {{
                document.getElementById('audit-text').textContent = 'You (' + LOGGED_IN_NAME + ') are not the session provider (' + (s.provider_name || 'the provider') + '). The note will show ' + (s.provider_name || 'the provider') + ' as provider, but the audit log will record this documentation under your name.';
                audit.classList.add('show');
                const ack = document.getElementById('audit-ack'); const checked = !!(ack && ack.checked);
                audit.classList.toggle('ack', checked);
                document.getElementById('audit-ack-label').textContent = checked ? ('Acknowledged - documenting as ' + LOGGED_IN_NAME) : 'I understand';
            }} else {{ audit.classList.remove('show','ack'); const ack = document.getElementById('audit-ack'); if (ack) ack.checked = false; }}
            const done = roster.filter(a => a.documented).length;
            if (done > 0) {{
                document.getElementById('dupe-text').textContent = done + ' of these attendees already have group therapy documentation on this appointment. Documenting again will create duplicate commands in their notes.';
                dupe.classList.add('show');
                const d = document.getElementById('dupe-ack'); const dc = !!(d && d.checked); dupe.classList.toggle('ack', dc);
                document.getElementById('dupe-ack-label').textContent = dc ? 'Acknowledged - will create duplicate commands' : 'Document anyway (creates duplicate commands)';
            }} else {{ dupe.classList.remove('show','ack'); const d = document.getElementById('dupe-ack'); if (d) d.checked = false; }}
        }}
        function auditOk() {{
            if (selected === null) return false;
            const s = sessions[selected];
            if (LOGGED_IN_STAFF_ID && s.provider_id && LOGGED_IN_STAFF_ID !== s.provider_id) {{ const ack = document.getElementById('audit-ack'); if (!(ack && ack.checked)) return false; }}
            if (roster.some(a => a.documented)) {{ const d = document.getElementById('dupe-ack'); if (!(d && d.checked)) return false; }}
            return true;
        }}
        function renderRoster() {{
            const list = document.getElementById('roster-list');
            document.getElementById('att-count').textContent = roster.length ? roster.length : '';
            renderSessionInfo();
            if (selected === null) {{ list.innerHTML = ''; document.getElementById('submit-btn').disabled = true; return; }}
            if (!roster.length) {{ list.innerHTML = '<div class="empty-state"><span class="material-icons-round">groups</span><p>No attendees in this session.</p></div>'; document.getElementById('submit-btn').disabled = true; return; }}
            list.innerHTML = '';
            roster.forEach(a => {{
                const card = document.createElement('div');
                card.className = 'p-card' + (a.blocked ? ' locked' : '');
                card.innerHTML = '<div class="p-header" onclick="toggleCard(\\''+a.patient_id+'\\')">' + avatarHtml(a)
                    + '<div class="p-info"><div class="p-name">'+esc(a.name)+'</div><div class="p-meta">DOB: '+esc(a.dob)+'</div></div>'
                    + (a.documented ? '<span class="badge-done"><span class="material-icons-round">check_circle</span>Documented</span>' : '')
                    + '<span class="material-icons-round card-chart" title="Open chart" onclick="event.stopPropagation(); openChart(\\''+a.patient_id+'\\')">open_in_new</span>'
                    + '<span class="material-icons-round p-chevron '+(a.expanded===false?'':'rotated')+'">expand_more</span></div>'
                    + '<div class="p-body '+(a.expanded===false?'collapsed':'')+'">' + cardBody(a) + '</div>';
                list.appendChild(card);
            }});
            document.getElementById('submit-btn').disabled = formLocked || !roster.some(a => !a.blocked) || !auditOk();
        }}

        // ---------- submit ----------
        function attendeeSummarySections(a) {{
            const out = [];
            sharedSecs().forEach(sec => {{ if (sec.type === 'free_text' || sec.type === 'options') {{ const v = asText(sharedForm[sec.label]).trim(); if (v) out.push({{label: sec.label, value: v}}); }} }});
            patientSecs().forEach(sec => {{
                if (sec.type === 'free_text' || sec.type === 'options') {{ const v = asText(a.fields[sec.label]).trim(); if (v) out.push({{label: sec.label, value: v}}); }}
                else if (sec.type === 'medications') {{ const v = (a.medications || []).join(', '); if (v) out.push({{label: sec.label, value: v}}); }}
            }});
            return out;
        }}
        function attendeeQuestionnaires(a) {{
            const out = [];
            sharedSecs().forEach(sec => {{ if (sec.type === 'questionnaire' && sec.code) out.push({{code: sec.code, answers: sharedQ[sec.label] || {{}}}}); }});
            patientSecs().forEach(sec => {{ if (sec.type === 'questionnaire' && sec.code) out.push({{code: sec.code, answers: (a.q[sec.label]) || {{}}}}); }});
            return out;
        }}
        function attendeeConditionId(a) {{ const dxSec = patientSecs().find(sec => sec.type === 'diagnosis'); return dxSec ? a.dx : ''; }}

        async function submitSession() {{
            if (selected === null || !auditOk()) return;
            const s = sessions[selected];
            const documentable = roster.filter(a => !a.blocked);
            if (!documentable.length) return;
            document.getElementById('submit-btn').disabled = true;
            const shared = {{ provider_id: s.provider_id, rfv_codes: s.rfv_codes || [], session_date: document.getElementById('session-date').value,
                facilitator: s.facilitator || s.provider_name || '', duration_minutes: s.duration_minutes }};
            showOverlay(documentable);
            let documented = 0, noShow = 0, skipped = 0;
            for (let i = 0; i < documentable.length; i++) {{
                const a = documentable[i];
                const participant = {{ id: a.patient_id, name: a.name, status: a.status, target_note_id: a.note_id, needs_checkin: a.needs_checkin }};
                if (a.status !== 'absent') {{ participant.condition_id = attendeeConditionId(a); participant.summary_sections = attendeeSummarySections(a); participant.questionnaires = attendeeQuestionnaires(a); }}
                let action = 'skipped';
                try {{ const resp = await fetch(BASE + '/session/complete-patient', {{ method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify({{ ...shared, participant_index: i, participant }}) }});
                    const data = await resp.json(); action = data.action || (data.success ? 'documented' : 'skipped'); }} catch (e) {{ action = 'error'; }}
                if (action === 'documented') {{ documented++; setOvMeta(i, 'Documented'); }} else if (action === 'no_show') {{ noShow++; setOvMeta(i, 'Marked no-show'); }} else {{ skipped++; setOvMeta(i, 'Skipped'); }}
            }}
            const parts = []; if (documented) parts.push(documented+' documented'); if (noShow) parts.push(noShow+' no-show'); if (skipped) parts.push(skipped+' skipped');
            document.getElementById('ov-sub').textContent = parts.join(' \\u00b7 ') + ' - open for your signature';
            formLocked = true; renderSharedForm(); renderRoster();
        }}
        function showOverlay(attendees) {{
            const ov = document.createElement('div'); ov.className = 'session-overlay'; ov.id = 'ov';
            const cards = attendees.map((a, i) => '<div class="ov-card">'+avatarHtml(a)
                +'<div style="flex:1;"><div class="p-name">'+esc(a.name)+'</div><div class="p-meta" id="ov-meta-'+i+'">Working...</div></div>'
                +'<a class="ov-link" onclick="openChart(\\''+a.patient_id+'\\')"><span class="material-icons-round">open_in_new</span>Open chart</a>'
                +'</div>').join('');
            ov.innerHTML = '<div class="session-container"><div class="ov-head"><h2>Documenting Session</h2><p id="ov-sub">'+attendees.length+' attendees</p></div>'+cards
                + '<div class="ov-actions"><button class="btn-pill btn-primary" onclick="documentAnother()">Document another session</button><button class="btn-pill btn-secondary" onclick="closeOverlay()">Close</button></div></div>';
            document.body.appendChild(ov);
        }}
        function setOvMeta(i, t) {{ const el = document.getElementById('ov-meta-'+i); if (el) el.textContent = t; }}
        function openChart(pid) {{ if (pid) window.open('/patient/'+pid, '_blank'); }}
        function documentAnother() {{ const ov = document.getElementById('ov'); if (ov) ov.remove(); formLocked = false; document.getElementById('session-date').value = localDateStr(new Date()); loadSessions(); document.getElementById('submit-btn').disabled = false; }}
        function closeOverlay() {{ const ov = document.getElementById('ov'); if (ov) ov.remove(); closeModal(); }}
    </script>
</body>
</html>"""
