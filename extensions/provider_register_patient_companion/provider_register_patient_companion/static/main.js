(function () {
    var messagePort = null;
    var API_BASE = '/plugin-io/api/provider_register_patient_companion/app';
    var POLL_INTERVAL_MS = 500;
    var POLL_TIMEOUT_MS = 5000;

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

    function setStatus(message, kind) {
        var el = document.getElementById('status');
        el.textContent = message || '';
        el.className = 'status' + (kind ? ' ' + kind : '');
    }

    function clearFieldErrors() {
        document.querySelectorAll('.field-row').forEach(function (row) {
            row.classList.remove('has-error');
        });
        document.querySelectorAll('.field-error').forEach(function (el) {
            el.textContent = '';
        });
    }

    function applyFieldErrors(errors) {
        clearFieldErrors();
        Object.keys(errors).forEach(function (name) {
            var errEl = document.querySelector('.field-error[data-for="' + name + '"]');
            if (errEl) {
                errEl.textContent = errors[name];
                errEl.closest('.field-row').classList.add('has-error');
            }
        });
    }

    function collectPayload(form) {
        var payload = {};
        var data = new FormData(form);
        data.forEach(function (value, key) {
            payload[key] = (value || '').toString().trim();
        });
        return payload;
    }

    function validateClient(payload) {
        var errors = {};
        if (!payload.first_name) errors.first_name = 'First name is required.';
        if (!payload.last_name) errors.last_name = 'Last name is required.';
        if (!payload.birth_date) {
            errors.birth_date = 'Date of birth is required.';
        } else {
            var today = new Date();
            var todayStr = today.toISOString().slice(0, 10);
            if (payload.birth_date > todayStr) {
                errors.birth_date = 'Date of birth cannot be in the future.';
            }
        }
        if (!payload.sex_at_birth) errors.sex_at_birth = 'Sex at birth is required.';
        if (!payload.phone) {
            errors.phone = 'Phone number is required.';
        } else if ((payload.phone.match(/\d/g) || []).length < 10) {
            errors.phone = 'Phone number must contain at least 10 digits.';
        }
        return errors;
    }

    function renderDuplicates(duplicates) {
        var callout = document.getElementById('duplicate-callout');
        var list = document.getElementById('duplicate-list');
        var ack = document.getElementById('acknowledge');
        list.innerHTML = '';

        if (!duplicates || duplicates.length === 0) {
            callout.hidden = true;
            ack.checked = false;
            return false;
        }

        duplicates.forEach(function (dup) {
            var li = document.createElement('li');

            var name = document.createElement('div');
            name.className = 'dup-name';
            name.textContent = (dup.first_name || '') + ' ' + (dup.last_name || '');

            var meta = document.createElement('div');
            meta.className = 'dup-meta';
            var metaParts = [];
            if (dup.birth_date) metaParts.push('DOB ' + dup.birth_date);
            if (dup.phone) metaParts.push(dup.phone);
            meta.textContent = metaParts.join(' · ');

            var reason = document.createElement('div');
            reason.className = 'dup-reason';
            reason.textContent = 'Match: ' + (dup.reasons || []).join(', ');

            li.appendChild(name);
            if (metaParts.length) li.appendChild(meta);
            li.appendChild(reason);
            list.appendChild(li);
        });

        callout.hidden = false;
        return true;
    }

    function pollForPatient(lookupParams, startedAt) {
        var start = Date.now();
        return new Promise(function (resolve, reject) {
            function attempt() {
                var url =
                    API_BASE + '/find' +
                    '?first_name=' + encodeURIComponent(lookupParams.first_name) +
                    '&last_name=' + encodeURIComponent(lookupParams.last_name) +
                    '&birth_date=' + encodeURIComponent(lookupParams.birth_date) +
                    '&after=' + encodeURIComponent(startedAt);
                fetch(url).then(function (res) {
                    if (!res.ok) {
                        reject(new Error('find failed: ' + res.status));
                        return;
                    }
                    return res.json().then(function (body) {
                        if (body && body.patient_id) {
                            resolve(body.patient_id);
                            return;
                        }
                        if (Date.now() - start >= POLL_TIMEOUT_MS) {
                            resolve(null);
                            return;
                        }
                        setTimeout(attempt, POLL_INTERVAL_MS);
                    });
                }).catch(function (err) { reject(err); });
            }
            attempt();
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var form = document.getElementById('register-form');
        var submitBtn = document.getElementById('submit-btn');
        var submitLabel = submitBtn.querySelector('.btn-label');
        var cancelBtn = document.getElementById('cancel-btn');
        var ackEl = document.getElementById('acknowledge');
        var duplicatesShowing = false;

        function setBusy(busy) {
            if (busy) {
                submitBtn.classList.add('is-busy');
                submitBtn.disabled = true;
                submitLabel.textContent = 'Creating patient';
                setStatus('', '');
            } else {
                submitBtn.classList.remove('is-busy');
                submitBtn.disabled = false;
                submitLabel.textContent = 'Register';
            }
        }

        cancelBtn.addEventListener('click', closeModal);

        form.addEventListener('input', function (e) {
            // Any edit to a form field (but NOT the acknowledge checkbox itself)
            // invalidates the duplicate callout so the next submit re-checks.
            if (e.target === ackEl) return;
            if (duplicatesShowing) {
                document.getElementById('duplicate-callout').hidden = true;
                ackEl.checked = false;
                duplicatesShowing = false;
            }
        });

        form.addEventListener('submit', function (e) {
            e.preventDefault();

            var payload = collectPayload(form);
            var clientErrors = validateClient(payload);
            if (Object.keys(clientErrors).length > 0) {
                applyFieldErrors(clientErrors);
                setStatus('', '');
                return;
            }
            clearFieldErrors();

            setBusy(true);

            if (!duplicatesShowing) {
                fetch(API_BASE + '/check', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                })
                    .then(function (res) {
                        return res.json().then(function (body) {
                            return { ok: res.ok, status: res.status, body: body };
                        });
                    })
                    .then(function (result) {
                        if (!result.ok) {
                            if (result.body && result.body.errors) {
                                applyFieldErrors(result.body.errors);
                            }
                            setStatus('Please fix the errors above.', 'error');
                            setBusy(false);
                            return;
                        }
                        var dups = (result.body && result.body.duplicates) || [];
                        if (dups.length > 0) {
                            duplicatesShowing = renderDuplicates(dups);
                            setStatus('Review the possible duplicates above.', 'error');
                            setBusy(false);
                            return;
                        }
                        submitCreate(payload, false);
                    })
                    .catch(function () {
                        setStatus('Network error. Try again.', 'error');
                        setBusy(false);
                    });
                return;
            }

            if (!ackEl.checked) {
                setStatus('Acknowledge the duplicate review to continue.', 'error');
                setBusy(false);
                return;
            }
            submitCreate(payload, true);
        });

        function submitCreate(payload, acknowledged) {
            var body = Object.assign({}, payload, { acknowledged: acknowledged });
            fetch(API_BASE + '/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            })
                .then(function (res) {
                    return res.json().then(function (data) {
                        return { ok: res.ok, status: res.status, body: data };
                    });
                })
                .then(function (result) {
                    if (!result.ok) {
                        if (result.status === 409 && result.body && result.body.duplicates) {
                            duplicatesShowing = renderDuplicates(result.body.duplicates);
                            setStatus('Review the possible duplicates above.', 'error');
                            setBusy(false);
                            return;
                        }
                        if (result.body && result.body.errors) {
                            applyFieldErrors(result.body.errors);
                        }
                        setStatus(
                            (result.body && result.body.error) || 'There was an issue creating the patient.',
                            'error'
                        );
                        setBusy(false);
                        return;
                    }

                    return pollForPatient(result.body.lookup_params, result.body.lookup_started_at).then(
                        function (patientId) {
                            if (patientId) {
                                window.top.location = '/companion/patient/' + patientId + '/';
                                return;
                            }
                            setStatus('There was an issue creating the patient. Please try again.', 'error');
                            setBusy(false);
                        }
                    );
                })
                .catch(function () {
                    setStatus('Network error. Try again.', 'error');
                    setBusy(false);
                });
        }
    });
})();
