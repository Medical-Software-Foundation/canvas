(function () {
    var API_BASE = '/plugin-io/api/provider_patient_profile_companion/app';

    var state = {
        patientId: '',
        fields: null,
        options: null,
        saving: false,
        loadError: null,
    };

    function getPatientId() {
        var params = new URLSearchParams(window.location.search);
        return (params.get('patient_id') || '').trim();
    }

    // ---------- fetch helpers ----------

    function fetchData() {
        var url = API_BASE + '/data.json?patient_id=' + encodeURIComponent(state.patientId);
        return fetch(url).then(function (res) {
            if (!res.ok) throw new Error('data.json ' + res.status);
            return res.json();
        });
    }

    function postSave(payload) {
        return fetch(API_BASE + '/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (res) {
            return res.json().then(function (body) { return { ok: res.ok, body: body }; });
        });
    }

    // ---------- DOM helpers ----------

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        if (attrs) {
            Object.keys(attrs).forEach(function (k) {
                if (k === 'className') node.className = attrs[k];
                else if (k === 'text') node.textContent = attrs[k];
                else if (k.indexOf('on') === 0) node.addEventListener(k.slice(2), attrs[k]);
                else node.setAttribute(k, attrs[k]);
            });
        }
        (children || []).forEach(function (c) {
            if (c == null) return;
            node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
        });
        return node;
    }

    function readTextInput(id) {
        var input = document.getElementById(id);
        return input ? input.value : '';
    }

    function collectFields() {
        return {
            first_name: readTextInput('first_name'),
            middle_name: readTextInput('middle_name'),
            last_name: readTextInput('last_name'),
            prefix: readTextInput('prefix'),
            suffix: readTextInput('suffix'),
            nickname: readTextInput('nickname'),
            birthdate: readTextInput('birthdate'),
            sex_at_birth: readTextInput('sex_at_birth'),
            social_security_number: readTextInput('social_security_number'),
        };
    }

    // ---------- form layout (flat) ----------

    function textField(id, label, value) {
        return el('div', { className: 'field' }, [
            el('label', { for: id, text: label }),
            el('input', { type: 'text', id: id, value: value || '' }),
        ]);
    }

    function fieldRow(left, right) {
        return el('div', { className: 'field-row' }, [left, right]);
    }

    function buildFields() {
        var f = state.fields;
        var sexOptions = (state.options && state.options.sex_at_birth) || [];

        var sexSelect = el('select', { id: 'sex_at_birth' },
            sexOptions.map(function (opt) {
                var attrs = { value: opt.value };
                if (opt.value === (f.sex_at_birth || '')) attrs.selected = 'selected';
                return el('option', attrs, [opt.label]);
            })
        );

        var birthdateInput = el('input', {
            type: 'date', id: 'birthdate', value: f.birthdate || '',
        });

        return [
            fieldRow(
                textField('first_name', 'First name', f.first_name),
                textField('last_name', 'Last name', f.last_name),
            ),
            fieldRow(
                textField('middle_name', 'Middle name', f.middle_name),
                textField('nickname', 'Preferred name', f.nickname),
            ),
            fieldRow(
                textField('prefix', 'Prefix', f.prefix),
                textField('suffix', 'Suffix', f.suffix),
            ),
            fieldRow(
                el('div', { className: 'field' }, [
                    el('label', { for: 'birthdate', text: 'Date of birth' }),
                    birthdateInput,
                ]),
                el('div', { className: 'field' }, [
                    el('label', { for: 'sex_at_birth', text: 'Sex at birth' }),
                    sexSelect,
                ]),
            ),
            fieldRow(
                textField('social_security_number', 'Social Security Number', f.social_security_number),
                el('div'),
            ),
        ];
    }

    // ---------- save ----------

    function showSaveError(message) {
        var banner = document.getElementById('save_status');
        if (!banner) return;
        banner.className = 'banner error';
        banner.textContent = message;
        banner.style.display = '';
    }

    function showSaveSuccess() {
        var banner = document.getElementById('save_status');
        if (!banner) return;
        banner.className = 'banner';
        banner.textContent = 'Saved.';
        banner.style.display = '';
        setTimeout(function () {
            if (banner.textContent === 'Saved.') banner.style.display = 'none';
        }, 2500);
    }

    function onSave() {
        if (state.saving) return;
        state.saving = true;
        var initialBtn = document.getElementById('save_button');
        if (initialBtn) initialBtn.disabled = true;

        var payload = { patient_id: state.patientId, fields: collectFields() };
        postSave(payload).then(function (result) {
            if (!result.ok) {
                showSaveError((result.body && result.body.error) || 'Save failed.');
                return;
            }
            // Save succeeded. Refresh the form from the server, then show
            // "Saved." *after* the re-render — otherwise renderAll wipes the
            // banner. If the refetch itself fails, the save was still applied
            // server-side, so still show success rather than a misleading
            // failure banner.
            return fetchData()
                .then(applyServerData)
                .then(renderAll)
                .then(showSaveSuccess, showSaveSuccess);
        }).catch(function () {
            // Reached only if postSave itself rejected (network drop). The
            // refetch chain above swallows its own errors, so this can't
            // mistakenly fire on a successful save with a flaky GET.
            showSaveError('Save failed — network error.');
        }).finally(function () {
            state.saving = false;
            // renderAll may have replaced the original button — re-resolve.
            var liveBtn = document.getElementById('save_button');
            if (liveBtn) liveBtn.disabled = false;
        });
    }

    // ---------- top-level render ----------

    function applyServerData(payload) {
        state.fields = payload.fields || {};
        state.options = payload.options || {};
    }

    function renderAll() {
        var root = document.getElementById('root');
        root.textContent = '';

        if (state.loadError) {
            root.appendChild(el('div', { className: 'banner error', text: state.loadError }));
            return;
        }

        var saveStatus = el('div', { id: 'save_status', className: 'banner', style: 'display:none;' });
        root.appendChild(saveStatus);

        root.appendChild(el('div', { className: 'form-body' }, buildFields()));

        var saveBtn = el('button', {
            type: 'button',
            id: 'save_button',
            className: 'btn btn-primary',
            text: 'Save',
            onclick: onSave,
        });
        root.appendChild(el('div', { className: 'actions' }, [saveBtn]));
    }

    // ---------- boot ----------

    document.addEventListener('DOMContentLoaded', function () {
        state.patientId = getPatientId();
        if (!state.patientId) {
            document.getElementById('root').textContent = 'Missing patient context.';
            return;
        }

        fetchData().then(function (payload) {
            applyServerData(payload);
            renderAll();
        }).catch(function () {
            state.loadError = 'Failed to load patient profile. Close and try again.';
            renderAll();
        });
    });
})();
