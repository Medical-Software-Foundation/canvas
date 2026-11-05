import { h } from 'https://esm.sh/preact@10.25.4';
import { useEffect, useState, useCallback } from 'https://esm.sh/preact@10.25.4/hooks';
import htm from 'https://esm.sh/htm@3.1.1';

import { api } from '/plugin-io/api/report_builder/static/api.js?v={{ cache_bust }}';
import { ReportList } from '/plugin-io/api/report_builder/static/report-list.js?v={{ cache_bust }}';
import { Builder } from '/plugin-io/api/report_builder/static/builder.js?v={{ cache_bust }}';
import { Runner } from '/plugin-io/api/report_builder/static/runner.js?v={{ cache_bust }}';
import { Toast } from '/plugin-io/api/report_builder/static/toast.js?v={{ cache_bust }}';

const html = htm.bind(h);

function emptyReport(entityKey) {
  return {
    id: null,
    name: '',
    description: '',
    root_entity: entityKey || 'patient',
    conditions: [],
    columns: [],
    aggregate_columns: [],
  };
}

export function App({ initialData }) {
  const [entities, setEntities] = useState(null);
  const [reports, setReports] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [draft, setDraft] = useState(null);
  const [view, setView] = useState('builder');
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(true);

  const showToast = useCallback((message, kind = 'info') => {
    setToast({ message, kind });
    setTimeout(() => setToast(null), 4000);
  }, []);

  const loadReports = useCallback(async () => {
    try {
      const data = await api.listReports();
      setReports(data.reports || []);
    } catch (err) {
      showToast(`Failed to load reports: ${err.message}`, 'error');
    }
  }, [showToast]);

  useEffect(() => {
    (async () => {
      try {
        const [entityData] = await Promise.all([api.getEntities(), loadReports()]);
        setEntities(entityData.entities || []);
      } catch (err) {
        showToast(`Failed to load schema: ${err.message}`, 'error');
      } finally {
        setLoading(false);
      }
    })();
  }, [loadReports, showToast]);

  const startNewReport = useCallback(() => {
    setSelectedId(null);
    setDraft(emptyReport(entities?.[0]?.key));
    setView('builder');
  }, [entities]);

  const openReport = useCallback(async (id) => {
    try {
      const { report } = await api.getReport(id);
      setSelectedId(id);
      setDraft(report);
      setView('builder');
    } catch (err) {
      showToast(`Failed to open report: ${err.message}`, 'error');
    }
  }, [showToast]);

  const saveDraft = useCallback(async () => {
    if (!draft) return;
    try {
      const payload = draft.id
        ? await api.updateReport(draft.id, draft)
        : await api.createReport(draft);
      const saved = payload.report;
      setDraft(saved);
      setSelectedId(saved.id);
      await loadReports();
      showToast(`Saved "${saved.name}"`, 'success');
    } catch (err) {
      showToast(`Save failed: ${err.message}`, 'error');
    }
  }, [draft, loadReports, showToast]);

  const deleteCurrent = useCallback(async () => {
    if (!draft?.id) return;
    if (!confirm(`Delete report "${draft.name}"?`)) return;
    try {
      await api.deleteReport(draft.id);
      setDraft(null);
      setSelectedId(null);
      await loadReports();
      showToast('Report deleted', 'success');
    } catch (err) {
      showToast(`Delete failed: ${err.message}`, 'error');
    }
  }, [draft, loadReports, showToast]);

  if (loading) {
    return html`<div class="rb-loading">Loading…</div>`;
  }

  return html`
    <div class="rb-root">
      ${toast && html`<${Toast} message=${toast.message} kind=${toast.kind} />`}
      <header class="rb-header">
        <h1>Report Builder</h1>
        <div class="rb-header-actions">
          <span class="rb-staff-name">${initialData.staffName || 'Staff'}</span>
          <button class="rb-btn rb-btn-primary" onClick=${startNewReport}>+ New report</button>
        </div>
      </header>
      <main class="rb-main">
        <aside class="rb-sidebar">
          <${ReportList}
            reports=${reports}
            selectedId=${selectedId}
            onSelect=${openReport}
          />
        </aside>
        <section class="rb-content">
          ${draft ? html`
            <div class="rb-tabs">
              <button
                class=${'rb-tab' + (view === 'builder' ? ' rb-tab-active' : '')}
                onClick=${() => setView('builder')}
              >Builder</button>
              <button
                class=${'rb-tab' + (view === 'runner' ? ' rb-tab-active' : '')}
                onClick=${() => setView('runner')}
                disabled=${!draft.id}
                title=${!draft.id ? 'Save the report first' : ''}
              >Run</button>
            </div>
            ${view === 'builder' ? html`
              <${Builder}
                entities=${entities}
                report=${draft}
                onChange=${setDraft}
                onSave=${saveDraft}
                onDelete=${draft.id ? deleteCurrent : null}
                showToast=${showToast}
              />
            ` : html`
              <${Runner}
                report=${draft}
                today=${initialData.today}
                showToast=${showToast}
              />
            `}
          ` : html`
            <div class="rb-empty">
              <h2>Select a report or create a new one.</h2>
              <p>Reports are saved to this Canvas instance and visible to all staff.</p>
            </div>
          `}
        </section>
      </main>
    </div>
  `;
}
