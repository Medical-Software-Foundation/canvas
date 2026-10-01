"""Pure logic for per-consent questions.

A consent definition carries an ordered list of questions the provider answers
while capturing consent. Each question is a dict:

    {"id": "q1", "prompt": "...", "type": "yes_no", "required": True, "affirm": True}

- ``type``     one of ``QUESTION_TYPES``.
- ``required`` the question must be answered.
- ``affirm``   (yes_no / acknowledge only) the answer must be affirmative
               ("Yes" / checked) or recording is blocked.

This module has no SDK/Django imports so it is trivial to unit-test and is the
authoritative place both the admin (cleaning input) and the capture endpoint
(gating the FHIR write) share.
"""

QUESTION_TYPES = ("yes_no", "acknowledge", "text")

# Affirmative values accepted from the browser for yes_no / acknowledge answers.
_AFFIRMATIVE = {"yes", "true", "1", "on", "checked", "confirmed"}


def _coerce_bool(value, default):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def normalize_questions(raw):
    """Clean a list of questions from the admin form.

    Drops entries without a prompt, coerces ``type`` to a known value (default
    ``yes_no``), coerces the ``required`` / ``affirm`` flags, and assigns a stable
    ``id`` (keeping any provided one). ``affirm`` is forced False for ``text``
    questions (affirmation is meaningless for free text). Returns a new list.
    """
    if not isinstance(raw, list):
        return []

    cleaned = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "").strip()
        if not prompt:
            continue

        qtype = item.get("type")
        if qtype not in QUESTION_TYPES:
            qtype = "yes_no"

        required = _coerce_bool(item.get("required"), True)
        affirm = _coerce_bool(item.get("affirm"), False)
        if qtype == "text":
            affirm = False

        qid = str(item.get("id") or "").strip() or ("q%d" % (index + 1))

        cleaned.append(
            {
                "id": qid,
                "prompt": prompt[:500],
                "type": qtype,
                "required": required,
                "affirm": affirm,
            }
        )
    return cleaned


def _is_affirmative(value):
    return str(value).strip().lower() in _AFFIRMATIVE


def _display(question, value):
    """Human-readable answer for the PDF."""
    qtype = question.get("type")
    if qtype == "text":
        return str(value or "").strip()
    if qtype == "acknowledge":
        return "Confirmed" if _is_affirmative(value) else "Not confirmed"
    # yes_no
    if value is None or str(value).strip() == "":
        return ""
    return "Yes" if _is_affirmative(value) else "No"


def evaluate_answers(questions, answers):
    """Validate submitted answers against a definition's questions.

    ``answers`` maps question id -> submitted value. Returns
    ``(ok, error, responses)``:

    - ``ok``        True when every required question is answered and every
                    ``affirm`` question is affirmative.
    - ``error``     a user-facing message on the first failure, else "".
                    Required-but-missing yields a "please answer" message;
                    an un-affirmed affirm question yields a "consent was not
                    granted" message (the caller must then write nothing).
    - ``responses`` ordered ``[(prompt, display)]`` for answered questions, for
                    printing on the PDF (empty answers are skipped).
    """
    questions = questions or []
    answers = answers or {}
    responses = []

    for question in questions:
        if not isinstance(question, dict):
            continue
        qid = question.get("id")
        prompt = question.get("prompt") or ""
        qtype = question.get("type", "yes_no")
        required = bool(question.get("required"))
        affirm = bool(question.get("affirm"))
        value = answers.get(qid)

        answered = value is not None and str(value).strip() != ""
        if qtype == "acknowledge":
            answered = _is_affirmative(value)

        if required and not answered:
            if qtype == "acknowledge":
                return False, "Please confirm: %s" % prompt, []
            return False, "Please answer: %s" % prompt, []

        if affirm and qtype in ("yes_no", "acknowledge") and not _is_affirmative(value):
            return (
                False,
                "Consent was not granted (the answer to “%s” was not "
                "affirmative). Nothing has been recorded." % prompt,
                [],
            )

        display = _display(question, value)
        if display:
            responses.append((prompt, display))

    return True, "", responses
