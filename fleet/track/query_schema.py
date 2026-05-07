"""Shared schema descriptions for Fleet track query tools."""

from __future__ import annotations

SEARCH_FILTER_FIELDS = (
    {
        "name": "session_id",
        "type": "string",
        "description": "Fleet session id.",
    },
    {
        "name": "user_id",
        "type": "string",
        "description": "Fleet user id that owns the session.",
    },
    {
        "name": "device_id",
        "type": "string",
        "description": "Tracked local device id.",
    },
    {
        "name": "tool",
        "type": "string",
        "description": "AI tool name, for example codex or claude.",
    },
    {
        "name": "cwd",
        "type": "string",
        "description": "Working directory captured for the session.",
    },
    {
        "name": "repo_url",
        "type": "string",
        "description": "Detected repository remote URL.",
    },
    {
        "name": "git_branch",
        "type": "string",
        "description": "Detected git branch.",
    },
    {
        "name": "model",
        "type": "string",
        "description": "Model name when captured by the source tool.",
    },
    {
        "name": "forked_from",
        "type": "string",
        "description": "Parent Fleet session id when this session was forked.",
    },
    {
        "name": "event_count",
        "type": "integer",
        "description": "Number of tracked events in the session.",
    },
    {
        "name": "started_at",
        "type": "datetime",
        "description": "Session start timestamp in ISO-8601 format.",
    },
    {
        "name": "last_active",
        "type": "datetime",
        "description": "Most recent session activity timestamp in ISO-8601 format.",
    },
)
SEARCH_TEXT_FIELD = {
    "name": "search_text",
    "type": "full-text string",
    "description": (
        "Indexed session text for search only. Use with text operators such as "
        "$all_tokens, $any_token, $phrase, $prefix, $glob, $iglob, or $regex."
    ),
}

SEARCH_FILTER_OPERATORS = (
    "eq/$eq",
    "ne/$ne",
    "in/$in",
    "nin/$nin",
    "gt/$gt",
    "gte/$gte",
    "lt/$lt",
    "lte/$lte",
    "contains/$contains",
    "glob/$glob",
    "iglob/$iglob",
    "regex/$regex",
)
SEARCH_TEXT_FILTER_OPERATORS = (
    "all_tokens/$all_tokens",
    "any_token/$any_token",
    "phrase/$phrase",
    "prefix/$prefix",
    "glob/$glob",
    "iglob/$iglob",
    "regex/$regex",
)
TEXT_MATCH_OPERATORS = (
    "all_tokens",
    "any_token",
    "phrase",
    "prefix",
    "glob",
    "iglob",
    "regex",
)

SEARCH_LOGICAL_OPERATORS = ("$and", "$or", "$not", "$nor")
SEARCH_TIME_FIELDS = ("last_active", "started_at")

AGGREGATE_METRICS = (
    "count",
    "sum_event_count",
    "min_event_count",
    "max_event_count",
    "avg_event_count",
    "distinct_user_count",
    "distinct_device_count",
    "distinct_repo_count",
    "distinct_model_count",
)
AGGREGATE_FEATURES = ("time_bucket", "order_by", "having")


def search_filter_catalog() -> dict:
    return {
        "description": "Structured Fleet session filters. Orchestrator compiles these to Postgres or Turbopuffer as needed.",
        "filterable_attributes": list(SEARCH_FILTER_FIELDS),
        "search_text_field": dict(SEARCH_TEXT_FIELD),
        "operators": list(SEARCH_FILTER_OPERATORS),
        "search_text_operators": list(SEARCH_TEXT_FILTER_OPERATORS),
        "text_match_operators": list(TEXT_MATCH_OPERATORS),
        "logical_operators": list(SEARCH_LOGICAL_OPERATORS),
        "time_fields": list(SEARCH_TIME_FIELDS),
        "aggregate_metrics": list(AGGREGATE_METRICS),
        "aggregate_features": list(AGGREGATE_FEATURES),
        "search_body_fields": {
            "query": "Natural-language ranked query.",
            "mode": ["hybrid", "keyword", "semantic", "recent"],
            "last_as_prefix": (
                "For BM25 keyword/hybrid query ranking, treat the final query "
                "token as a prefix."
            ),
            "text_match": (
                "Full-text filter: {'query': str, 'operator': one of "
                "text_match_operators, 'field': 'search_text', 'negate': bool}."
            ),
            "filters": "Mongo-style filters over metadata fields plus search_text.",
            "time": "Shared time filter, e.g. {'field': 'last_active', 'since': '7d'}.",
            "limit": "Maximum result count.",
        },
        "response_fields": {
            "content_endpoint": (
                "Relative API path for retrieving the session content URL."
            ),
            "search_match": (
                "Search diagnostics with matched_fields, filter_fields, "
                "rank_sources, query, mode, and text_match."
            ),
        },
        "examples": [
            {"filters": {"tool": "codex"}},
            {
                "filters": {
                    "$or": [
                        {"repo_url": {"$contains": "theseus"}},
                        {"repo_url": {"$contains": "fleet-sdk"}},
                    ],
                    "event_count": {"$gte": 1000},
                }
            },
            {"time": {"field": "last_active", "since": "7d"}},
            {"text_match": {"query": "shit", "operator": "all_tokens"}},
            {
                "query": "schema migr",
                "last_as_prefix": True,
                "filters": {"search_text": {"$prefix": "database schem"}},
            },
            {
                "filters": {
                    "repo_url": "github.com/fleet-ai/theseus",
                    "tool": "codex",
                    "event_count": {"gte": 1000},
                }
            },
        ],
    }
