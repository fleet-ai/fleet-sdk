"""Tests for the Compactor protocol and TruncationCompactor."""

from __future__ import annotations

from fleet.track.compactor import (
    KNOWN_MODELS,
    TokenBudget,
    TruncationCompactor,
    TruncationConfig,
    budget_for,
    estimate_event_tokens,
    estimate_tokens,
)
from fleet.track.unified import (
    AssistantMessage,
    Attachment,
    AssistantReasoning,
    Lifecycle,
    OpaqueEvent,
    SessionStart,
    TokenUsage,
    ToolCall,
    ToolResult,
    UserMessage,
)


# ------------------------------------------------------------------ #
# Token budget                                                         #
# ------------------------------------------------------------------ #


def test_token_budget_usable_applies_margin():
    b = TokenBudget(target=100_000, margin=0.85)
    assert b.usable == 85_000


def test_budget_for_known_model():
    b = budget_for("codex", "gpt-5")
    assert b.target == KNOWN_MODELS["gpt-5"]


def test_budget_for_unknown_model_uses_tool_default():
    b = budget_for("codex", "future-model-no-one-knows")
    assert b.target == 200_000  # codex default


def test_budget_for_unknown_tool_uses_conservative_fallback():
    b = budget_for("future-tool", None)
    assert b.target == 100_000


def test_budget_for_claude_opus_4_7_is_million():
    """The 1M-context model should get the full window in its budget."""
    b = budget_for("claude", "claude-opus-4-7")
    assert b.target == 1_000_000


# ------------------------------------------------------------------ #
# Token estimation                                                     #
# ------------------------------------------------------------------ #


def test_estimate_tokens_returns_at_least_one():
    assert estimate_tokens("a") >= 1


def test_estimate_event_tokens_includes_text_and_overhead():
    short = estimate_event_tokens(UserMessage(source="claude", text="hi"))
    long = estimate_event_tokens(UserMessage(source="claude", text="x" * 4000))
    assert long > short


def test_estimate_event_tokens_includes_tool_input():
    bare = estimate_event_tokens(
        ToolCall(source="claude", tool_call_id="t", name="Bash", input={})
    )
    big_input = estimate_event_tokens(
        ToolCall(
            source="claude",
            tool_call_id="t",
            name="Bash",
            input={"command": "x" * 4000},
        )
    )
    assert big_input > bare


# ------------------------------------------------------------------ #
# TruncationCompactor — drop noise                                     #
# ------------------------------------------------------------------ #


def _generous_budget() -> TokenBudget:
    return TokenBudget(target=10_000_000, margin=1.0)  # effectively unlimited


def test_compactor_drops_attachments_lifecycle_reasoning():
    events: list = [
        UserMessage(source="claude", text="ask"),
        AssistantReasoning(source="claude", text="think"),
        Lifecycle(source="claude", name="ai_title"),
        Attachment(source="claude", media_type="image/png"),
        OpaqueEvent(source="claude", original_type="future"),
        TokenUsage(source="claude", input_tokens=1, output_tokens=1),
        AssistantMessage(source="claude", text="answer"),
    ]
    c = TruncationCompactor(budget=_generous_budget())
    out = c.compact(events)
    types = [e.type for e in out]
    assert types == ["user_message", "assistant_message"]


def test_compactor_drop_flags_independent():
    """Each drop flag controls only its own type."""
    events = [
        UserMessage(source="claude", text="x"),
        Lifecycle(source="claude", name="x"),
    ]
    c = TruncationCompactor(
        budget=_generous_budget(),
        cfg=TruncationConfig(
            drop_lifecycle=False,
            drop_attachments=False,
            drop_reasoning=False,
            drop_opaque=False,
            drop_token_usage=False,
        ),
    )
    out = c.compact(events)
    assert len(out) == 2  # nothing dropped


# ------------------------------------------------------------------ #
# TruncationCompactor — output truncation                              #
# ------------------------------------------------------------------ #


def test_compactor_truncates_large_tool_results():
    big = "x" * 10_000
    c = TruncationCompactor(
        budget=_generous_budget(),
        cfg=TruncationConfig(max_tool_output_chars=100),
    )
    events = [ToolResult(source="claude", tool_call_id="t", output=big)]
    out = c.compact(events)
    assert len(out) == 1
    assert len(out[0].output) < len(big)
    assert "truncated" in out[0].output


def test_compactor_no_truncation_when_cap_is_none():
    big = "x" * 10_000
    c = TruncationCompactor(
        budget=_generous_budget(),
        cfg=TruncationConfig(max_tool_output_chars=None),
    )
    events = [ToolResult(source="claude", tool_call_id="t", output=big)]
    out = c.compact(events)
    assert out[0].output == big


# ------------------------------------------------------------------ #
# TruncationCompactor — budget targeting                               #
# ------------------------------------------------------------------ #


def test_compactor_keeps_everything_when_under_budget():
    events: list = [SessionStart(source="claude", id="s")]
    for i in range(5):
        events.append(UserMessage(source="claude", text=f"q{i}"))
        events.append(AssistantMessage(source="claude", text=f"a{i}"))

    # Generous budget: nothing should be dropped (and no summary).
    c = TruncationCompactor(budget=_generous_budget())
    out = c.compact(events)
    assert len(out) == len(events)
    assert all("session summary" not in getattr(e, "text", "") for e in out)


def test_compactor_drops_oldest_when_over_budget():
    """A tight budget should keep tail events, drop early ones, prepend a summary."""
    events: list = [SessionStart(source="claude", id="s")]
    for i in range(20):
        events.append(UserMessage(source="claude", text="x" * 500))
        events.append(AssistantMessage(source="claude", text="y" * 500))

    # Budget tight enough that we can't fit all 40 large messages.
    c = TruncationCompactor(budget=TokenBudget(target=2_000, margin=1.0))
    out = c.compact(events)

    # Head: SessionStart preserved.
    assert out[0].type == "session_start"
    # Summary present.
    assert any("session summary" in getattr(e, "text", "").lower() for e in out)
    # Output is shorter than input.
    assert len(out) < len(events)


def test_compactor_keeps_contiguous_recent_suffix_when_middle_event_is_oversized():
    events = [
        UserMessage(source="claude", text="older small"),
        UserMessage(source="claude", text="oversized"),
        UserMessage(source="claude", text="newer small"),
    ]

    def estimate(ev):
        return 300 if getattr(ev, "text", "") == "oversized" else 100

    c = TruncationCompactor(
        budget=TokenBudget(target=1_200, margin=1.0),
        cfg=TruncationConfig(summarize_dropped=False),
        token_estimator=estimate,
    )

    out = c.compact(events)

    assert [e.text for e in out] == ["newer small"]


def test_compactor_summary_can_be_disabled():
    events: list = []
    for i in range(20):
        events.append(UserMessage(source="claude", text="x" * 500))

    c = TruncationCompactor(
        budget=TokenBudget(target=2_000, margin=1.0),
        cfg=TruncationConfig(summarize_dropped=False),
    )
    out = c.compact(events)
    # No summary message present.
    assert not any("session summary" in getattr(e, "text", "").lower() for e in out)


def test_compactor_summary_includes_dropped_metadata():
    events: list = []
    for i in range(10):
        events.append(UserMessage(source="claude", text=f"q{i}"))
        events.append(
            ToolCall(
                source="claude",
                tool_call_id=f"t{i}",
                name="Bash",
                input={"command": "x" * 200},
            )
        )
        events.append(
            ToolResult(source="claude", tool_call_id=f"t{i}", output="y" * 200)
        )
        events.append(AssistantMessage(source="claude", text=f"a{i}"))

    # Tight budget so we drop a bunch of turns.
    c = TruncationCompactor(budget=TokenBudget(target=1_500, margin=1.0))
    out = c.compact(events)

    summaries = [e for e in out if "session summary" in getattr(e, "text", "").lower()]
    assert len(summaries) == 1
    s = summaries[0].text
    # Spot-check structural fields appear.
    assert "user messages" in s
    assert "tool calls" in s
    assert "Bash" in s


def test_compactor_preserves_session_start_at_head():
    """SessionStart at the very front survives even with a tight budget."""
    events: list = [SessionStart(source="claude", id="s")]
    for _ in range(50):
        events.append(UserMessage(source="claude", text="x" * 1000))

    c = TruncationCompactor(budget=TokenBudget(target=500, margin=1.0))
    out = c.compact(events)
    assert out[0].type == "session_start"


# ------------------------------------------------------------------ #
# Compactor protocol shape                                             #
# ------------------------------------------------------------------ #


def test_truncation_compactor_satisfies_protocol():
    """TruncationCompactor implements the Compactor protocol structurally."""
    from fleet.track.compactor import Compactor

    c: Compactor = TruncationCompactor(budget=_generous_budget())
    out = c.compact([UserMessage(source="claude", text="x")])
    assert len(out) == 1
