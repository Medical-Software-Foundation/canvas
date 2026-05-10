from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import RemoveBannerAlert

from patient_tags.constants import (
    BANNER_KEY_PREFIX,
    DEFAULT_COLOR,
    DEFAULT_SEPARATOR,
    DESCRIPTION_MAX_CHARS,
    PALETTE,
    RULE_ACTION_AUTO_ASSIGN,
    RULE_ACTION_AUTO_REMOVE,
    VALID_INTENTS,
    VALID_PLACEMENTS,
    VALID_RULE_ACTIONS,
)
from patient_tags.models import (
    BannerGroup,
    Label,
    LabelRule,
    PatientLabel,
    PatientLabelAudit,
    PatientProxy,
)


def _serialize_group(group: BannerGroup, label_count: int | None = None) -> dict[str, Any]:
    data = {
        "id": group.dbid,
        "name": group.name,
        "intent": group.intent,
        "placements": list(group.placements or []),
        "separator": group.separator,
        "href": group.href,
    }
    if label_count is not None:
        data["label_count"] = label_count
    return data


def _serialize_label(label: Label, banner_group_name: str | None = None) -> dict[str, Any]:
    return {
        "id": label.dbid,
        "name": label.name,
        "description": label.description,
        "color": label.color,
        "assignable_in_chart": label.assignable_in_chart,
        "assignable_in_profile": label.assignable_in_profile,
        "banner_group_id": label.banner_group_id,
        "banner_group_name": banner_group_name,
    }


def _resolve_group_name(banner_group_id: int | None) -> str | None:
    if not banner_group_id:
        return None
    name = (
        BannerGroup.objects
        .filter(dbid=banner_group_id)
        .values_list("name", flat=True)
        .first()
    )
    return str(name) if name else None


def list_banner_groups() -> list[dict[str, Any]]:
    groups = list(BannerGroup.objects.all().order_by("name"))
    if not groups:
        return []
    counts: dict[int, int] = {}
    for gid in (
        Label.objects
        .filter(banner_group_id__in=[g.dbid for g in groups])
        .values_list("banner_group_id", flat=True)
    ):
        counts[gid] = counts.get(gid, 0) + 1
    return [_serialize_group(g, label_count=counts.get(g.dbid, 0)) for g in groups]


def create_banner_group(
    name: str,
    intent: str = "info",
    placements: list[str] | None = None,
    separator: str = DEFAULT_SEPARATOR,
    href: str = "",
) -> dict[str, Any]:
    placements = placements or ["CHART"]
    _validate_group_inputs(name, intent, placements)
    _require_safe_href(href)
    clean_name = name.strip()
    if BannerGroup.objects.filter(name=clean_name).exists():
        raise ValueError(f"A banner named {clean_name!r} already exists")
    group = BannerGroup.objects.create(
        name=clean_name,
        intent=intent,
        placements=placements,
        separator=separator,
        href=href,
    )
    return _serialize_group(group)


def update_banner_group(group_id: int, **fields: Any) -> dict[str, Any]:
    group = BannerGroup.objects.get(dbid=group_id)
    if "name" in fields:
        _require_nonempty(fields["name"], "name")
        clean_name = fields["name"].strip()
        if (
            clean_name != group.name
            and BannerGroup.objects.filter(name=clean_name).exclude(dbid=group_id).exists()
        ):
            raise ValueError(f"A banner named {clean_name!r} already exists")
        group.name = clean_name
    if "intent" in fields:
        _require_in(fields["intent"], VALID_INTENTS, "intent")
        group.intent = fields["intent"]
    if "placements" in fields:
        _require_placements(fields["placements"])
        group.placements = fields["placements"]
    if "separator" in fields:
        group.separator = fields["separator"]
    if "href" in fields:
        href_value = fields["href"] or ""
        _require_safe_href(href_value)
        group.href = href_value
    group.save()
    return _serialize_group(group)


def delete_banner_group(group_id: int) -> list[Effect]:
    """Delete a banner group, unset banner_group on its labels, and emit a
    RemoveBannerAlert for every patient currently displaying this group's
    banner. Once the group row is gone, compute_banner_effects can no
    longer find the key to reconcile, so this one-shot cleanup is required
    to prevent stale clinical banners (e.g. a red Banned alert) from
    lingering on patient charts forever.

    Returns the list of effects the caller should include in its API
    response so Canvas processes the cleanup.
    """
    # Capture the affected patient UUIDs BEFORE we sever the FK. Two-step
    # query (label_ids → patient UUIDs) avoids a chained label__banner_group_id
    # lookup that would traverse a Canvas-nullable FK.
    label_ids = list(
        Label.objects.filter(banner_group_id=group_id).values_list("dbid", flat=True)
    )
    patient_uuids: list[str] = []
    if label_ids:
        patient_uuids = list(
            PatientLabel.objects
            .filter(label_id__in=label_ids)
            .values_list("patient__id", flat=True)
            .distinct()
        )

    Label.objects.filter(banner_group_id=group_id).update(banner_group=None)
    BannerGroup.objects.filter(dbid=group_id).delete()

    key = f"{BANNER_KEY_PREFIX}{group_id}"
    return [
        RemoveBannerAlert(patient_id=str(uuid), key=key).apply()
        for uuid in patient_uuids
    ]


def list_labels() -> list[dict[str, Any]]:
    labels = list(Label.objects.order_by("name"))
    if not labels:
        return []
    group_ids = {l.banner_group_id for l in labels if l.banner_group_id}
    group_names: dict[int, str] = (
        dict(BannerGroup.objects.filter(dbid__in=group_ids).values_list("dbid", "name"))
        if group_ids else {}
    )
    return [_serialize_label(l, group_names.get(l.banner_group_id)) for l in labels]


def create_label(
    name: str,
    description: str = "",
    color: str = DEFAULT_COLOR,
    assignable_in_chart: bool = True,
    assignable_in_profile: bool = True,
    banner_group_id: int | None = None,
) -> dict[str, Any]:
    _validate_label_inputs(name, description, color)
    clean_name = name.strip()
    if Label.objects.filter(name=clean_name).exists():
        raise ValueError(f"A label named {clean_name!r} already exists")
    label = Label.objects.create(
        name=clean_name,
        description=description,
        color=color,
        assignable_in_chart=assignable_in_chart,
        assignable_in_profile=assignable_in_profile,
        banner_group_id=banner_group_id,
    )
    return _serialize_label(label, _resolve_group_name(label.banner_group_id))


def update_label(
    label_id: int, **fields: Any
) -> tuple[dict[str, Any], list[Effect]]:
    """Update a label and return (serialized_label, banner_reconcile_effects).

    When `name` or `banner_group_id` changes, banners on patients who have
    this label assigned go stale (the joined-name narrative or the
    containing-group attribution). Reconcile each affected patient by
    re-running compute_banner_effects so Canvas updates the rendered
    banners immediately rather than waiting for the next PATIENT_UPDATED.
    """
    label = Label.objects.get(dbid=label_id)
    # Treat any touch of `name` / `banner_group_id` as banner-relevant. A
    # no-op same-value update triggers an extra reconcile, which is cheap
    # (per-patient query bounded by group size).
    banner_relevant = "name" in fields or "banner_group_id" in fields
    if "name" in fields:
        _require_nonempty(fields["name"], "name")
        clean_name = fields["name"].strip()
        if (
            clean_name != label.name
            and Label.objects.filter(name=clean_name).exclude(dbid=label_id).exists()
        ):
            raise ValueError(f"A label named {clean_name!r} already exists")
        label.name = clean_name
    if "description" in fields:
        _require_max_length(fields["description"], DESCRIPTION_MAX_CHARS, "description")
        label.description = fields["description"]
    if "color" in fields:
        _require_in(fields["color"], list(PALETTE.keys()), "color")
        label.color = fields["color"]
    if "assignable_in_chart" in fields:
        label.assignable_in_chart = bool(fields["assignable_in_chart"])
    if "assignable_in_profile" in fields:
        label.assignable_in_profile = bool(fields["assignable_in_profile"])
    if "banner_group_id" in fields:
        label.banner_group_id = fields["banner_group_id"]
    label.save()

    effects: list[Effect] = []
    if banner_relevant:
        effects = _reconcile_banners_for_label(label_id)
    return (
        _serialize_label(label, _resolve_group_name(label.banner_group_id)),
        effects,
    )


def delete_label(label_id: int) -> list[Effect]:
    """Delete a label, its rules, and its assignments. Reconcile banners on
    every affected patient so the deleted label's name doesn't linger in any
    banner-group narrative until the next PATIENT_UPDATED for each patient.
    """
    # Capture affected UUIDs BEFORE the assignment rows are removed, so the
    # subsequent reconcile reaches the right population.
    affected_uuids = list(
        PatientLabel.objects.filter(label_id=label_id)
        .values_list("patient__id", flat=True)
        .distinct()
    )

    PatientLabel.objects.filter(label_id=label_id).delete()
    # Clean up any rules where this label is the trigger or target.
    LabelRule.objects.filter(trigger_label_id=label_id).delete()
    LabelRule.objects.filter(target_label_id=label_id).delete()
    Label.objects.filter(dbid=label_id).delete()

    return _compute_banner_effects_for(affected_uuids)


def _reconcile_banners_for_label(label_id: int) -> list[Effect]:
    """Run compute_banner_effects for every patient who has this label.

    Used by update_label when a banner-relevant field changed.
    """
    affected_uuids = list(
        PatientLabel.objects.filter(label_id=label_id)
        .values_list("patient__id", flat=True)
        .distinct()
    )
    return _compute_banner_effects_for(affected_uuids)


def _compute_banner_effects_for(patient_uuids: list[str]) -> list[Effect]:
    # Local import avoids any chance of an import cycle through banner_service
    # (which only depends on models, not on label_service). Pulled into one
    # helper so the loop body lives in one place across update/delete paths.
    from patient_tags.services.banner_service import compute_banner_effects

    effects: list[Effect] = []
    for uuid in patient_uuids:
        effects.extend(compute_banner_effects(str(uuid)))
    return effects


def get_patient_assignment_ids(patient_id: str) -> list[int]:
    return list(
        PatientLabel.objects
        .filter(patient__id=patient_id)
        .values_list("label_id", flat=True)
    )


def save_patient_assignments(
    patient_id: str,
    label_ids: list[int],
    actor_id: str = "",
    actor_name: str = "",
) -> None:
    """Replace this patient's label assignments with the given set of label IDs.

    After applying the user's desired set, fires LabelRule effects for any
    labels that were freshly assigned (transitioned from absent to present).
    Rules run a single pass — labels added by rule cascades do NOT re-trigger
    rules. Each transition (manual + rule-induced) is recorded in
    PatientLabelAudit so the history view can show who did what.
    """
    patient = PatientProxy.objects.get(id=patient_id)
    desired = set(label_ids)

    # Validate IDs exist before any writes. Without this, an unknown ID hits
    # the FK constraint mid-loop → uncaught IntegrityError → 500 + partial
    # commit + missing audit row. Mirrors add_patient_assignments.
    if desired:
        valid_ids = set(
            Label.objects.filter(dbid__in=desired).values_list("dbid", flat=True)
        )
        unknown = [lid for lid in desired if lid not in valid_ids]
        if unknown:
            raise ValueError(f"Unknown label IDs: {unknown}")

    existing_qs = PatientLabel.objects.filter(patient=patient)
    existing = {pl.label_id: pl for pl in existing_qs}

    to_delete = [pl for label_id, pl in existing.items() if label_id not in desired]
    to_create = [label_id for label_id in desired if label_id not in existing]

    if to_delete:
        PatientLabel.objects.filter(
            dbid__in=[pl.dbid for pl in to_delete]
        ).delete()
    for label_id in to_create:
        PatientLabel.objects.create(patient=patient, label_id=label_id)

    _write_assignment_audits(
        patient_uuid=patient_id,
        added_ids=to_create,
        removed_ids=[pl.label_id for pl in to_delete],
        via="manual",
        actor_id=actor_id,
        actor_name=actor_name,
    )

    if to_create:
        _apply_rules_for_triggers(
            patient,
            to_create,
            patient_uuid=patient_id,
            actor_id=actor_id,
            actor_name=actor_name,
        )


def add_patient_assignments(
    patient_id: str,
    label_ids: list[int],
    actor_id: str = "",
    actor_name: str = "",
) -> dict[str, list[int]]:
    """Add labels to a patient without disturbing existing assignments.

    Idempotent — labels already assigned are silently skipped. Triggers rule
    cascades for newly-added labels (same as save_patient_assignments).
    Returns {"added": [...], "already_present": [...]}.
    """
    # Dedupe at the entry. Without this, [1, 1] passes through to a per-row
    # create() loop where the second insert violates `unique_patient_label`
    # → uncaught IntegrityError → 500 + partial commit + missing audit row.
    label_ids = list(dict.fromkeys(label_ids))
    patient = PatientProxy.objects.get(id=patient_id)
    current = set(
        PatientLabel.objects.filter(patient=patient).values_list("label_id", flat=True)
    )
    to_add = [lid for lid in label_ids if lid not in current]
    already = [lid for lid in label_ids if lid in current]

    if to_add:
        valid_ids = set(Label.objects.filter(dbid__in=to_add).values_list("dbid", flat=True))
        unknown = [lid for lid in to_add if lid not in valid_ids]
        if unknown:
            raise ValueError(f"Unknown label IDs: {unknown}")
        for label_id in to_add:
            PatientLabel.objects.create(patient=patient, label_id=label_id)
        _write_assignment_audits(
            patient_uuid=patient_id,
            added_ids=to_add,
            removed_ids=[],
            via="manual",
            actor_id=actor_id,
            actor_name=actor_name,
        )
        _apply_rules_for_triggers(
            patient, to_add,
            patient_uuid=patient_id,
            actor_id=actor_id,
            actor_name=actor_name,
        )

    return {"added": to_add, "already_present": already}


def remove_patient_assignments(
    patient_id: str,
    label_ids: list[int],
    actor_id: str = "",
    actor_name: str = "",
) -> dict[str, list[int]]:
    """Remove labels from a patient. Idempotent — labels not currently
    assigned are silently skipped. Does NOT trigger rules (rules fire on
    assignment only, by design). Returns {"removed": [...], "not_present": [...]}.
    """
    # Dedupe at the entry so duplicate input doesn't produce duplicate audit
    # rows (the bulk delete is already idempotent, but the audit log isn't).
    label_ids = list(dict.fromkeys(label_ids))
    patient = PatientProxy.objects.get(id=patient_id)
    current = set(
        PatientLabel.objects.filter(patient=patient).values_list("label_id", flat=True)
    )
    to_remove = [lid for lid in label_ids if lid in current]
    not_present = [lid for lid in label_ids if lid not in current]

    if to_remove:
        PatientLabel.objects.filter(
            patient=patient, label_id__in=to_remove
        ).delete()
        _write_assignment_audits(
            patient_uuid=patient_id,
            added_ids=[],
            removed_ids=to_remove,
            via="manual",
            actor_id=actor_id,
            actor_name=actor_name,
        )

    return {"removed": to_remove, "not_present": not_present}


def _apply_rules_for_triggers(
    patient: PatientProxy,
    trigger_ids: list[int],
    patient_uuid: str = "",
    actor_id: str = "",
    actor_name: str = "",
) -> None:
    """Apply LabelRules whose trigger is in the just-assigned set.

    Single pass — does not re-trigger on rule-induced changes. If a target is
    both auto_assign'd and auto_remove'd by overlapping rules, auto_remove wins.
    Cascaded changes are written to the audit log with via="rule".
    """
    rules = list(LabelRule.objects.filter(trigger_label_id__in=trigger_ids))
    if not rules:
        return

    auto_assign_targets: set[int] = set()
    auto_remove_targets: set[int] = set()
    for rule in rules:
        if rule.action == RULE_ACTION_AUTO_ASSIGN:
            auto_assign_targets.add(rule.target_label_id)
        elif rule.action == RULE_ACTION_AUTO_REMOVE:
            auto_remove_targets.add(rule.target_label_id)

    auto_assign_targets -= auto_remove_targets

    current = set(
        PatientLabel.objects
        .filter(patient=patient)
        .values_list("label_id", flat=True)
    )
    new_assigns = auto_assign_targets - current
    new_removes = auto_remove_targets & current

    if new_removes:
        PatientLabel.objects.filter(patient=patient, label_id__in=new_removes).delete()
    for label_id in new_assigns:
        PatientLabel.objects.create(patient=patient, label_id=label_id)

    _write_assignment_audits(
        patient_uuid=patient_uuid,
        added_ids=list(new_assigns),
        removed_ids=list(new_removes),
        via="rule",
        actor_id=actor_id,
        actor_name=actor_name,
    )


def _write_assignment_audits(
    patient_uuid: str,
    added_ids: list[int],
    removed_ids: list[int],
    via: str,
    actor_id: str,
    actor_name: str,
) -> None:
    """Append audit rows for each label transition in this save."""
    if not added_ids and not removed_ids:
        return

    touched_ids = set(added_ids) | set(removed_ids)
    label_meta = {
        l["dbid"]: l
        for l in Label.objects.filter(dbid__in=touched_ids).values("dbid", "name", "color")
    }

    def meta_for(lid: int) -> tuple[str, str]:
        m = label_meta.get(lid)
        if not m:
            return (f"label #{lid}", "blue")
        return (m["name"], m["color"])

    for lid in added_ids:
        name, color = meta_for(lid)
        PatientLabelAudit.objects.create(
            patient_uuid=patient_uuid,
            label_id=lid,
            label_name=name,
            label_color=color,
            action="assigned",
            via=via,
            actor_id=actor_id,
            actor_name=actor_name,
        )
    for lid in removed_ids:
        name, color = meta_for(lid)
        PatientLabelAudit.objects.create(
            patient_uuid=patient_uuid,
            label_id=lid,
            label_name=name,
            label_color=color,
            action="removed",
            via=via,
            actor_id=actor_id,
            actor_name=actor_name,
        )


def list_patient_history(patient_uuid: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent label-assignment audit entries for a patient, newest first."""
    rows = (
        PatientLabelAudit.objects
        .filter(patient_uuid=patient_uuid)
        .order_by("-at")
        .values("label_id", "label_name", "label_color", "action", "via",
                "actor_name", "actor_id", "at")[:limit]
    )
    return [
        {
            "label_id": r["label_id"],
            "label_name": r["label_name"],
            "label_color": r["label_color"],
            "action": r["action"],
            "via": r["via"],
            "actor_name": r["actor_name"] or "Unknown",
            "actor_id": r["actor_id"],
            "at": r["at"].isoformat() if r["at"] else "",
        }
        for r in rows
    ]


# ── Rule CRUD ─────────────────────────────────────────────────────────────


def _serialize_rule(rule: LabelRule, target_name: str | None = None) -> dict[str, Any]:
    return {
        "id": rule.dbid,
        "trigger_label_id": rule.trigger_label_id,
        "action": rule.action,
        "target_label_id": rule.target_label_id,
        "target_label_name": target_name,
    }


def list_rules_for_label(label_id: int) -> list[dict[str, Any]]:
    """Rules where the given label is the trigger."""
    rules = list(LabelRule.objects.filter(trigger_label_id=label_id))
    if not rules:
        return []
    target_ids = {r.target_label_id for r in rules}
    target_names = dict(
        Label.objects.filter(dbid__in=target_ids).values_list("dbid", "name")
    )
    return [_serialize_rule(r, target_names.get(r.target_label_id)) for r in rules]


def create_rule(trigger_label_id: int, action: str, target_label_id: int) -> dict[str, Any]:
    _require_in(action, VALID_RULE_ACTIONS, "action")
    if trigger_label_id == target_label_id:
        raise ValueError("Trigger and target must be different labels.")
    if not Label.objects.filter(dbid=trigger_label_id).exists():
        raise ValueError("Trigger label does not exist.")
    if not Label.objects.filter(dbid=target_label_id).exists():
        raise ValueError("Target label does not exist.")
    if LabelRule.objects.filter(
        trigger_label_id=trigger_label_id,
        action=action,
        target_label_id=target_label_id,
    ).exists():
        raise ValueError("This rule already exists.")
    # Conflict: same trigger + target with the opposing action would behave
    # contradictorily at runtime. Block at creation; user must remove the
    # existing rule first.
    opposing = (
        RULE_ACTION_AUTO_REMOVE if action == RULE_ACTION_AUTO_ASSIGN
        else RULE_ACTION_AUTO_ASSIGN
    )
    opposing_label = "Auto-remove" if opposing == RULE_ACTION_AUTO_REMOVE else "Auto-assign"
    if LabelRule.objects.filter(
        trigger_label_id=trigger_label_id,
        action=opposing,
        target_label_id=target_label_id,
    ).exists():
        raise ValueError(
            f"Conflict: There is already an {opposing_label} rule for that label. "
            "Remove the existing rule first."
        )
    rule = LabelRule.objects.create(
        trigger_label_id=trigger_label_id,
        action=action,
        target_label_id=target_label_id,
    )
    target_name = Label.objects.filter(dbid=target_label_id).values_list("name", flat=True).first()
    return _serialize_rule(rule, str(target_name) if target_name else None)


def delete_rule(rule_id: int) -> None:
    LabelRule.objects.filter(dbid=rule_id).delete()


def _validate_label_inputs(name: str, description: str, color: str) -> None:
    _require_nonempty(name, "name")
    _require_max_length(description, DESCRIPTION_MAX_CHARS, "description")
    _require_in(color, list(PALETTE.keys()), "color")


def _validate_group_inputs(name: str, intent: str, placements: list[str]) -> None:
    _require_nonempty(name, "name")
    _require_in(intent, VALID_INTENTS, "intent")
    _require_placements(placements)


def _require_nonempty(value: str, field: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field} is required")


def _require_max_length(value: str, max_len: int, field: str) -> None:
    if value and len(value) > max_len:
        raise ValueError(f"{field} exceeds {max_len} characters")


def _require_in(value: str, allowed: list[str], field: str) -> None:
    if value not in allowed:
        raise ValueError(f"{field} must be one of {allowed}")


def _require_placements(placements: list[str]) -> None:
    if not placements:
        raise ValueError("placements must include at least one value")
    for p in placements:
        if p not in VALID_PLACEMENTS:
            raise ValueError(f"placement {p!r} not in {VALID_PLACEMENTS}")


def _require_safe_href(value: str) -> None:
    """Reject href values that would execute code when rendered as an anchor.

    Allows: empty, http(s)://… absolute URLs, /relative or ./relative paths.
    Rejects: javascript:, data:, vbscript:, file:, and anything else that
    looks like a non-http(s) scheme — these would run as same-origin script
    in the chart context if a clinician clicks the rendered link.
    """
    if not value:
        return
    stripped = value.strip()
    if not stripped:
        return
    lowered = stripped.lower()
    if lowered.startswith(("http://", "https://")):
        return
    # Treat as relative path if there is no scheme separator before any slash.
    first_segment = lowered.split("/", 1)[0]
    if ":" not in first_segment:
        return
    raise ValueError(
        "href must be empty, an http(s):// URL, or a relative path"
    )
