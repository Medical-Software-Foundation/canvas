"""Two query shapes that pass here and are refused by the plugin runner sandbox.

Every other test in this suite runs against the pytest database, where Django is a
whole Django. The sandbox the plugin actually runs in is not, and on 2026-08-28 two
defects reached a real instance with all 207 tests green, both of them the same
mistake in different clothes.

The first asked for a class's coverage entries through prefetch_related, and then
through the reverse accessor the prefetch would have filled. The sandbox hands back
neither, so the moment a class carried its first coverage entry every eligibility
check answered 500 and the note header control could never appear. GET /classes had
already met this and grouped its steps by hand, with a comment saying reverse
accessors are unavailable, so the rule was known and one file had drifted off it.

The second filtered enrolled steps with the enrolment object rather than its dbid.
The foreign key is declared to_field dbid, and the sandbox refuses that lookup with
Cannot query, Must be Enrollment instance, while the same lookup passes here. Every
enrolment made through the form lost its banner and answered with an empty body.

Neither can be reproduced against this database, which is the whole problem, so what
is checked instead is the shape of the source. That is a weaker kind of test and it is
the strongest one available, and it is worth having because both defects were a single
grep away from being caught and nothing was grepping.
"""

import re
from pathlib import Path

import pytest

#: The package, found from this file rather than named, so a rename does not silently
#: leave these checks reading nothing and passing.
PACKAGE = Path(__file__).resolve().parent.parent / "medication_followup_protocol"

#: Every module of the package, so a rule cannot be broken in a file added later.
MODULES = sorted(PACKAGE.rglob("*.py"))


def _source(path: Path) -> str:
    """One module's source with its comments and docstrings left in.

    The prose is kept rather than stripped, because the rules below are stated in the
    comments too and a check that could not see them would report the comment
    explaining the rule as a breach of it. Both patterns are specific enough that a
    sentence about them does not look like code doing them.
    """
    return path.read_text()


def test_the_package_names_some_modules() -> None:
    """Covers criterion: AC20.

    Without this the parametrised checks below would pass with no cases at all if the
    package ever moved, which reads exactly like every module obeying the rules.
    """
    assert MODULES, f"no modules found under {PACKAGE}"


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_no_module_asks_the_sandbox_to_prefetch(module: Path) -> None:
    """Covers scenario: AC20, the enrolment control shows once a prescription matches a class's coverage. Covers criterion: AC20.

    prefetch_related is not available in the sandbox. A related set is read in its own
    query and grouped into a dict by hand, which is what GET /classes does with steps
    and what services/eligibility.py now does with coverage entries.
    """
    offending = [
        line
        for line in _source(module).splitlines()
        if "prefetch_related(" in line
    ]

    assert not offending, (
        f"{module.name} calls prefetch_related, which the sandbox refuses. Read the "
        f"related rows in their own query and group them by hand instead. {offending}"
    )


#: A filter or an exclude keyed on the enrolment object rather than on its dbid. The
#: create call, which legitimately takes the object, is a different shape and is not
#: matched here, since it names the field with no lookup and no queryset in front of it.
_OBJECT_KEYED_LOOKUP = re.compile(r"objects\.(?:filter|exclude)\([^)]*\benrollment=", re.S)


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_no_module_filters_enrolled_steps_by_the_enrolment_object(module: Path) -> None:
    """Covers scenario: AC24, the chart banner is text only, added on enrolment and removed on stop without touching another enrolment's banner. Covers criterion: AC24.

    The foreign key is declared to_field dbid, and on the instance a lookup handed the
    enrolment itself is refused while the same lookup passes here. Every read goes
    through enrollment__dbid, the way services/program_pane.py already reads its steps.

    Creating a row with enrollment=enrollment is untouched by this. Assigning the
    object to a foreign key is not a lookup and the sandbox is happy with it.
    """
    found = _OBJECT_KEYED_LOOKUP.findall(_source(module))

    assert not found, (
        f"{module.name} filters on the enrolment object, which the sandbox refuses "
        f"with Cannot query, Must be Enrollment instance. Filter on "
        f"enrollment__dbid=enrollment.dbid instead. {found}"
    )
