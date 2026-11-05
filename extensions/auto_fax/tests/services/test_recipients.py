from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from auto_fax.services.config import RecipientSpec, Rule
from auto_fax.services.recipients import Recipient, resolve_recipients

PCP = "446050000"
REFERRING = "3842006"
TODAY = date(2026, 11, 2)


def _rule(name, *specs):
    return Rule(
        name=name,
        note_type_codes=frozenset({"*"}),
        trigger_states=frozenset({"LKD"}),
        recipients=tuple(specs),
    )


def _membership(role_code, object_id):
    return SimpleNamespace(
        role_code=role_code, organizational_entity=SimpleNamespace(object_id=object_id)
    )


def _provider(
    dbid, first="Pat", last="Lee", practice="", fax="555-234-0100", active=True
):
    return SimpleNamespace(
        dbid=dbid,
        first_name=first,
        last_name=last,
        practice_name=practice,
        business_fax=fax,
        is_active=active,
    )


def _facility_address(name="Oak House", fax="5552340111", active=True):
    return SimpleNamespace(
        facility=SimpleNamespace(name=name, fax_number=fax, active=active)
    )


@pytest.fixture
def models():
    with (
        patch("auto_fax.services.recipients.CareTeamMembership") as care_team,
        patch("auto_fax.services.recipients.ServiceProvider") as service_provider,
        patch(
            "auto_fax.services.recipients.PatientFacilityAddress"
        ) as facility_address,
    ):
        yield SimpleNamespace(
            care_team=care_team,
            service_provider=service_provider,
            facility=facility_address,
        )


def _care_team_chain(models, memberships):
    chain = models.care_team.objects.filter.return_value.select_related.return_value.order_by
    chain.return_value = memberships
    return chain


def _facility_chain(models, address):
    first = models.facility.objects.filter.return_value.filter.return_value.select_related.return_value.order_by.return_value.first
    first.return_value = address
    return first


def test_fixed_recipient_needs_no_queries(models):
    rule = _rule(
        "fixed", RecipientSpec(type="fixed", name="Records", fax_digits="5552340100")
    )
    assert resolve_recipients("p1", [rule], TODAY) == [
        Recipient(rule, "fixed", "Records", "5552340100")
    ]
    models.care_team.objects.filter.assert_not_called()
    models.facility.objects.filter.assert_not_called()


def test_care_team_members_resolved_in_two_queries_total(models):
    pcp_rule = _rule(
        "pcp", RecipientSpec(type="care_team_role", role_codes=frozenset({PCP}))
    )
    ref_rule = _rule(
        "ref", RecipientSpec(type="care_team_role", role_codes=frozenset({REFERRING}))
    )
    _care_team_chain(
        models,
        [_membership(PCP, 11), _membership(REFERRING, 12), _membership(REFERRING, 13)],
    )
    models.service_provider.objects.filter.return_value = [
        _provider(11, practice="Main St Clinic"),
        _provider(12, first="", last="", practice="Valley Ortho", fax="(555) 234-0122"),
        _provider(13, first="Sam", last="Ray", practice="Sam Ray", fax="5552340133"),
    ]

    result = resolve_recipients("p1", [pcp_rule, ref_rule], TODAY)

    assert result == [
        Recipient(pcp_rule, "care_team_role", "Pat Lee, Main St Clinic", "5552340100"),
        Recipient(ref_rule, "care_team_role", "Valley Ortho", "5552340122"),
        Recipient(ref_rule, "care_team_role", "Sam Ray", "5552340133"),
    ]
    filter_kwargs = models.care_team.objects.filter.call_args.kwargs
    assert filter_kwargs["patient__id"] == "p1"
    assert filter_kwargs["status"] == "active"
    assert filter_kwargs["role_code__in"] == sorted([PCP, REFERRING])
    assert filter_kwargs["staff__isnull"] is True
    assert filter_kwargs["organizational_entity__type"] == "Service Provider"
    models.care_team.objects.filter.return_value.select_related.assert_called_once_with(
        "organizational_entity"
    )
    assert models.care_team.objects.filter.call_count == 1
    models.service_provider.objects.filter.assert_called_once_with(
        dbid__in=[11, 12, 13]
    )


def test_no_matching_member_is_a_problem(models):
    rule = _rule(
        "pcp", RecipientSpec(type="care_team_role", role_codes=frozenset({PCP}))
    )
    _care_team_chain(models, [])
    result = resolve_recipients("p1", [rule], TODAY)
    assert result == [
        Recipient(
            rule,
            "care_team_role",
            "",
            None,
            problem="no active external care team member with that role",
        )
    ]
    models.service_provider.objects.filter.assert_not_called()


def test_member_with_other_role_does_not_match(models):
    rule = _rule(
        "pcp", RecipientSpec(type="care_team_role", role_codes=frozenset({PCP}))
    )
    other = _rule(
        "ref", RecipientSpec(type="care_team_role", role_codes=frozenset({REFERRING}))
    )
    _care_team_chain(models, [_membership(REFERRING, 12)])
    models.service_provider.objects.filter.return_value = [_provider(12)]
    result = resolve_recipients("p1", [rule, other], TODAY)
    assert result[0].problem == "no active external care team member with that role"
    assert result[1].fax_digits == "5552340100"


@pytest.mark.parametrize(
    ("provider", "name", "problem"),
    [
        (
            _provider(11, fax=""),
            "Pat Lee",
            "no valid fax number on the directory record",
        ),
        (
            _provider(11, fax="12345"),
            "Pat Lee",
            "no valid fax number on the directory record",
        ),
        (_provider(11, active=False), "Pat Lee", "directory record is inactive"),
        (None, "", "care team member's directory record is missing"),
    ],
)
def test_unfaxable_member_is_a_problem(models, provider, name, problem):
    rule = _rule(
        "pcp", RecipientSpec(type="care_team_role", role_codes=frozenset({PCP}))
    )
    _care_team_chain(models, [_membership(PCP, 11)])
    models.service_provider.objects.filter.return_value = [provider] if provider else []
    (recipient,) = resolve_recipients("p1", [rule], TODAY)
    assert recipient == Recipient(rule, "care_team_role", name, None, problem=problem)


def test_facility_recipient(models):
    rule = _rule("facility", RecipientSpec(type="facility"))
    first = _facility_chain(models, _facility_address())
    (recipient,) = resolve_recipients("p1", [rule], TODAY)
    assert recipient == Recipient(rule, "facility", "Oak House", "5552340111")
    first.assert_called_once_with()
    filter_kwargs = models.facility.objects.filter.call_args.kwargs
    assert filter_kwargs == {
        "patient__id": "p1",
        "state": "active",
        "facility__isnull": False,
    }
    models.facility.objects.filter.return_value.filter.return_value.select_related.assert_called_once_with(
        "facility"
    )
    models.care_team.objects.filter.assert_not_called()


def test_facility_looked_up_once_for_several_rules(models):
    rules = [
        _rule("a", RecipientSpec(type="facility")),
        _rule("b", RecipientSpec(type="facility")),
    ]
    _facility_chain(models, _facility_address())
    result = resolve_recipients("p1", rules, TODAY)
    assert [r.rule.name for r in result] == ["a", "b"]
    assert models.facility.objects.filter.call_count == 1


@pytest.mark.parametrize(
    ("address", "name", "problem"),
    [
        (None, "", "patient has no current facility address"),
        (_facility_address(active=False), "Oak House", "facility is inactive"),
        (_facility_address(fax=None), "Oak House", "facility has no valid fax number"),
    ],
)
def test_unfaxable_facility_is_a_problem(models, address, name, problem):
    rule = _rule("facility", RecipientSpec(type="facility"))
    _facility_chain(models, address)
    (recipient,) = resolve_recipients("p1", [rule], TODAY)
    assert recipient == Recipient(rule, "facility", name, None, problem=problem)


def test_no_rules_no_queries(models):
    assert resolve_recipients("p1", [], TODAY) == []
    models.care_team.objects.filter.assert_not_called()
    models.facility.objects.filter.assert_not_called()


def test_mixed_rule_keeps_recipient_order(models):
    rule = _rule(
        "mixed",
        RecipientSpec(type="facility"),
        RecipientSpec(type="fixed", name="Records", fax_digits="5552340100"),
        RecipientSpec(type="care_team_role", role_codes=frozenset({PCP})),
    )
    _facility_chain(models, _facility_address())
    _care_team_chain(models, [_membership(PCP, 11)])
    models.service_provider.objects.filter.return_value = [
        _provider(11, fax="5552340177")
    ]
    result = resolve_recipients("p1", [rule], TODAY)
    assert [(r.kind, r.fax_digits) for r in result] == [
        ("facility", "5552340111"),
        ("fixed", "5552340100"),
        ("care_team_role", "5552340177"),
    ]


def test_provider_name_with_only_practice():
    from auto_fax.services.recipients import _provider_name

    assert (
        _provider_name(MagicMock(first_name="", last_name="", practice_name=""))
        == "Care team provider"
    )
    assert (
        _provider_name(MagicMock(first_name="Ann", last_name="", practice_name=""))
        == "Ann"
    )
