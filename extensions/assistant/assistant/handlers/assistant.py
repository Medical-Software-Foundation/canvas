import json
from http import HTTPStatus
from typing import Any

import requests

from assistant.chat_tools import (
    CHAT_TOOL_REGISTRY,
    dispatch_chat_tool,
    dispatch_mutation,
    is_mutating_tool,
)
from assistant.constants.secrets import Secrets
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    Credentials,
    SessionCredentials,
    SimpleAPI,
    StaffSessionAuthMixin,
    api,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.utils.http import Http
from canvas_sdk.v1.data.patient import Patient

# ---- /chat endpoint constants ---------------------------------------------

ANTHROPIC_API_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
CHAT_MODEL = "claude-sonnet-4-6"
CHAT_MAX_TOKENS = 8192
MAX_LOOP_ITERATIONS = 8


# ---- Tool-use loop constants ---------------------------------------------

# Flip to False to bypass authentication. Lets you exercise /chat via curl
# without a Canvas staff session — useful for the smoke-test script and
# out-of-session debugging. MUST be True in production. When True, requests
# need the `canvas-logged-in-user-*` headers set by Canvas's session middleware
# (i.e. requests originating from the in-Canvas Assistant panel).
AUTH_ENABLED = True

# Flip to False to remove the Anthropic-hosted `web_search` tool. Useful when
# you don't want PHI-leaning prompts sending queries off-instance, or when
# you're hitting the 90s _AnthropicHttp timeout too often on broad surveys.
# Affects both the tool list and the system-prompt guidance Claude sees.
WEB_SEARCH_ENABLED = True

# Flip to False to drop suggested-next-action chips. System prompt loses
# its guidance + the client renderer ignores any stray blocks.
SUGGESTIONS_ENABLED = True

# Flip to False to drop patient-link guidance. The client-side renderer is
# already scoped to /patient/<id> hrefs only, so it becomes a no-op for any
# stray markdown links if this is off.
PATIENT_LINKS_ENABLED = True

# Flip to False to drop chart-emission guidance from the system prompt (and
# the matching client-side renderer becomes a no-op for any stray blocks).
CHARTS_ENABLED = True

class _AnthropicHttp(Http):
    """Http with a higher timeout for the Anthropic /v1/messages call.

    Default Http.post timeout is 30s which is too short for requests that
    invoke the server-side `web_search` tool (each search + model reasoning
    can take 15-60s). Subclassing to override the class-level constant
    bumps the timeout for our outbound call without touching the SDK or
    affecting other Http users in the plugin.

    The SDK logs a deprecation warning on this override but doesn't block
    it as of canvas 0.155.0 — revisit if a future SDK removes the override
    path entirely.
    """

    _MAX_REQUEST_TIMEOUT_SECONDS = 90

_WEB_SEARCH_GUIDANCE = (
    "Use the `web_search` tool when you need information not in the patient's "
    "chart — drug interactions, FDA updates, recent clinical guidelines, etc. "
    "Cite the sources `web_search` returns and remind the clinician to verify "
    "in a primary source before acting. Do not include patient names in search "
    "queries.\n\n"
)

_SUGGESTIONS_GUIDANCE = (
    "After answering, when an obvious next-step workflow exists for the "
    "clinician (you just showed a lab trend → \"draft a refill task\"; you "
    "just listed open tasks → \"mark these complete\"), suggest 2-3 short "
    "follow-up prompts. Emit them as a fenced JSON block tagged "
    "`suggestions`, after your prose:\n"
    "```suggestions\n"
    '["Trend her A1C over 12 months","Draft a metformin refill task",'
    '"Schedule diabetes follow-up"]\n'
    "```\n"
    "Rules: a JSON array of plain-string prompts. Max 3 chips, each ≤ 60 "
    "characters. Phrase each chip as an instruction the clinician would "
    "type (\"Trend her A1C\", not \"Would you like me to…\"). No markdown "
    "formatting, no leading emoji, no PHI names. Skip the block entirely "
    "when the answer was trivial (\"no allergies on file\") or when no "
    "sensible follow-up exists. One `suggestions` block per answer.\n\n"
)

_PATIENT_LINKS_GUIDANCE = (
    "When you reference a patient by name in your answer, format the first "
    "mention as a markdown link to their chart using their public id: "
    "`[First Last](/patient/<patient_id>)` — use the `id` field returned "
    "by `find_patients` / `find_appointments` / `find_encounters` / etc., "
    "NOT MRN or any other identifier. Don't link every mention (just the "
    "first per patient in an answer), and never fabricate an id — if you "
    "don't have one, write the name as plain text. Patient links are the "
    "only resource type that supports deep linking right now; don't make "
    "condition/medication/staff/note links even if it would be useful.\n\n"
)

_CHART_GUIDANCE = (
    "When the user asks to visualize a trend, plot something over time, or "
    "compare numeric values across dates (height/weight/BP over time, lab "
    "values trending, etc.), embed a chart in your answer using a fenced "
    "code block tagged `chart`. The block must contain valid JSON in this "
    "shape:\n"
    "```chart\n"
    '{"type":"line","title":"Height over time","x_label":"Date",'
    '"y_label":"cm","series":[{"name":"Height","points":'
    '[{"x":"2024-03-12","y":172.1},{"x":"2025-02-14","y":172.5}]}]}\n'
    "```\n"
    "Rules: `type` must be `line`. `x` is an ISO date (YYYY-MM-DD) or "
    "datetime string. `y` must be a number — drop points with missing or "
    "non-numeric values rather than guessing. One chart per fenced block; "
    "you may emit multiple blocks and write prose around them. Keep series "
    "≤ 4 and points-per-series ≤ 100. Don't put PHI in `title` or `name` "
    "(say \"Height\", not \"Reagan's height\"). Only chart when the user "
    "explicitly wants a visualization; otherwise summarize in prose.\n\n"
)

CHAT_SYSTEM_PROMPT = (
    "You are a clinical assistant for a Canvas Medical clinician. Use the provided "
    "tools to answer the user's question about patient data.\n\n"
    "Today's date is available via the `get_today` tool — call it rather than guessing "
    "relative dates like 'today' or 'this week'.\n\n"
    "The requesting clinician's staff_id is included in the user message as "
    "<staff_id>...</staff_id>. When the user says 'my schedule', 'my patients', or "
    "similar self-referential phrases AND a staff_id is provided, filter by that "
    "staff_id. If the staff_id is empty, treat 'my' phrasing as referring to the "
    "whole practice — do not ask the user for an id, just answer at the practice "
    "level.\n\n"
    'When an <active_patient id="..." /> tag is present in the user message, '
    "that patient's chart is currently open. When the user refers to 'this "
    "patient', 'her', 'him', 'they', or asks without naming a patient, use the "
    "active_patient id directly with per-patient tools (find_conditions, "
    "find_medications, find_appointments with patient_id=..., etc.) — do NOT "
    "call find_patients first; you already have the id. If the user names a "
    "different patient, look up that patient and use their id instead.\n\n"
    "Tools that take a `patient_id` require it — look up the patient by name with "
    "`find_patients` first if you only have a name.\n\n"
    "When the user asks about a specific note or visit by date ('tell me about "
    "the note from 2/10', 'what happened at last week's visit'), call "
    "`find_notes` with a `date_from`/`date_to` range covering that day to pick "
    "the right note_id, then call `find_commands(note_id=...)` to read the "
    "actual structured content (diagnoses, prescriptions, plan, etc.) on that "
    "note. Summarize what's on the note in prose. Don't ask the user to "
    "specify the year if the date is unambiguous from context (use `get_today` "
    "and assume the most recent occurrence).\n\n"
    "For prep-the-day workflows ('prep tomorrow', 'who am I seeing', 'morning "
    "rounds', 'get me ready for today'), call `prep_visit_panel` instead of "
    "chaining find_appointments + find_conditions + find_medications + "
    "find_lab_reports + find_tasks per patient — it returns one compact "
    "bundle per scheduled patient in a single call, which keeps you inside "
    "the iteration budget. Defaults to today and the requesting staff_id; "
    "pass `date` and `provider_id` to override. After calling it, write a "
    "short one-paragraph summary per patient (name as a deep link, age/sex, "
    "appointment time, the 1-3 things actually worth flagging — overdue "
    "follow-up, abnormal lab to address, open task to close out). Skip "
    "boilerplate; if a patient has nothing notable, say so in one line.\n\n"
    + (_WEB_SEARCH_GUIDANCE if WEB_SEARCH_ENABLED else "")
    + (_PATIENT_LINKS_GUIDANCE if PATIENT_LINKS_ENABLED else "")
    + (_CHART_GUIDANCE if CHARTS_ENABLED else "")
    + (_SUGGESTIONS_GUIDANCE if SUGGESTIONS_ENABLED else "")
    + "Mutating tools (e.g. `create_task`) DO NOT execute immediately — the user "
    "must approve each one. After you call a mutating tool, the request pauses; "
    "the user sees an approval card and either approves or denies. Don't call "
    "the same mutating tool more than once per turn, and don't claim success "
    "until you see a tool result confirming the action was approved.\n\n"
    "Be concise. If a question requires data outside the available tools, say so plainly."
)


# All chat tools (read-only + mutating create_*) live under
# `assistant.chat_tools` — each in its own module with a pydantic args model
# and a free-function handler. The package's __init__ side-effect-imports each
# tool module so its @chat_tool or @mutation_tool decorator populates
# `CHAT_TOOL_REGISTRY`. The derived schemas are spliced onto CHAT_TOOLS at the
# bottom of this file (which also includes the Anthropic-hosted `web_search`
# tool definition).

CHAT_TOOLS: list[dict[str, Any]] = [

    # ---- Anthropic-hosted server-side tools ------------------------------
    # max_uses caps Anthropic's internal sub-loop so a single /v1/messages
    # call stays within the 90s timeout we set on _AnthropicHttp. Multiple
    # searches across one user turn happen via the existing pause_turn /
    # polling path. Disable globally by flipping WEB_SEARCH_ENABLED above.
    *(
        [{"type": "web_search_20260209", "name": "web_search", "max_uses": 1}]
        if WEB_SEARCH_ENABLED
        else []
    ),
]


class Assistant(StaffSessionAuthMixin, SimpleAPI):
    """SimpleAPI handler that answers natural-language questions about patients."""

    PREFIX = None

    def authenticate(self, credentials: Credentials) -> bool:
        """Gate requests behind a Canvas staff session, with a test-only bypass.

        The annotation is `Credentials` (no-op constructor) rather than
        `SessionCredentials` so the SimpleAPI framework can call us *before*
        attempting to read session headers — that lets `AUTH_ENABLED = False`
        actually bypass auth for curl-driven testing where no Canvas session
        exists. When `AUTH_ENABLED` is True (production), we construct
        `SessionCredentials` ourselves and delegate to `StaffSessionAuthMixin`
        via super(), which enforces that the logged-in user is a Staff member.
        """
        if not AUTH_ENABLED:
            return True
        return super().authenticate(SessionCredentials(self.request))

    def _resolve_staff_id(self, body: dict) -> str | None:
        """Resolve the requesting staff member's id.

        In production (`AUTH_ENABLED`) the identity comes solely from the
        authenticated session via the `canvas-logged-in-user-id` header. A
        client-supplied `staff_id` must NOT override it — otherwise any
        authenticated caller could impersonate another staff member for
        mutation authorship and "my panel" reads. The body `staff_id` is
        honored only when auth is disabled, for out-of-session curl testing.
        """
        if not AUTH_ENABLED and (explicit := body.get("staff_id")):
            return str(explicit)
        return self.request.headers.get("canvas-logged-in-user-id")

    @api.get("/ui")
    def chat_ui(self) -> list[Response | Effect]:
        """Render the chat panel HTML.

        Used by companion applications, which load their UI via URL (not
        inline content). Accepts optional `?patient_id=<id>` so a patient
        chart's companion can scope subsequent /chat calls to the active
        patient — same shape as the inline ChatApp's template context.
        """
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        patient_name = ""
        if patient_id:
            try:
                p = Patient.objects.get(id=patient_id)
                patient_name = f"{p.first_name} {p.last_name}".strip()
            except Patient.DoesNotExist:
                pass

        html = render_to_string(
            "templates/chat.html",
            {
                "chat_url": "/plugin-io/api/assistant/chat",
                "patient_id": patient_id,
                "patient_name": patient_name,
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    # ---- /chat endpoint: Claude tool-use loop ----------------------------

    def _execute_tool(self, name: str, arguments: dict) -> dict:
        """Dispatch a read-only chat tool. Always returns a JSON-serializable dict.

        All read-only tools live in `assistant.chat_tools`; this wraps the
        package's `dispatch_chat_tool` and turns its `None`-on-unknown into
        an explicit error dict. Mutating tools are intercepted earlier in the
        chat loop via `is_mutating_tool(name)` and routed through
        `dispatch_mutation` only after the user approves them.
        """
        result = dispatch_chat_tool(self, name, arguments)
        if result is None:
            return {"error": f"unknown tool: {name}"}
        return result

    # ---- Anthropic HTTP + tool-use loop ----------------------------------

    def _call_anthropic(self, messages: list[dict]) -> dict:
        """One POST to /v1/messages. Returns the parsed JSON.

        This is the single boundary for Anthropic call failures: network /
        timeout errors, non-200 responses, and malformed JSON bodies are all
        converted to `RuntimeError` so the caller can catch one type. Any
        other exception (a programming bug) propagates untouched so it
        reaches Sentry.
        """
        http = _AnthropicHttp(base_url=ANTHROPIC_API_URL)
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
            "x-api-key": self.secrets[Secrets.anthropic_key],
        }
        # Cache the static prefix (tools + system). Marker on the last system block
        # caches both tiers since render order is tools -> system -> messages.
        body = {
            "model": CHAT_MODEL,
            "max_tokens": CHAT_MAX_TOKENS,
            "system": [
                {
                    "type": "text",
                    "text": CHAT_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "tools": CHAT_TOOLS,
            "tool_choice": {"type": "auto"},
            "messages": messages,
        }
        try:
            resp = http.post("/v1/messages", headers=headers, data=json.dumps(body))
        except requests.RequestException as exc:
            raise RuntimeError(f"anthropic request failed: {exc}") from exc
        if resp.status_code != HTTPStatus.OK:
            raise RuntimeError(f"anthropic {resp.status_code}: {resp.text[:500]}")
        try:
            return json.loads(resp.text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"anthropic returned malformed JSON: {exc}") from exc

    @staticmethod
    def _summarize_result(result: dict) -> dict:
        """Trim a tool result to a compact summary for the trace (full result still goes to Claude)."""
        if "error" in result:
            return {"error": result["error"]}
        summary: dict = {}
        if "count" in result:
            summary["count"] = result["count"]
        if "date" in result:
            summary["date"] = result["date"]
        if isinstance(result.get("results"), list):
            summary["results_len"] = len(result["results"])
        return summary

    @staticmethod
    def _build_user_turn(
        question: str, staff_id: str | None, patient_id: str | None = None
    ) -> dict:
        framing = [f"<staff_id>{staff_id or ''}</staff_id>"]
        if patient_id:
            framing.append(f'<active_patient id="{patient_id}" />')
        return {
            "role": "user",
            "content": "\n".join(framing) + f"\n\n{question}",
        }

    def _normalize_history(self, raw: Any, max_turns: int = 40) -> list[dict]:
        """Validate and truncate inbound conversation history.

        Truncation drops oldest messages but never cuts between an assistant
        turn containing `tool_use` blocks and the matching `tool_result`
        user turn — the Anthropic API 400s on dangling tool_use blocks.
        """
        if not isinstance(raw, list):
            return []
        cleaned: list[dict] = []
        for m in raw:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            if role not in ("user", "assistant"):
                continue
            content = m.get("content")
            if content is None:
                continue
            cleaned.append({"role": role, "content": content})
        if len(cleaned) <= max_turns:
            return cleaned
        # Truncate from the front, but only at a "safe" boundary: a plain-text
        # user turn (not a tool_result). Scan forward from the rough cut point.
        cut = len(cleaned) - max_turns
        while cut < len(cleaned):
            m = cleaned[cut]
            if m["role"] == "user":
                c = m["content"]
                if isinstance(c, str):
                    break
                if isinstance(c, list) and all(
                    b.get("type") not in ("tool_result", "tool_use")
                    for b in c
                    if isinstance(b, dict)
                ):
                    break
            cut += 1
        return cleaned[cut:]

    # ---- The chat loop ---------------------------------------------------

    def _run_chat_loop(
        self,
        messages: list[dict],
        approvals: dict[str, dict] | None = None,
        staff_id: str | None = None,
        polling: bool = False,
    ) -> dict:
        """Run (or resume) the Claude tool-use loop.

        Args:
            messages: full message history, including the last assistant turn
                if resuming after approvals.
            approvals: when resuming, a dict keyed by tool_use_id with values
                like {"decision": "approve"} or {"decision": "deny", "reason": "..."}.
            staff_id: the requesting clinician's id (used as the author for
                mutations they approve).
            polling: when True, run at most one iteration per call and return
                `{state: "running", ...}` if more iterations are needed. The
                client repolls with `{continue: true, messages, ...}` until a
                final answer or pending_mutations is returned. This is the
                progressive-progress mode used by the chat UI; CLI/script
                callers leave it False to run the full loop in one request.
        """
        messages = list(messages)
        trace: list[dict] = []
        cache_creation = 0
        cache_read = 0
        input_tokens = 0
        output_tokens = 0
        effects: list[Effect] = []

        # Resuming after user approval: synthesize tool_result blocks for the
        # pending assistant turn before entering the loop.
        if approvals:
            if not messages or messages[-1].get("role") != "assistant":
                return {
                    "error": "approvals provided but the last message isn't an assistant turn",
                    "messages": messages,
                }
            assistant_content = messages[-1].get("content") or []
            tool_results = []
            for block in assistant_content:
                if block.get("type") != "tool_use":
                    continue
                tu_id = block.get("id")
                tool_name = block.get("name", "")
                tool_input = block.get("input") or {}
                decision = approvals.get(tu_id) or {}
                d = decision.get("decision")
                if d == "approve":
                    result, mutation_effects = dispatch_mutation(
                        self, tool_name, tool_input, staff_id
                    )
                    effects.extend(mutation_effects)
                    trace.append(
                        {
                            "tool": tool_name,
                            "input": tool_input,
                            "summary": {**self._summarize_result(result), "approved": True},
                        }
                    )
                    tr_block: dict = {
                        "type": "tool_result",
                        "tool_use_id": tu_id,
                        "content": json.dumps(result, default=str),
                    }
                    if "error" in result:
                        tr_block["is_error"] = True
                    tool_results.append(tr_block)
                elif d == "deny":
                    reason = (decision.get("reason") or "User denied this action.").strip()
                    trace.append(
                        {
                            "tool": tool_name,
                            "input": tool_input,
                            "summary": {"denied": True, "reason": reason},
                        }
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu_id,
                            "content": f"User denied: {reason}",
                            "is_error": True,
                        }
                    )
                else:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu_id,
                            "content": "No decision was provided for this action.",
                            "is_error": True,
                        }
                    )
            messages.append({"role": "user", "content": tool_results})

        def _envelope(extra: dict) -> dict:
            return {
                "trace": trace,
                "messages": messages,
                "effects": effects,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_creation_input_tokens": cache_creation,
                    "cache_read_input_tokens": cache_read,
                },
                **extra,
            }

        max_iters = 1 if polling else MAX_LOOP_ITERATIONS
        for iteration in range(max_iters):
            resp = self._call_anthropic(messages)

            usage = resp.get("usage") or {}
            cache_creation += usage.get("cache_creation_input_tokens") or 0
            cache_read += usage.get("cache_read_input_tokens") or 0
            input_tokens += usage.get("input_tokens") or 0
            output_tokens += usage.get("output_tokens") or 0

            content = resp.get("content") or []
            messages.append({"role": "assistant", "content": content})
            stop_reason = resp.get("stop_reason")

            # Surface server-side tool calls (web_search etc.) in the trace
            # so the UI shows them alongside our custom tools.
            for block in content:
                if block.get("type") == "server_tool_use":
                    trace.append(
                        {
                            "tool": block.get("name", "server_tool"),
                            "input": block.get("input") or {},
                            "summary": {"server_side": True},
                        }
                    )

            if stop_reason == "end_turn":
                answer = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                return _envelope({"answer": answer.strip(), "iterations": iteration + 1})

            if stop_reason == "pause_turn":
                # Anthropic's server-side tool loop hit its internal cap. Per
                # the API spec we re-send messages as-is (already appended the
                # assistant turn above) and Anthropic resumes where it left off.
                continue

            if stop_reason == "tool_use":
                # Split into mutations (pause for approval) vs read-only tools.
                pending_mutations = []
                tool_results = []
                for block in content:
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name", "")
                    args = block.get("input") or {}
                    if is_mutating_tool(name):
                        pending_mutations.append(
                            {
                                "tool_use_id": block.get("id"),
                                "tool": name,
                                "input": args,
                            }
                        )
                        continue
                    result = self._execute_tool(name, args)
                    trace.append(
                        {
                            "tool": name,
                            "input": args,
                            "summary": self._summarize_result(result),
                        }
                    )
                    tr_block = {
                        "type": "tool_result",
                        "tool_use_id": block.get("id"),
                        "content": json.dumps(result, default=str),
                    }
                    if "error" in result:
                        tr_block["is_error"] = True
                    tool_results.append(tr_block)

                if pending_mutations:
                    # Pause the loop; the client surfaces an approval card and
                    # re-calls /chat with `mutation_results` to resume.
                    return _envelope(
                        {
                            "pending_mutations": pending_mutations,
                            "iterations": iteration + 1,
                        }
                    )

                messages.append({"role": "user", "content": tool_results})
                continue

            # max_tokens, refusal, stop_sequence — bail with what we have
            answer = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            return _envelope(
                {
                    "answer": answer.strip() or f"(model stopped: {stop_reason})",
                    "iterations": iteration + 1,
                    "stop_reason": stop_reason,
                }
            )

        if polling:
            # One iteration of read-only tools just ran; client will repoll.
            return _envelope({"state": "running", "iterations": max_iters})

        return _envelope(
            {
                "answer": "I couldn't finish that within the iteration budget.",
                "iterations": MAX_LOOP_ITERATIONS,
            }
        )

    @api.post("/chat")
    def chat(self) -> list[Response | Effect]:
        """Tool-use-driven natural-language Q&A about patient data.

        Modes:
        - New question: pass `question` (and optional `messages` for history).
        - Continuation after approval: pass `mutation_results` (the user's
          approve/deny decisions for the previous response's `pending_mutations`)
          plus the previous `messages` verbatim. `question` is ignored.
        - Polling continuation: pass `continue: true` + `messages` to advance
          the loop one more iteration (used when `poll: true` was set on a
          prior call and the response was `{state: "running"}`).

        Polling: when `poll: true` is set in the body, the server runs at most
        ONE Anthropic iteration per call and returns `{state: "running"}` if
        more work is needed. The client repolls with `continue: true` until
        the response is `{answer}` or `{pending_mutations}`. Non-polling
        callers (scripts, curl, smoke tests) leave `poll` unset and get the
        full loop in one request, as before.
        """
        body = self.request.json() or {}
        staff_id = self._resolve_staff_id(body)
        # Stash for read-only tools (`prep_visit_panel`) that default to the
        # requesting staff but go through `_execute_tool`, which doesn't
        # otherwise receive staff_id. Mutations get it explicitly via
        # `dispatch_mutation`.
        self._requesting_staff_id = staff_id
        patient_id = (body.get("patient_id") or "").strip() or None
        mutation_results = body.get("mutation_results")
        polling = bool(body.get("poll"))
        continue_loop = bool(body.get("continue"))

        try:
            if mutation_results is not None:
                # Approval continuation: resume the loop with the user's decisions.
                if not isinstance(mutation_results, list):
                    return [
                        JSONResponse(
                            {"error": "'mutation_results' must be a list"},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]
                approvals = {
                    m["tool_use_id"]: m
                    for m in mutation_results
                    if isinstance(m, dict) and m.get("tool_use_id")
                }
                seed_messages = self._normalize_history(body.get("messages"))
                if not seed_messages:
                    return [
                        JSONResponse(
                            {"error": "continuation requires 'messages' from the prior response"},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]
                result = self._run_chat_loop(
                    seed_messages,
                    approvals=approvals,
                    staff_id=staff_id,
                    polling=polling,
                )
                question = ""
            elif continue_loop:
                # Polling continuation: no new question, no approvals — just
                # advance the loop from where the prior response left off.
                seed_messages = self._normalize_history(body.get("messages"))
                if not seed_messages:
                    return [
                        JSONResponse(
                            {"error": "continue=true requires 'messages' from the prior response"},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]
                result = self._run_chat_loop(
                    seed_messages, staff_id=staff_id, polling=polling
                )
                question = ""
            else:
                question = (body.get("question") or "").strip()
                if not question:
                    return [
                        JSONResponse(
                            {"error": "missing 'question'"},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]
                prior_messages = self._normalize_history(body.get("messages"))
                seed_messages = prior_messages + [
                    self._build_user_turn(question, staff_id, patient_id=patient_id)
                ]
                result = self._run_chat_loop(
                    seed_messages, staff_id=staff_id, polling=polling
                )
        except RuntimeError as exc:
            # Only the Anthropic call raises RuntimeError (see _call_anthropic).
            # Any other exception is a bug and propagates to Sentry.
            return [
                JSONResponse(
                    {"error": "chat loop failed", "detail": f"{exc.__class__.__name__}: {exc}"},
                    status_code=HTTPStatus.BAD_GATEWAY,
                )
            ]

        effects = result.pop("effects", []) or []
        return [
            JSONResponse(
                {"question": question, **result},
                status_code=HTTPStatus.OK,
            ),
            *effects,
        ]


# Splice pydantic-derived tool schemas into CHAT_TOOLS. The registry was
# populated when `assistant.chat_tools` was imported at the top of the file.
CHAT_TOOLS.extend(t["schema"] for t in CHAT_TOOL_REGISTRY)

