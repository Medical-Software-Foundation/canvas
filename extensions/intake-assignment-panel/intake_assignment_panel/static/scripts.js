// Row click handler — opens the deep-link in a new tab unless the user clicked the patient
// anchor (which navigates itself with target="_blank") or held a modifier key.
function openNote(event, url) {
    if (!url) return;
    if (event.target && event.target.closest('a')) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) return;
    window.open(url, '_blank', 'noopener');
}

// Sort column toggling. Click cycles asc → desc → cleared (back to default).
function sortByColumn(column) {
    const meta = document.querySelector('.table-meta');
    const currentSortBy = meta?.dataset.sortBy || '';
    const currentSortDir = meta?.dataset.sortDir || '';

    let nextSortBy = column;
    let nextSortDir = 'asc';
    if (column === currentSortBy) {
        if (currentSortDir === 'asc') {
            nextSortDir = 'desc';
        } else {
            nextSortBy = '';
            nextSortDir = '';
        }
    }

    const params = new URLSearchParams();
    if (nextSortBy) params.append('sort_by', nextSortBy);
    if (nextSortDir) params.append('sort_dir', nextSortDir);

    const qs = params.toString();
    const url = '/plugin-io/api/intake_assignment_panel/app/table' + (qs ? '?' + qs : '');
    htmx.ajax('GET', url, { target: '#intake-table', swap: 'innerHTML' });
}

function initSortableHeaders() {
    document.querySelectorAll('.intake-table th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const column = th.getAttribute('data-sort');
            if (column) sortByColumn(column);
        });
    });
}

document.addEventListener('htmx:afterSwap', (event) => {
    if (event.target && event.target.id === 'intake-table') {
        initSortableHeaders();
    }
});
