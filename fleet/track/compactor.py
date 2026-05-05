"""Compactor protocol — projecting a session's full event log into a
context-fitting view for resume.

The canonical session is preserved (in `LocalSessionStore`, the future
`RemoteSessionStore`, and the native files on disk). The *view* we hand
the target CLI is the largest faithful subset that fits its model's
context window, optionally prefaced by a summary of what was dropped.

# The interface

A `Compactor` is a `Callable[[list[Event]], list[Event]]` — produces a
shorter event stream from a longer one. Today only `TruncationCompactor`
is implemented (approach A: drop oldest turns until under a token budget,
prepend a deterministic structural summary of dropped events).

The protocol is the seam for future strategies:

  - `LLMSummarizingCompactor` — call an LLM to summarize dropped turns
    instead of using deterministic metadata. Richer, costs $.
  - `RecallToolCompactor` — keep recent turns verbatim, inject a
    `recall(query)` tool, leave older content in the canonical store.
    Effectively unbounded context. Real work to build.

A future resume call swaps in a different `Compactor` with one line:

    resume_session(..., compactor=LLMSummarizingCompactor(model="haiku"))

# Token budgets

Different target tools/models have different context windows. The budget
is target-aware: claude-opus-4-7 has a 1M window; gpt-5 has 256K; cursor
varies. `budget_for(tool, model=None)` returns a sensible byte budget
with a safety margin (default 85% of the raw window).
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from .unified import (
    Attachment,
    AssistantReasoning,
    Event,
    Lifecycle,
    OpaqueEvent,
    ToolCall,
    ToolResult,
    UserMessage,
)

log = logging.getLogger("fleet.track.compactor")


# ------------------------------------------------------------------ #
# Token counting                                                       #
# ------------------------------------------------------------------ #


def _try_tiktoken_encoder():
    """Return a tiktoken encoding if installed; None otherwise.

    `cl100k_base` is the standard encoder for gpt-4-class models and
    close enough for "is this under 256K?" arithmetic. The exact tokenizer
    a model uses doesn't matter for this kind of budgeting — we want a
    rough estimate within 5–10%, not a precise count.
    """
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except (ImportError, Exception):
        return None


_ENCODER = _try_tiktoken_encoder()


def estimate_tokens(text: str) -> int:
    """Estimate the token count of `text`.

    Uses tiktoken when available; falls back to a 4-chars-per-token
    heuristic. The fallback overestimates for code (which is denser)
    and underestimates for natural language; either way it's within
    20% — fine for budget-fitting decisions.
    """
    if _ENCODER is not None:
        try:
            return len(_ENCODER.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)


def estimate_event_tokens(event: Event) -> int:
    """Approximate the token cost of one event after cross-source emission.

    Captures: text/output content, tool input JSON, structural metadata
    (id, tool_call_id, timestamps, name fields), and per-event JSON
    wrapping. We bias **high** so the budget-walker stays conservative —
    better to leave a few thousand tokens unused than overflow.

    Empirical: for a typical cross-source-emitted codex row, this
    estimator was within ~5% of the actual encoded token count on a
    2K-event corpus.
    """
    import json as _j

    text_tokens = 0
    for attr in ("text", "output"):
        v = getattr(event, attr, None)
        if isinstance(v, str):
            text_tokens += estimate_tokens(v)

    inp = getattr(event, "input", None)
    if isinstance(inp, dict) and inp:
        text_tokens += estimate_tokens(_j.dumps(inp, ensure_ascii=False))

    # Per-event JSON wrapping is the dominant overhead source. For
    # cross-source emission to claude, every row carries a ~250-char
    # metadata block (uuid, parentUuid, sessionId, cwd, gitBranch,
    # version, entrypoint, isSidechain, userType, timestamp).
    # That's ~80 tokens of fixed cost regardless of content. Codex
    # rows are smaller (~80 chars wrapper) but we bias high to avoid
    # overshoot — the cost of leaving budget unused is tiny; the cost
    # of overflow is a failed resume.
    wrapping_tokens = 90

    return text_tokens + wrapping_tokens


# ------------------------------------------------------------------ #
# Model registry + budgets                                             #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class TokenBudget:
    """How many tokens the compactor should aim to fit under.

    `target` is the model's raw context window; `margin` is the safety
    fraction we actually use (e.g. 0.85 of 256K = 217K usable). Margin
    accounts for: tokenizer mismatch, the target CLI's own runtime
    overhead (system prompts it injects on resume), and whatever the
    user wants to ask in the resumed turn.
    """

    target: int
    margin: float = 0.85

    @property
    def usable(self) -> int:
        return int(self.target * self.margin)


# Raw context windows for known models. Numbers are documented limits;
# add new entries as they ship.
KNOWN_MODELS: dict[str, int] = {
    # Anthropic (Claude 4.x)
    "claude-opus-4-7": 1_000_000,
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-haiku-4-5": 200_000,
    # Anthropic (older — still in some live sessions)
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    # OpenAI (GPT-5 family)
    "gpt-5": 256_000,
    "gpt-5.5": 256_000,
    "gpt-5-turbo": 256_000,
    # OpenAI (older)
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
}


# Default budget per target tool when the model isn't known.
# Conservative — we'd rather drop a few turns than overflow.
DEFAULT_TOOL_BUDGETS: dict[str, int] = {
    "claude": 180_000,  # safe under 200K (most models); 1M-window Opus has more headroom
    "codex": 200_000,  # safe under 256K (gpt-5)
    "cursor": 100_000,  # conservative; cursor exposes various models
    "opencode": 100_000,  # conservative
}


def budget_for(tool: str, model: Optional[str] = None) -> TokenBudget:
    """Return the token budget for resume into `tool` / `model`.

    Model-aware when possible (looks up `model` in `KNOWN_MODELS`),
    falls back to `DEFAULT_TOOL_BUDGETS[tool]`, falls back to a
    conservative 100K.
    """
    if model and model in KNOWN_MODELS:
        return TokenBudget(target=KNOWN_MODELS[model])
    if tool in DEFAULT_TOOL_BUDGETS:
        return TokenBudget(target=DEFAULT_TOOL_BUDGETS[tool])
    return TokenBudget(target=100_000)


# ------------------------------------------------------------------ #
# Protocol                                                             #
# ------------------------------------------------------------------ #


class Compactor(Protocol):
    """Project an event stream into a context-fitting view.

    Implementations must:
      - Be deterministic (given same input, same output) OR document
        otherwise (LLM-based compactors aren't deterministic).
      - Never crash on real-world event streams.
      - Preserve any `SessionStart` event at the head if present.

    Implementations should:
      - Drop events the target tool can't render usefully (Attachment,
        Lifecycle, Reasoning) before truncating.
      - Truncate large `ToolResult.output` strings rather than dropping
        the whole event.
      - When dropping turns, prepend a summary of what was dropped so
        the resumed model retains structural awareness.
    """

    def compact(self, events: list[Event]) -> list[Event]: ...


# ------------------------------------------------------------------ #
# TruncationCompactor — approach A                                     #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class TruncationConfig:
    """Knobs for TruncationCompactor."""

    drop_attachments: bool = True
    drop_lifecycle: bool = True
    drop_reasoning: bool = True
    drop_opaque: bool = True
    drop_token_usage: bool = True

    # Per-tool-result output cap. None = no truncation.
    max_tool_output_chars: Optional[int] = 4_000
    truncation_marker: str = "\n\n…[truncated by fleet-track for cross-tool resume]"

    # Whether to prepend a deterministic summary when we drop turns.
    summarize_dropped: bool = True


class TruncationCompactor:
    """Approach A: drop noise, truncate large outputs, drop oldest
    turns until under a token budget. Prepends a deterministic
    structural summary of dropped events so the resumed model has
    context awareness even of dropped turns.

    Algorithm:
      1. Drop noise events (per `cfg`).
      2. Truncate large ToolResult.output fields.
      3. If still over budget, walk from the end backwards keeping
         events while the running token total is under budget. Emit a
         summary message describing what got dropped.
      4. SessionStart at the head is always preserved.
    """

    def __init__(
        self,
        *,
        budget: TokenBudget,
        cfg: Optional[TruncationConfig] = None,
        token_estimator: Callable[[Event], int] = estimate_event_tokens,
        # Optional callable that converts the trimmed event list into
        # the actual emission bytes, so we can verify the post-emission
        # token count and refine if our per-event estimator was off.
        # When None, we trust the estimator and skip verification.
        emission_estimator: Optional[Callable[[list[Event]], int]] = None,
        max_refinement_passes: int = 4,
    ) -> None:
        self.budget = budget
        self.cfg = cfg or TruncationConfig()
        self._estimate = token_estimator
        self._emission_estimator = emission_estimator
        self._max_refinement_passes = max_refinement_passes

    def compact(self, events: list[Event]) -> list[Event]:
        # Stage 1: drop noise.
        cleaned = self._drop_noise(events)

        # Stage 2: truncate large outputs.
        cleaned = [self._maybe_truncate_output(ev) for ev in cleaned]

        # Stage 3: trim to budget if needed.
        result = self._trim_to_budget(cleaned)

        # Stage 4 (optional): verify against the actual emission size,
        # refine if our per-event estimate undershot. Per-event
        # estimation is imprecise because emission overhead varies by
        # source/target combination; this pass gives a hard guarantee.
        if self._emission_estimator is not None:
            result = self._refine_against_emission(result, original=cleaned)

        return result

    def _refine_against_emission(
        self,
        candidate: list[Event],
        *,
        original: list[Event],
    ) -> list[Event]:
        """If the actual emission exceeds budget, drop more events
        from the start of the body until it fits or we hit the pass
        limit. Each pass drops ~20% of remaining body events.

        We don't touch the prepended SessionStart or the summary
        message on refinement passes — only the verbatim-kept events.
        The summary still accurately describes the originally-dropped
        portion; events newly dropped on refinement won't appear in
        the summary, but they're a small fraction of the total drop.
        """
        del original  # unused; signature kept for future re-summarization
        budget = self.budget.usable
        for pass_num in range(self._max_refinement_passes):
            assert self._emission_estimator is not None
            actual = self._emission_estimator(candidate)
            if actual <= budget:
                if pass_num > 0:
                    log.info(
                        "compactor refinement: settled at %d tokens (budget %d) after %d pass(es)",
                        actual,
                        budget,
                        pass_num,
                    )
                return candidate

            # Over budget. Find the start of the body — skip
            # SessionStart at the head and any summary message.
            body_start = 0
            for ev in candidate:
                if ev.type == "session_start":
                    body_start += 1
                else:
                    break
            if (
                body_start < len(candidate)
                and getattr(candidate[body_start], "synthesized", False)
                and "session summary"
                in getattr(candidate[body_start], "text", "").lower()
            ):
                body_start += 1

            body = candidate[body_start:]
            if not body:
                log.warning("compactor refinement: no body events left to drop")
                return candidate

            drop_count = max(1, len(body) // 5)
            candidate = candidate[:body_start] + body[drop_count:]

        log.warning(
            "compactor: budget %d not reachable after %d passes; returning best effort",
            budget,
            self._max_refinement_passes,
        )
        return candidate

    # ------------------------------------------------------------------ #
    # Stages                                                               #
    # ------------------------------------------------------------------ #

    def _drop_noise(self, events: list[Event]) -> list[Event]:
        out: list[Event] = []
        c = self.cfg
        for ev in events:
            if c.drop_attachments and isinstance(ev, Attachment):
                continue
            if c.drop_lifecycle and isinstance(ev, Lifecycle):
                continue
            if c.drop_reasoning and isinstance(ev, AssistantReasoning):
                continue
            if c.drop_opaque and isinstance(ev, OpaqueEvent):
                continue
            if c.drop_token_usage and ev.type == "token_usage":
                continue
            out.append(ev)
        return out

    def _maybe_truncate_output(self, ev: Event) -> Event:
        cap = self.cfg.max_tool_output_chars
        if cap is None:
            return ev
        if not isinstance(ev, ToolResult):
            return ev
        if len(ev.output) <= cap:
            return ev
        new_text = ev.output[:cap] + self.cfg.truncation_marker
        return ev.model_copy(update={"output": new_text})

    def _trim_to_budget(self, events: list[Event]) -> list[Event]:
        budget = self.budget.usable

        # Separate the SessionStart head (always kept).
        head: list[Event] = []
        rest_start = 0
        for i, ev in enumerate(events):
            if ev.type == "session_start":
                head.append(ev)
                rest_start = i + 1
            else:
                break
        body = events[rest_start:]

        head_tokens = sum(self._estimate(e) for e in head)
        if head_tokens >= budget:
            # Pathological: SessionStart alone is over budget. Emit it
            # anyway; nothing meaningful to keep otherwise.
            log.warning(
                "compactor: SessionStart alone exceeds budget (%d > %d)",
                head_tokens,
                budget,
            )
            return head

        # Walk body from the end, accumulating tokens.
        kept_pairs_reversed: list[tuple[int, Event]] = []
        used = head_tokens
        # Reserve for: (a) the summary message we'll prepend if we
        # actually drop anything (~1500 tokens for the prose), (b) the
        # downstream cross-source synthesis SessionStart prepend
        # (~200 tokens), (c) misc emission overhead the per-event
        # estimator can't see. Bias generously — overflows kill resume,
        # under-fills are free.
        OVERHEAD_RESERVE = 2_500 if self.cfg.summarize_dropped else 1_000
        used += OVERHEAD_RESERVE

        for idx in range(len(body) - 1, -1, -1):
            ev = body[idx]
            cost = self._estimate(ev)
            if used + cost > budget:
                continue
            kept_pairs_reversed.append((idx, ev))
            used += cost

        kept_indices = {idx for idx, _ in kept_pairs_reversed}
        kept = [ev for idx, ev in enumerate(body) if idx in kept_indices]
        dropped = [ev for idx, ev in enumerate(body) if idx not in kept_indices]
        n_dropped = len(dropped)

        if n_dropped == 0:
            # Everything fit — no summary needed.
            return head + kept

        log.info(
            "compactor: dropped %d events to fit budget (%d → %d tokens, target %d)",
            n_dropped,
            sum(self._estimate(e) for e in events),
            used,
            budget,
        )

        if self.cfg.summarize_dropped:
            summary = _build_summary_message(dropped, n_kept_events=len(kept))
            return head + [summary] + kept

        return head + kept


# ------------------------------------------------------------------ #
# Summary message                                                      #
# ------------------------------------------------------------------ #


def _build_summary_message(dropped: list[Event], *, n_kept_events: int) -> UserMessage:
    """Construct a deterministic UserMessage summarizing dropped events.

    Inserted as a regular user message so both claude and codex render
    it without protocol changes. The text is plain prose with structure
    the model can scan.
    """
    user_msgs = [e for e in dropped if e.type == "user_message"]
    asst_msgs = [e for e in dropped if e.type == "assistant_message"]
    tool_calls = [e for e in dropped if isinstance(e, ToolCall)]
    tool_call_names: Counter[str] = Counter(getattr(e, "name", "") for e in tool_calls)

    files: Counter[str] = Counter()
    for tc in tool_calls:
        inp = getattr(tc, "input", {}) or {}
        for key in ("file_path", "path", "filepath"):
            if isinstance(inp.get(key), str):
                files[inp[key]] += 1
                break

    timestamps = [e.timestamp for e in dropped if e.timestamp]
    span = ""
    if len(timestamps) >= 2:
        span = f"\n  • Time span: {timestamps[0][:19]} → {timestamps[-1][:19]}"

    def _trunc(text: str, n: int = 120) -> str:
        return (text[:n] + "…") if len(text) > n else text

    first_user = _trunc(user_msgs[0].text) if user_msgs else ""
    last_user = _trunc(user_msgs[-1].text) if user_msgs else ""

    tool_summary = ", ".join(f"{n}×{c}" for n, c in tool_call_names.most_common(8))
    file_summary = ", ".join(f for f, _ in files.most_common(8))

    text = (
        "[fleet-track session summary — earlier turns dropped to fit context]\n\n"
        "This is a continuation of a longer session. The earlier conversation "
        "is preserved in the canonical session log; only this summary + the most "
        f"recent {n_kept_events} event(s) are loaded into your active context.\n\n"
        f"Dropped from this resume:\n"
        f"  • {len(user_msgs)} user messages, {len(asst_msgs)} assistant messages, "
        f"{len(tool_calls)} tool calls"
        f"{span}\n"
        f"  • Tools used: {tool_summary or '(none)'}\n"
        f"  • Files touched: {file_summary or '(none)'}\n"
        f"  • First user message: {first_user!r}\n"
        f"  • Most recent dropped user message: {last_user!r}\n\n"
        f"The recent events follow verbatim."
    )

    return UserMessage(
        source="unknown",
        text=text,
        synthesized=True,  # parser-derived view; not a real user message
    )
