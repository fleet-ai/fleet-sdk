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
    "regex/$regex",
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
        "operators": list(SEARCH_FILTER_OPERATORS),
        "logical_operators": list(SEARCH_LOGICAL_OPERATORS),
        "time_fields": list(SEARCH_TIME_FIELDS),
        "aggregate_metrics": list(AGGREGATE_METRICS),
        "aggregate_features": list(AGGREGATE_FEATURES),
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
            {
                "filters": {
                    "repo_url": "github.com/fleet-ai/theseus",
                    "tool": "codex",
                    "event_count": {"gte": 1000},
                }
            },
        ],
    }
