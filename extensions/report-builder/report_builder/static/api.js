const BASE = '/plugin-io/api/report_builder';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    credentials: 'same-origin',
    ...options,
  });
  const contentType = res.headers.get('content-type') || '';
  let body = null;
  if (contentType.includes('application/json')) {
    body = await res.json();
  } else {
    body = await res.text();
  }
  if (!res.ok) {
    const message = body && body.errors
      ? body.errors.map((e) => `${e.path}: ${e.message}`).join('; ')
      : (body && body.error) || res.statusText;
    const err = new Error(message);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

export const api = {
  getEntities: () => request('/entities'),
  listReports: () => request('/reports'),
  getReport: (id) => request(`/reports/${encodeURIComponent(id)}`),
  createReport: (report) => request('/reports', { method: 'POST', body: JSON.stringify(report) }),
  updateReport: (id, report) => request(`/reports/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(report),
  }),
  deleteReport: (id) => request(`/reports/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  previewReport: (report, as_of_date, page = 1, per_page = 25) => request('/reports/preview', {
    method: 'POST',
    body: JSON.stringify({ report, as_of_date, page, per_page }),
  }),
  runReport: (id, as_of_date, page = 1, per_page = 100) => request(`/reports/${encodeURIComponent(id)}/run`, {
    method: 'POST',
    body: JSON.stringify({ as_of_date, page, per_page }),
  }),
  exportUrl: (id, as_of_date) => `${BASE}/reports/${encodeURIComponent(id)}/export?as_of_date=${encodeURIComponent(as_of_date)}`,
};
