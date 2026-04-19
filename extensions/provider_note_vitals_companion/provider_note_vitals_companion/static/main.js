(function () {
    var messagePort = null;

    window.addEventListener('message', function (event) {
        if (event.data && event.data.type === 'INIT_CHANNEL' && event.ports && event.ports[0]) {
            messagePort = event.ports[0];
            messagePort.start();
        }
    });

    function closeModal() {
        if (messagePort) {
            messagePort.postMessage({ type: 'CLOSE_MODAL' });
            return;
        }
        window.close();
    }

    function getNoteId() {
        var params = new URLSearchParams(window.location.search);
        return (params.get('note_id') || '').trim();
    }

    function setStatus(message, kind) {
        var el = document.getElementById('status');
        el.textContent = message || '';
        el.className = 'status' + (kind ? ' ' + kind : '');
    }

    function collectPayload(form) {
        var payload = {};
        var data = new FormData(form);
        data.forEach(function (value, key) {
            var trimmed = (value || '').toString().trim();
            if (trimmed !== '') {
                payload[key] = trimmed;
            }
        });
        return payload;
    }

    document.addEventListener('DOMContentLoaded', function () {
        var form = document.getElementById('vitals-form');
        var submitBtn = document.getElementById('submit-btn');
        var cancelBtn = document.getElementById('cancel-btn');
        var noteId = getNoteId();

        // Stop wheel / scroll from quietly mutating focused number inputs.
        form.querySelectorAll('input[type="number"]').forEach(function (input) {
            input.addEventListener('wheel', function () { input.blur(); }, { passive: true });
        });

        cancelBtn.addEventListener('click', closeModal);

        form.addEventListener('submit', function (e) {
            e.preventDefault();

            if (!noteId) {
                setStatus('Missing note context. Close and re-open this tool from the note.', 'error');
                return;
            }

            var payload = collectPayload(form);
            if (Object.keys(payload).length === 0) {
                setStatus('Enter at least one vital before saving.', 'error');
                return;
            }

            submitBtn.disabled = true;
            setStatus('Saving...', '');

            fetch(
                '/plugin-io/api/provider_note_vitals_companion/app/vitals?note_id=' +
                    encodeURIComponent(noteId),
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                }
            )
                .then(function (res) {
                    return res
                        .json()
                        .catch(function () {
                            return {};
                        })
                        .then(function (body) {
                            return { ok: res.ok, status: res.status, body: body };
                        });
                })
                .then(function (result) {
                    if (result.ok) {
                        setStatus('Vitals saved.', 'success');
                        closeModal();
                    } else {
                        var msg = (result.body && result.body.error) || 'Failed to save vitals';
                        setStatus(msg, 'error');
                        submitBtn.disabled = false;
                    }
                })
                .catch(function () {
                    setStatus('Network error. Try again.', 'error');
                    submitBtn.disabled = false;
                });
        });
    });
})();
