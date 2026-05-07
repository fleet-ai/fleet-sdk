"""FleetCode MCP server.

This module intentionally keeps the `mcp` import inside `create_mcp()` so the
base SDK and normal track tests do not require MCP dependencies. The connector
runtime should install the `fleetcode` extra and run `fleetcode-mcp` with either
`FLEET_API_KEY` or stored `flt login` credentials available to the process.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import Any, Optional

from .api import TrackAPIClient
from .download import ensure_local_session
from .paths import TrackPaths
from .query_schema import (
    AGGREGATE_METRICS,
    SEARCH_FILTER_FIELDS,
    SEARCH_FILTER_OPERATORS,
    SEARCH_LOGICAL_OPERATORS,
    SEARCH_TEXT_FILTER_OPERATORS,
    SEARCH_TEXT_FIELD,
    SEARCH_TIME_FIELDS,
    TEXT_MATCH_OPERATORS,
)

FILTERABLE_ATTRIBUTES = [field["name"] for field in SEARCH_FILTER_FIELDS]
SEARCH_FILTERABLE_ATTRIBUTES = FILTERABLE_ATTRIBUTES + [SEARCH_TEXT_FIELD["name"]]
FILTER_OPERATORS = list(SEARCH_FILTER_OPERATORS)
LOGICAL_OPERATORS = list(SEARCH_LOGICAL_OPERATORS)
SEARCH_MODES = ["hybrid", "keyword", "semantic", "recent"]
SEARCH_TEXT_OPERATORS = list(SEARCH_TEXT_FILTER_OPERATORS)
TEXT_MATCH_OPERATORS_LIST = list(TEXT_MATCH_OPERATORS)
TIME_FIELDS = list(SEARCH_TIME_FIELDS)
FABRIC_SOURCES = ["slack", "linear", "github"]
FABRIC_GROUP_BY = [
    "source",
    "day",
    "hour",
    "channel",
    "author",
    "identifier",
    "state",
    "linear_team",
    "linear_project",
    "linear_state_type",
    "github_repo",
    "github_author",
]


def fleetcode_query_guide() -> dict[str, Any]:
    """Return the FleetCode query contract for agents."""
    return {
        "tools": {
            "fleetcode_search_sessions": {
                "purpose": "Find relevant sessions. Returns hydrated session metadata.",
                "backend": "Turbopuffer via orchestrator",
                "body_fields": {
                    "query": "Natural-language search text.",
                    "mode": SEARCH_MODES,
                    "last_as_prefix": "Treat the final BM25 query token as a prefix.",
                    "text_match": {
                        "purpose": "Full-text filter over indexed session text.",
                        "operators": TEXT_MATCH_OPERATORS_LIST,
                        "shape": {
                            "query": "Text to match.",
                            "operator": "Defaults to all_tokens.",
                            "field": "search_text",
                            "negate": False,
                        },
                    },
                    "limit": "Maximum result count. Defaults to 50.",
                    "filters": "Mongo-style filters over search_filter_attributes.",
                    "time": "Shared time filter, e.g. {'field':'last_active','since':'7d'}.",
                },
                "response_fields": {
                    "items[].content_endpoint": "Relative content URL endpoint for the download tool/API.",
                    "items[].search_match": "Diagnostics: matched_fields, filter_fields, rank_sources, query, mode, and text_match.",
                },
            },
            "fleetcode_aggregate_sessions": {
                "purpose": "Summarize sessions by metadata fields. Returns grouped metrics, not sessions.",
                "backend": "Postgres via orchestrator",
                "body_fields": {
                    "group_by": FILTERABLE_ATTRIBUTES,
                    "metrics": AGGREGATE_METRICS,
                    "filters": "Same Mongo-style filters as search.",
                    "time": "Same time filter as search.",
                    "time_bucket": "Optional bucket: {'field':'last_active','interval':'day'}.",
                    "order_by": "Metric/key ordering, e.g. [{'field':'count','direction':'desc'}].",
                    "having": "Metric filters after grouping, e.g. {'count': {'$gte': 5}}.",
                    "limit": "Maximum number of groups. Defaults server-side.",
                },
            },
            "fleetcode_search_fabric": {
                "purpose": "Search FleetCode Fabric activity across Slack, Linear, and GitHub.",
                "backend": "Postgres Fabric tables via orchestrator",
                "body_fields": {
                    "q": "Natural-language search text.",
                    "sources": FABRIC_SOURCES,
                    "time": "Fabric time filter, e.g. {'since':'7d'} or {'gte':'2026-05-01T00:00:00Z'}.",
                    "limit": "Maximum result count. Defaults server-side.",
                    "cursor": "Opaque pagination cursor returned as next_cursor.",
                },
            },
            "fleetcode_aggregate_fabric": {
                "purpose": "Summarize FleetCode Fabric activity by source, time, and source-specific fields.",
                "backend": "Postgres Fabric tables via orchestrator",
                "body_fields": {
                    "q": "Optional natural-language search text to constrain aggregated entries.",
                    "sources": FABRIC_SOURCES,
                    "time": "Same Fabric time filter as search.",
                    "group_by": FABRIC_GROUP_BY,
                    "order_by": "Metric/key ordering, e.g. [{'field':'count','direction':'desc'}].",
                    "limit": "Maximum number of groups. Defaults server-side.",
                },
            },
            "fleetcode_download_session": {
                "purpose": "Download one session to local cache for exact intra-session analysis.",
                "next_step": "Use local tools such as rg, jq, sed, or Python against the returned JSONL path.",
            },
        },
        "filters": {
            "attributes": FILTERABLE_ATTRIBUTES,
            "search_filter_attributes": SEARCH_FILTERABLE_ATTRIBUTES,
            "search_text_field": dict(SEARCH_TEXT_FIELD),
            "operators": FILTER_OPERATORS,
            "search_text_operators": SEARCH_TEXT_OPERATORS,
            "logical_operators": LOGICAL_OPERATORS,
            "examples": [
                {"tool": "codex"},
                {"event_count": {"$gte": 1000}},
                {"search_text": {"$prefix": "database migr"}},
                {"repo_url": "github.com/fleet-ai/theseus", "tool": "codex"},
                {
                    "$or": [
                        {"repo_url": {"$contains": "theseus"}},
                        {"repo_url": {"$contains": "fleet-sdk"}},
                    ]
                },
            ],
        },
        "time": {
            "fields": TIME_FIELDS,
            "operators": ["since", "gte", "gt", "lte", "lt"],
            "examples": [
                {"field": "last_active", "since": "7d"},
                {"field": "started_at", "gte": "2026-05-01T00:00:00Z"},
            ],
        },
        "examples": {
            "search": {
                "query": "deployment debugging",
                "mode": "hybrid",
                "filters": {"repo_url": {"$contains": "theseus"}},
                "time": {"field": "last_active", "since": "30d"},
                "limit": 25,
            },
            "text_match": {
                "text_match": {"query": "database schema", "operator": "phrase"},
                "filters": {"tool": "codex"},
                "limit": 10,
            },
            "aggregate": {
                "group_by": ["repo_url", "tool"],
                "metrics": ["count", "sum_event_count"],
                "time": {"field": "last_active", "since": "30d"},
                "time_bucket": {"field": "last_active", "interval": "day"},
                "having": {"count": {"$gte": 5}},
                "order_by": [{"field": "count", "direction": "desc"}],
            },
            "fabric_search": {
                "q": "deployment incident",
                "sources": ["slack", "github"],
                "time": {"since": "14d"},
                "limit": 25,
            },
            "fabric_aggregate": {
                "q": "deployment incident",
                "sources": ["linear", "github"],
                "group_by": ["source", "day", "state"],
                "time": {"since": "30d"},
                "order_by": [{"field": "count", "direction": "desc"}],
                "limit": 50,
            },
        },
    }


def _body_dict(body: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(body, Mapping):
        raise TypeError("body must be a JSON object")
    return dict(body)


def _with_api(
    api: Optional[TrackAPIClient],
    fn,
) -> Any:
    if api is not None:
        return fn(api)
    with TrackAPIClient() as client:
        return fn(client)


def fleetcode_search_sessions(
    body: Mapping[str, Any],
    *,
    api: Optional[TrackAPIClient] = None,
) -> dict[str, Any]:
    """Run structured FleetCode session search."""
    payload = _body_dict(body)
    if "limit" not in payload and "top_k" not in payload:
        payload["limit"] = 50
    return _with_api(api, lambda client: client.search_sessions(payload))


def fleetcode_aggregate_sessions(
    body: Mapping[str, Any],
    *,
    api: Optional[TrackAPIClient] = None,
) -> dict[str, Any]:
    """Run structured FleetCode aggregate session query."""
    payload = _body_dict(body)
    return _with_api(api, lambda client: client.aggregate_sessions(payload))


def fleetcode_search_fabric(
    body: Mapping[str, Any],
    *,
    api: Optional[TrackAPIClient] = None,
) -> dict[str, Any]:
    """Run structured FleetCode Fabric search."""
    payload = _body_dict(body)
    return _with_api(api, lambda client: client.search_fabric(payload))


def fleetcode_aggregate_fabric(
    body: Mapping[str, Any],
    *,
    api: Optional[TrackAPIClient] = None,
) -> dict[str, Any]:
    """Run structured FleetCode Fabric aggregate query."""
    payload = _body_dict(body)
    return _with_api(api, lambda client: client.aggregate_fabric(payload))


def fleetcode_download_session(
    session_id: str,
    *,
    force: bool = False,
    api: Optional[TrackAPIClient] = None,
    paths: Optional[TrackPaths] = None,
) -> dict[str, Any]:
    """Download a session to local cache for exact local analysis."""
    cached = _with_api(
        api,
        lambda client: ensure_local_session(
            session_id,
            api=client,
            paths=paths,
            force=force,
        ),
    )
    payload = cached.to_dict()
    path = payload["path"]
    payload["local_analysis"] = {
        "description": "Use local tools against this canonical JSONL file.",
        "examples": {
            "grep": f"rg '<pattern>' {path}",
            "json_messages": f"jq 'select(.type==\"message\")' {path}",
        },
    }
    return payload


def _mcp_install_error_message() -> str:
    if sys.version_info < (3, 10):
        return (
            "FleetCode MCP requires Python 3.10+ and the MCP extra. "
            "Run with Python 3.10+ and install with: "
            "pip install 'fleet-python[fleetcode]'"
        )
    return (
        "FleetCode MCP requires the MCP extra. "
        "Install with: pip install 'fleet-python[fleetcode]'"
    )


def create_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        print(_mcp_install_error_message(), file=sys.stderr)
        raise SystemExit(1) from exc

    mcp = FastMCP("fleetcode")
    search_impl = globals()["fleetcode_search_sessions"]
    aggregate_impl = globals()["fleetcode_aggregate_sessions"]
    fabric_search_impl = globals()["fleetcode_search_fabric"]
    fabric_aggregate_impl = globals()["fleetcode_aggregate_fabric"]
    download_impl = globals()["fleetcode_download_session"]

    @mcp.tool()
    def fleetcode_query_help() -> dict[str, Any]:
        """Return FleetCode search, aggregate, filter, and download guidance."""
        return fleetcode_query_guide()

    @mcp.tool()
    def fleetcode_search_sessions(body: dict[str, Any]) -> dict[str, Any]:
        """Find relevant sessions using structured FleetCode search.

        Body fields: query, mode, last_as_prefix, text_match, limit, filters,
        and time. Modes are hybrid, keyword, semantic, and recent. `text_match`
        supports all_tokens, any_token, phrase, prefix, glob, iglob, and regex
        over search_text. Results include content_endpoint and search_match
        when the server returns match diagnostics.
        """
        return search_impl(body)

    @mcp.tool()
    def fleetcode_aggregate_sessions(body: dict[str, Any]) -> dict[str, Any]:
        """Aggregate tracked session metadata.

        Body fields: group_by, metrics, filters, time, time_bucket, order_by,
        having, and limit. Metrics include counts, event_count summaries, and
        distinct user/device/repo/model counts. No raw SQL is accepted.
        """
        return aggregate_impl(body)

    @mcp.tool()
    def fleetcode_search_fabric(body: dict[str, Any]) -> dict[str, Any]:
        """Search FleetCode Fabric activity.

        Body fields: q, sources, time, limit, and cursor. Sources are slack,
        linear, and github. No raw SQL is accepted.
        """
        return fabric_search_impl(body)

    @mcp.tool()
    def fleetcode_aggregate_fabric(body: dict[str, Any]) -> dict[str, Any]:
        """Aggregate FleetCode Fabric activity.

        Body fields: q, sources, time, group_by, order_by, and limit. Groups
        return count values. Group by source, day, hour, channel, author,
        identifier, state, and source-specific Linear or GitHub fields. No raw
        SQL is accepted.
        """
        return fabric_aggregate_impl(body)

    @mcp.tool()
    def fleetcode_download_session(
        session_id: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """Download one session to local cache for exact analysis.

        Returns a canonical JSONL path. After download, use local tools such as
        rg, jq, sed, or Python against the returned path for intra-session grep
        or transcript analysis.
        """
        return download_impl(session_id, force=force)

    return mcp


def main() -> None:
    """Run the FleetCode MCP server for connector hosts."""
    create_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
