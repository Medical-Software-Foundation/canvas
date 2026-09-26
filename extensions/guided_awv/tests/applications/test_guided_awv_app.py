"""Tests for GuidedAWVApp NoteApplication handler."""

from unittest.mock import MagicMock, patch

from guided_awv.applications.guided_awv_app import GuidedAWVApp


def _make_app(context: dict | None = None) -> GuidedAWVApp:
    """Instantiate GuidedAWVApp with a mock event carrying *context*."""
    event = MagicMock()
    event.context = context or {}
    event.target.id = "patient-target-id"
    app = GuidedAWVApp.__new__(GuidedAWVApp)
    app.event = event
    return app


def _mock_note(
    system: str = "SNOMED",
    code: str = "401131001",
    uuid: str = "note-uuid-789",
) -> MagicMock:
    """Build a mock Note whose note_type_version has the given system/code."""
    note = MagicMock()
    note.id = uuid
    note.note_type_version.system = system
    note.note_type_version.code = code
    return note


def _patch_note_module(note_cls: MagicMock):
    """Patch the canvas_sdk.v1.data.note module with a Note class mock."""
    return patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.note": MagicMock(Note=note_cls)},
    )


class TestVisible:
    """Tests for GuidedAWVApp.visible() - filters by SNOMED 401131001."""

    def test_returns_false_when_no_note_id(self) -> None:
        app = _make_app(context={})
        assert app.visible() is False

    def test_returns_false_when_note_query_raises(self) -> None:
        mock_note_cls = MagicMock()
        mock_note_cls.objects.select_related.return_value.get.side_effect = Exception("not found")
        app = _make_app(context={"note_id": "123"})
        with _patch_note_module(mock_note_cls):
            assert app.visible() is False

    def test_returns_false_for_non_awv_snomed_code(self) -> None:
        """An office visit note (different SNOMED code) should not show the button."""
        mock_note = _mock_note(system="SNOMED", code="185349003")
        mock_note_cls = MagicMock()
        mock_note_cls.objects.select_related.return_value.get.return_value = mock_note

        app = _make_app(context={"note_id": "123"})
        with _patch_note_module(mock_note_cls):
            assert app.visible() is False

    def test_returns_false_when_system_differs(self) -> None:
        """Same code under a different coding system should not match."""
        mock_note = _mock_note(system="LOINC", code="401131001")
        mock_note_cls = MagicMock()
        mock_note_cls.objects.select_related.return_value.get.return_value = mock_note

        app = _make_app(context={"note_id": "123"})
        with _patch_note_module(mock_note_cls):
            assert app.visible() is False

    def test_returns_true_for_awv_snomed_code(self) -> None:
        mock_note = _mock_note(system="SNOMED", code="401131001")
        mock_note_cls = MagicMock()
        mock_note_cls.objects.select_related.return_value.get.return_value = mock_note

        app = _make_app(context={"note_id": "123"})
        with _patch_note_module(mock_note_cls):
            assert app.visible() is True

    def test_returns_false_when_note_type_version_missing(self) -> None:
        mock_note = MagicMock()
        mock_note.note_type_version = None
        mock_note_cls = MagicMock()
        mock_note_cls.objects.select_related.return_value.get.return_value = mock_note

        app = _make_app(context={"note_id": "123"})
        with _patch_note_module(mock_note_cls):
            assert app.visible() is False


class TestHandle:
    """Tests for GuidedAWVApp.handle()."""

    def test_returns_a_list(self) -> None:
        """handle() should return a list of Effect objects without crashing."""
        mock_note = _mock_note()
        mock_note_cls = MagicMock()
        mock_note_cls.objects.get.return_value = mock_note

        mock_module_instance = MagicMock()
        mock_module_instance.is_visible.return_value = True
        mock_module_instance.render.return_value = {
            "section_id": "test_section",
            "title": "Test Section",
        }
        mock_module_instance.render_content_html.return_value = "<p>test</p>"

        mock_module_cls = MagicMock(return_value=mock_module_instance)
        mock_module_cls.__name__ = "MockModule"

        app = _make_app(context={"note_id": "42", "patient_id": "patient-abc"})

        with _patch_note_module(mock_note_cls), patch(
            "guided_awv.modules.ALL_MODULES",
            [mock_module_cls],
        ), patch(
            "guided_awv.api.awv_api._get_all_form_states",
            return_value={},
        ), patch(
            "canvas_sdk.templates.render_to_string",
            return_value="<html>[[modules_html]]</html>",
        ):
            result = app.handle()

        assert isinstance(result, list)
        assert len(result) >= 1

    def test_default_awv_type_is_initial(self) -> None:
        """With no cached selection, modules render with awv_type='initial'."""
        mock_note = _mock_note()
        mock_note_cls = MagicMock()
        mock_note_cls.objects.get.return_value = mock_note

        mock_module_instance = MagicMock()
        mock_module_instance.is_visible.return_value = False
        mock_module_cls = MagicMock(return_value=mock_module_instance)
        mock_module_cls.__name__ = "MockModule"

        app = _make_app(context={"note_id": "42", "patient_id": "patient-abc"})

        with _patch_note_module(mock_note_cls), patch(
            "guided_awv.modules.ALL_MODULES",
            [mock_module_cls],
        ), patch(
            "guided_awv.api.awv_api._get_all_form_states",
            return_value={},
        ), patch(
            "canvas_sdk.templates.render_to_string",
            return_value="<html>stub</html>",
        ):
            app.handle()

        mock_module_cls.assert_called_with(
            note_id="note-uuid-789",
            patient_id="patient-abc",
            awv_type="initial",
        )

    def test_restores_awv_type_subsequent_from_cache(self) -> None:
        """When the form-state cache holds awv_type='subsequent', that value is used."""
        mock_note = _mock_note()
        mock_note_cls = MagicMock()
        mock_note_cls.objects.get.return_value = mock_note

        mock_module_instance = MagicMock()
        mock_module_instance.is_visible.return_value = False
        mock_module_cls = MagicMock(return_value=mock_module_instance)
        mock_module_cls.__name__ = "MockModule"

        app = _make_app(context={"note_id": "42", "patient_id": "patient-abc"})

        with _patch_note_module(mock_note_cls), patch(
            "guided_awv.modules.ALL_MODULES",
            [mock_module_cls],
        ), patch(
            "guided_awv.api.awv_api._get_all_form_states",
            return_value={"_awv_meta": {"awv_type": "subsequent"}},
        ), patch(
            "canvas_sdk.templates.render_to_string",
            return_value="<html>stub</html>",
        ):
            app.handle()

        mock_module_cls.assert_called_with(
            note_id="note-uuid-789",
            patient_id="patient-abc",
            awv_type="subsequent",
        )

    def test_invalid_cached_awv_type_falls_back_to_initial(self) -> None:
        """A garbage cached value should not propagate; default to 'initial'."""
        mock_note = _mock_note()
        mock_note_cls = MagicMock()
        mock_note_cls.objects.get.return_value = mock_note

        mock_module_instance = MagicMock()
        mock_module_instance.is_visible.return_value = False
        mock_module_cls = MagicMock(return_value=mock_module_instance)
        mock_module_cls.__name__ = "MockModule"

        app = _make_app(context={"note_id": "42", "patient_id": "patient-abc"})

        with _patch_note_module(mock_note_cls), patch(
            "guided_awv.modules.ALL_MODULES",
            [mock_module_cls],
        ), patch(
            "guided_awv.api.awv_api._get_all_form_states",
            return_value={"_awv_meta": {"awv_type": "junk"}},
        ), patch(
            "canvas_sdk.templates.render_to_string",
            return_value="<html>stub</html>",
        ):
            app.handle()

        mock_module_cls.assert_called_with(
            note_id="note-uuid-789",
            patient_id="patient-abc",
            awv_type="initial",
        )


class TestTemplateContent:
    """Verify the modal template includes the validation JS, CSS, and toggle wiring.

    The HTML/CSS/JS lives in templates/guided_awv.html (not inlined in the
    Python handler) so these tests read the template file directly.
    """

    @staticmethod
    def _read_template() -> str:
        from pathlib import Path
        # tests/applications/test_guided_awv_app.py -> guided-awv/guided_awv/templates/guided_awv.html
        template_path = (
            Path(__file__).resolve().parent.parent.parent
            / "guided_awv" / "templates" / "guided_awv.html"
        )
        return template_path.read_text()

    def test_validate_section_function_defined(self) -> None:
        src = self._read_template()
        assert "function validateSection(sectionId)" in src

    def test_save_section_calls_validate(self) -> None:
        src = self._read_template()
        assert "validateSection(sectionId)" in src
        assert "Required fields missing" in src

    def test_validation_css_present(self) -> None:
        src = self._read_template()
        assert ".awv-required" in src
        assert ".awv-field--error" in src
        assert ".awv-field-error" in src

    def test_attestation_required_attributes(self) -> None:
        src = self._read_template()
        assert 'name="attestation_face_to_face_time"' in src
        assert 'data-required="true"' in src

    def test_awv_type_toggle_rendered_in_header(self) -> None:
        src = self._read_template()
        assert 'name="awv_type_toggle"' in src
        assert 'value="initial"' in src
        assert 'value="subsequent"' in src

    def test_awv_type_update_function_present(self) -> None:
        src = self._read_template()
        assert "function updateAWVType()" in src
        assert "/awv/awv-type" in src

    def test_save_handlers_use_dynamic_awv_type(self) -> None:
        """saveHRA, saveAssessmentPlan, saveAttestation must read AWV_TYPE at call time."""
        src = self._read_template()
        # Dynamic AWV_TYPE variable used in HRA save body
        assert "awv_type: AWV_TYPE" in src
        # Plan and attestation include awv_cpt_code via getAwvCptCode()
        assert "awv_cpt_code: getAwvCptCode()" in src

    def test_plan_save_endpoints_pass_explicit_section_id(self) -> None:
        """Regression for Claude review finding #3.

        saveAssessmentPlan and saveAttestation both POST to /awv/plan. Without
        an explicit section_id, the handler would clobber form-state across
        the two flows. Both must declare which slot they own.
        """
        src = self._read_template()
        assert "section_id: 'assessmentplan'" in src
        assert "section_id: 'attestation'" in src

    def test_reconstructs_specialist_rows_before_populating(self) -> None:
        """Regression for Claude review finding #11.

        Server renders only ``_specialist_row(0)``. Without re-creating
        rows 1..N from cached form-state, ``populateFormFields`` silently
        dropped specialist_1_*, specialist_2_*, etc. - then the next Save
        Providers overwrote the cached section with the empty DOM and
        permanently destroyed the data. The fix scans for the highest
        ``specialist_<N>_*`` key and calls ``addSpecialistRow()`` N times
        before the value-restore loop.
        """
        src = self._read_template()
        assert "function reconstructSpecialistRows(data)" in src
        # Must be called from populateFormFields for the currentproviders section
        # before the main field-restore loop runs.
        pf_start = src.find("function populateFormFields(sections)")
        pf_end = src.find("\n}", pf_start)
        block = src[pf_start:pf_end + 2]
        assert "reconstructSpecialistRows(sections.currentproviders)" in block
        # The regex used to find the highest specialist index
        assert "specialist_(\\d+)_" in src or "/^specialist_(\\d+)_/" in src

    def test_depression_save_ships_all_cms_fields(self) -> None:
        """Regression for Claude review finding #16 (Depression).

        saveDepressionScreening used to compare `safety_assessed === 'Yes'`
        but the rendered radio values are assessed_no_risk / assessed_safety_plan
        / assessed_crisis_referral / not_assessed - so safety_assessed was
        unconditionally False. suicide_ideation_assessed,
        suicide_ideation_present, depression_treatment_plan, and
        depression_treatment_notes were also never sent.
        """
        src = self._read_template()
        sd_start = src.find("function saveDepressionScreening()")
        sd_end = src.find("\n}", sd_start)
        block = src[sd_start:sd_end + 2]
        # The buggy comparison is gone
        assert "d.safety_assessed === 'Yes'" not in block
        # The new mapping recognizes the actual radio values
        assert "indexOf('assessed_')" in block or "startsWith('assessed_')" in block
        # All previously-dropped fields are shipped
        assert "suicide_ideation_assessed" in block
        assert "suicide_ideation_present" in block
        assert "depression_treatment_plan" in block
        assert "depression_treatment_notes" in block

    def test_acp_save_ships_all_16_rendered_fields(self) -> None:
        """Regression for Claude review finding #16 (ACP).

        saveAdvanceCarePlanning used to ship only 7 of 16 rendered ACP fields,
        dropping acp_total_minutes (the CMS 99497 time-billing key), code_status,
        acp_topics_discussed, healthcare_proxy_contact/_designated,
        documents_completed_today, copy_given_to_patient, documents_scanned_to_chart.
        """
        src = self._read_template()
        acp_start = src.find("function saveAdvanceCarePlanning()")
        acp_end = src.find("\n}", acp_start)
        block = src[acp_start:acp_end + 2]
        # The previously-dropped CMS-billing-time field must be present
        assert "acp_total_minutes" in block
        # And the other 8 previously-dropped fields
        assert "code_status" in block
        assert "acp_topics_discussed" in block
        assert "healthcare_proxy_contact" in block
        assert "healthcare_proxy_designated" in block
        assert "documents_completed_today" in block
        assert "copy_given_to_patient" in block
        assert "documents_scanned_to_chart" in block

    def test_vitals_save_ships_bp_arm_and_position(self) -> None:
        """Regression for Claude review finding #19 (Vitals).

        bp_arm and bp_position are required radios in the vitals module but
        saveVitals used to ship only 5 fields, dropping the CMS-required arm
        + position documentation.
        """
        src = self._read_template()
        sv_start = src.find("function saveVitals()")
        sv_end = src.find("\n}", sv_start)
        block = src[sv_start:sv_end + 2]
        assert "bp_arm: d.bp_arm" in block
        assert "bp_position: d.bp_position" in block

    def test_med_recon_save_ships_medications_reconciled(self) -> None:
        """Regression for Claude review finding #19 (Med Recon).

        medications_reconciled is a required radio that drives CPT II 1111F.
        It used to be missing from the JS save body, so the handler defaulted
        to None and fired 1111F unconditionally.
        """
        src = self._read_template()
        smr_start = src.find("function saveMedicationReconciliation()")
        smr_end = src.find("\n}", smr_start)
        block = src[smr_start:smr_end + 2]
        assert "medications_reconciled: d.medications_reconciled" in block

    def test_save_follow_up_reads_actual_rendered_fields(self) -> None:
        """Regression for Claude review finding #15.

        saveFollowUp JS used to read followup_type / followup_timeframe /
        followup_notes / followup_date - none of which the FollowUpSchedulingModule
        renders. Every Follow-Up save produced a FollowUpCommand with a null
        requested_date and a near-empty comment. The fix updates the JS to
        read the actual rendered field names.
        """
        src = self._read_template()
        sf_start = src.find("function saveFollowUp()")
        sf_end = src.find("\n}", sf_start)
        block = src[sf_start:sf_end + 2]
        # Dead reads are gone
        assert "d.followup_type" not in block
        assert "d.followup_timeframe" not in block
        assert "d.followup_notes" not in block
        assert "d.followup_date" not in block
        # New reads use names the module actually renders
        assert "d.next_awv_date" in block
        assert "d.next_awv_timeframe" in block
        assert "d.primary_care_followup" in block
        assert "d.followup_reason" in block
        assert "d.pending_labs" in block
        assert "d.patient_goals" in block
        # requested_date now sources from next_awv_date (the real field)
        assert "requested_date: d.next_awv_date" in block

    def test_dx_search_uses_safe_dom_apis(self) -> None:
        """Regression for Claude review finding #12 (site 1).

        The diagnosis-search result rows previously built via
        ``innerHTML +=`` and string-interpolated icd10_code / icd10_text -
        a half-escaped peer of the pharmacy-search XSS that v0.14.6 fixed.
        Rebuild via createElement + textContent + addEventListener.
        """
        src = self._read_template()
        # The dangerous patterns from the old code are gone.
        # Note: there are still innerHTML uses elsewhere in the template that
        # are pre-existing and reviewed safe; we specifically guard the dx
        # search block.
        dx_start = src.find("if (dxSearchInput)")
        dx_end = src.find("function selectCondition(", dx_start)
        block = src[dx_start:dx_end]
        # Old pattern: innerHTML = '...<div class="dx-result-item"...>...' with
        # string-concatenated icd10_code / icd10_text. Gone.
        assert "dxResultsDiv.innerHTML = html;" not in block
        assert "icd10_text.replace(/\"/g," not in block
        # New pattern present
        assert "document.createElement('div')" in block
        assert "dataset.code" in block
        assert "dataset.text" in block

    def test_saveHRA_does_not_prefix_filter_form_fields(self) -> None:
        """Regression for Claude review finding #9 Bug B1.

        saveHRA used to filter form fields by ``key.indexOf('hra_') === 0``,
        which dropped every actual HRA input (tobacco_use, alcohol_use,
        exercise_days, food_security, housing_stability, etc. - all declared
        bare in modules/hra.py without a prefix). The handler's CPT II logic
        was effectively dead in production because nothing it looked for ever
        reached the server. The fix forwards every field except meta keys
        (note_id, _form_fields, _last_saved).
        """
        src = self._read_template()
        sh_start = src.find("function saveHRA()")
        sh_end = src.find("\n}", sh_start)
        block = src[sh_start:sh_end + 2]
        # The bad prefix filter must be gone.
        assert "key.indexOf('hra_') === 0" not in block
        # The correct meta-keys allowlist is in place.
        assert "META_KEYS" in block
        assert "note_id: 1" in block
        assert "_form_fields: 1" in block

    def test_pending_pharmacies_only_clear_on_success(self) -> None:
        """Regression for Claude review finding #6.

        The previous saveCurrentProviders scheduled
        ``setTimeout(clearPendingPharmacies, 500)`` inside the transformFn
        callback. transformFn runs synchronously *before* apiPost is fired,
        so the timer always elapsed - on a 4xx/5xx, network error, or
        validation failure, the pending pharmacy UI was silently wiped and
        the additions were never persisted.

        Fix: saveSection now accepts an onSuccess callback that only fires
        after the server confirms ``success: true``. saveCurrentProviders
        passes clearPendingPharmacies as the onSuccess hook. The bad
        setTimeout pattern must be gone, and the onSuccess wiring must be
        present.
        """
        src = self._read_template()
        # The unconditional timer is gone.
        assert "setTimeout(clearPendingPharmacies" not in src
        # saveSection now threads onSuccess and saveCurrentProviders uses it.
        assert "saveSection(sectionId, endpoint, transformFn, onSuccess)" in src
        assert "clearPendingPharmacies()" in src
        # The clear is inside saveCurrentProviders' onSuccess callback - not
        # in the transformFn body. Asserting the structural shape via a
        # multi-line slice would be brittle, so instead require both the
        # function-shaped onSuccess block and that the clear happens after
        # the transform return.
        sc_start = src.find("function saveCurrentProviders()")
        sc_end = src.find("}\n}", sc_start)
        block = src[sc_start:sc_end + 3]
        # transformFn return + onSuccess callback should both be present
        assert "new_preferred_pharmacies: getPendingPharmacies()" in block
        assert "function(result) {" in block
        assert "clearPendingPharmacies()" in block

    def test_pharmacy_search_uses_safe_dom_apis_not_inline_onclick(self) -> None:
        """Regression for Claude review finding #1.

        The previous searchPharmacies / setPendingPharmacies built result rows
        by concatenating user-derived strings into inline onclick="..." HTML
        attributes and innerHTML. A pharmacy name with an apostrophe (Macy's,
        O'Reilly) would break the JS string literal, and a name containing <
        or & would render as live HTML. This test asserts the DOM-API rewrite:
        - no inline onclick referencing selectPharmacy / removePendingPharmacy
        - results built via createElement / textContent
        """
        src = self._read_template()
        # The dangerous interpolated-onclick patterns must be gone.
        assert "onclick=\"selectPharmacy('" not in src
        assert "onclick=\"removePendingPharmacy('" not in src
        assert "onclick='selectPharmacy(" not in src
        # The DOM-API building blocks must be present.
        assert "document.createElement('div')" in src
        assert ".textContent" in src
        # The selectPharmacy / removePendingPharmacy bindings happen via addEventListener
        # reading from this.dataset, not via string interpolation.
        assert "addEventListener('click'" in src
        assert "this.dataset.ncpdp" in src

    def test_template_has_substitution_placeholders(self) -> None:
        """The template must declare the [[var]] placeholders the handler replaces."""
        src = self._read_template()
        for placeholder in (
            "[[awv_label]]",
            "[[modules_html]]",
            "[[note_uuid]]",
            "[[patient_id]]",
            "[[awv_type]]",
            "[[initial_checked]]",
            "[[subsequent_checked]]",
        ):
            assert placeholder in src, f"missing {placeholder} in template"

    def test_template_has_commit_all_commands_directions(self) -> None:
        """Attestation section must explain how to finalize the AWV (Note tab + Commit all commands)."""
        src = self._read_template()
        assert "Next steps to finalize this AWV" in src
        assert "Commit all commands" in src
        # Canvas's commit button is at the bottom of the note - guard against
        # accidentally telling the user to look at the top.
        assert "bottom of the note" in src
        assert "top of the note" not in src

    def test_template_has_no_doubled_backslash_escapes(self) -> None:
        r"""Regression: when the HTML was extracted from a Python f-string, doubled
        backslashes (e.g. '\\D' in a regex, '\\n' in a join) were preserved as
        literal two-char sequences instead of being un-escaped. That broke the
        phone-number formatter (\\D didn't match non-digits) and the narrative
        joiners (literal '\\n' instead of newlines). This test guards against
        any such doubled-escape sneaking back in.
        """
        src = self._read_template()
        for pattern, why in (
            (r"\\D", "JS regex non-digit (phone formatter)"),
            (r"\\b", "JS regex word boundary"),
            (r"\\w", "JS regex word char"),
            (r"\\n", "newline join separator"),
        ):
            assert pattern not in src, f"doubled backslash {pattern!r} still in template ({why})"
