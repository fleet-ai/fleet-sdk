"""A schema‑agnostic, SQL‑native DSL for snapshot validation and diff invariants.

The module extends your original `DatabaseSnapshot` implementation with

* A **Supabase‑style query builder** (method‑chaining: `select`, `eq`, `join`, …).
* Assertion helpers (`assert_exists`, `assert_none`, `assert_eq`, `count().assert_eq`, …).
* A `SnapshotDiff` engine that enforces invariants (`expect_only`, `expect`).
* Convenience helpers (`expect_row`, `expect_rows`, `expect_absent_row`).

The public API stays tiny yet composable; everything else is built on
orthogonal primitives so it works for *any* relational schema.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any
import json

from fleet.verifiers.diff_validation import validate_diff_expect_exactly

################################################################################
#  Low‑level helpers
################################################################################

from typing import Union, Tuple, Dict, List, Optional, Any, Set

SQLValue = Union[str, int, float, None]
Condition = Tuple[str, str, SQLValue]  # (column, op, value)
JoinSpec = Tuple[str, Dict[str, str]]  # (table, on mapping)


def _is_json_string(value: Any) -> bool:
    """Check if a value looks like a JSON string."""
    if not isinstance(value, str):
        return False
    value = value.strip()
    return (value.startswith("{") and value.endswith("}")) or (
        value.startswith("[") and value.endswith("]")
    )


def _values_equivalent(val1: Any, val2: Any) -> bool:
    """Compare two values, using JSON semantic comparison for JSON strings."""
    # If both are exactly equal, return True
    if val1 == val2:
        return True

    # If both look like JSON strings, try semantic comparison
    if _is_json_string(val1) and _is_json_string(val2):
        try:
            parsed1 = json.loads(val1)
            parsed2 = json.loads(val2)
            return parsed1 == parsed2
        except (json.JSONDecodeError, TypeError):
            # If parsing fails, fall back to string comparison
            pass

    # Default to exact comparison
    return val1 == val2


class _CountResult:
    """Wraps an integer count so we can chain assertions fluently."""

    def __init__(self, value: int):
        self.value = value

    # Assertions ------------------------------------------------------------
    def assert_eq(self, expected: int):
        if self.value != expected:
            raise AssertionError(f"Expected {expected}, got {self.value}")
        return self

    def assert_gt(self, threshold: int):
        if self.value <= threshold:
            raise AssertionError(f"Expected > {threshold}, got {self.value}")
        return self

    def assert_between(self, low: int, high: int):
        if not low <= self.value <= high:
            raise AssertionError(f"Expected {low}‑{high}, got {self.value}")
        return self

    # Convenience -----------------------------------------------------------
    def __int__(self):
        return self.value

    def __repr__(self):
        return f"<Count {self.value}>"


################################################################################
#  Query Builder
################################################################################


class QueryBuilder:
    """Fluent SQL builder executed against a single `DatabaseSnapshot`."""

    def __init__(self, snapshot: "DatabaseSnapshot", table: str):  # noqa: UP037
        self._snapshot = snapshot
        self._table = table
        self._select_cols: List[str] = ["*"]
        self._conditions: List[Condition] = []
        self._joins: List[JoinSpec] = []
        self._limit: Optional[int] = None
        self._order_by: Optional[str] = None
        # Cache for idempotent executions
        self._cached_rows: Optional[List[Dict[str, Any]]] = None

    # ---------------------------------------------------------------------
    #  Column projection / limiting / ordering
    # ---------------------------------------------------------------------
    def select(self, *columns: str) -> "QueryBuilder":  # noqa: UP037
        qb = self._clone()
        qb._select_cols = list(columns) if columns else ["*"]
        return qb

    def limit(self, n: int) -> "QueryBuilder":  # noqa: UP037
        qb = self._clone()
        qb._limit = n
        return qb

    def sort(self, column: str, desc: bool = False) -> "QueryBuilder":  # noqa: UP037
        qb = self._clone()
        qb._order_by = f"{column} {'DESC' if desc else 'ASC'}"
        return qb

    # ---------------------------------------------------------------------
    #  WHERE helpers (SQL‑like)
    # ---------------------------------------------------------------------
    def _add_condition(self, column: str, op: str, value: SQLValue) -> "QueryBuilder":  # noqa: UP037
        qb = self._clone()
        qb._conditions.append((column, op, value))
        return qb

    def eq(self, column: str, value: SQLValue) -> "QueryBuilder":  # noqa: UP037
        return self._add_condition(column, "=", value)

    def neq(self, column: str, value: SQLValue) -> "QueryBuilder":  # noqa: UP037
        return self._add_condition(column, "!=", value)

    def gt(self, column: str, value: SQLValue) -> "QueryBuilder":  # noqa: UP037
        return self._add_condition(column, ">", value)

    def gte(self, column: str, value: SQLValue) -> "QueryBuilder":  # noqa: UP037
        return self._add_condition(column, ">=", value)

    def lt(self, column: str, value: SQLValue) -> "QueryBuilder":  # noqa: UP037
        return self._add_condition(column, "<", value)

    def lte(self, column: str, value: SQLValue) -> "QueryBuilder":  # noqa: UP037
        return self._add_condition(column, "<=", value)

    def in_(self, column: str, values: List[SQLValue]) -> "QueryBuilder":  # noqa: UP037
        qb = self._clone()
        qb._conditions.append((column, "IN", tuple(values)))
        return qb

    def not_in(self, column: str, values: List[SQLValue]) -> "QueryBuilder":  # noqa: UP037
        qb = self._clone()
        qb._conditions.append((column, "NOT IN", tuple(values)))
        return qb

    def is_null(self, column: str) -> "QueryBuilder":  # noqa: UP037
        return self._add_condition(column, "IS", None)

    def not_null(self, column: str) -> "QueryBuilder":  # noqa: UP037
        return self._add_condition(column, "IS NOT", None)

    def ilike(self, column: str, pattern: str) -> "QueryBuilder":  # noqa: UP037
        qb = self._clone()
        qb._conditions.append((column, "ILIKE", pattern))
        return qb

    # ---------------------------------------------------------------------
    #  JOIN (simple inner join)
    # ---------------------------------------------------------------------
    def join(self, other_table: str, on: Dict[str, str]) -> "QueryBuilder":  # noqa: UP037
        """`on` expects {local_col: remote_col}."""
        qb = self._clone()
        qb._joins.append((other_table, on))
        return qb

    # ---------------------------------------------------------------------
    #  Execution helpers
    # ---------------------------------------------------------------------
    def _compile(self) -> Tuple[str, List[Any]]:
        cols = ", ".join(self._select_cols)
        sql = [f"SELECT {cols} FROM {self._table}"]
        params: List[Any] = []

        # Joins -------------------------------------------------------------
        for tbl, onmap in self._joins:
            join_clauses = [
                f"{self._table}.{l} = {tbl}.{r}"
                for l, r in onmap.items()  # noqa: E741
            ]
            sql.append(f"JOIN {tbl} ON {' AND '.join(join_clauses)}")

        # WHERE -------------------------------------------------------------
        if self._conditions:
            placeholders = []
            for col, op, val in self._conditions:
                if op in ("IN", "NOT IN") and isinstance(val, tuple):
                    ph = ", ".join(["?" for _ in val])
                    placeholders.append(f"{col} {op} ({ph})")
                    params.extend(val)
                elif op in ("IS", "IS NOT"):
                    placeholders.append(f"{col} {op} NULL")
                elif op == "ILIKE":
                    placeholders.append(
                        f"{col} LIKE ?"
                    )  # SQLite has no ILIKE; LIKE is case‑insensitive when in NOCASE collation
                    params.append(val)
                else:
                    placeholders.append(f"{col} {op} ?")
                    params.append(val)
            sql.append("WHERE " + " AND ".join(placeholders))

        # ORDER / LIMIT -----------------------------------------------------
        if self._order_by:
            sql.append(f"ORDER BY {self._order_by}")
        if self._limit is not None:
            sql.append(f"LIMIT {self._limit}")

        return " ".join(sql), params

    def _execute(self) -> List[Dict[str, Any]]:
        if self._cached_rows is not None:
            return self._cached_rows

        sql, params = self._compile()
        conn = sqlite3.connect(self._snapshot.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        self._cached_rows = rows
        return rows

    # ---------------------------------------------------------------------
    #  High‑level result helpers / assertions
    # ---------------------------------------------------------------------
    def count(self) -> _CountResult:
        qb = self.select("COUNT(*) AS __cnt__").limit(
            None
        )  # remove limit since counting overrides
        sql, params = qb._compile()
        conn = sqlite3.connect(self._snapshot.db_path)
        cur = conn.cursor()
        cur.execute(sql, params)
        val = cur.fetchone()[0] or 0
        cur.close()
        conn.close()
        return _CountResult(val)

    def first(self) -> Optional[Dict[str, Any]]:
        return self.limit(1)._execute()[0] if self.limit(1)._execute() else None

    def all(self) -> List[Dict[str, Any]]:
        return self._execute()

    # Assertions -----------------------------------------------------------
    def assert_exists(self):
        row = self.first()
        if row is None:
            # Build descriptive error message
            sql, params = self._compile()
            error_msg = (
                f"Expected at least one matching row, but found none.\n"
                f"Query: {sql}\n"
                f"Parameters: {params}\n"
                f"Table: {self._table}"
            )
            if hasattr(self, "_conditions") and self._conditions:
                conditions_str = ", ".join(
                    [f"{col} {op} {val}" for col, op, val in self._conditions]
                )
                error_msg += f"\nConditions: {conditions_str}"
            raise AssertionError(error_msg)
        return self

    def assert_none(self):
        row = self.first()
        if row is not None:
            row_id = _get_row_identifier(row)
            row_data = _format_row_for_error(row)
            sql, params = self._compile()
            error_msg = (
                f"Expected no matching rows, but found at least one.\n"
                f"Found row: {row_id}\n"
                f"Row data: {row_data}\n"
                f"Query: {sql}\n"
                f"Parameters: {params}\n"
                f"Table: {self._table}"
            )
            raise AssertionError(error_msg)
        return self

    def assert_eq(self, column: str, value: SQLValue):
        row = self.first()
        if row is None:
            sql, params = self._compile()
            error_msg = (
                f"Row not found for equality assertion.\n"
                f"Expected to find a row with {column}={repr(value)}\n"
                f"Query: {sql}\n"
                f"Parameters: {params}\n"
                f"Table: {self._table}"
            )
            raise AssertionError(error_msg)

        actual_value = row.get(column)
        if actual_value != value:
            row_id = _get_row_identifier(row)
            row_data = _format_row_for_error(row)
            error_msg = (
                f"Field value assertion failed.\n"
                f"Row: {row_id}\n"
                f"Field: {column}\n"
                f"Expected: {repr(value)}\n"
                f"Actual: {repr(actual_value)}\n"
                f"Full row data: {row_data}\n"
                f"Table: {self._table}"
            )
            raise AssertionError(error_msg)
        return self

    # Misc -----------------------------------------------------------------
    def explain(self) -> str:
        sql, params = self._compile()
        return f"SQL: {sql}\nParams: {params}"

    # Utilities ------------------------------------------------------------
    def _clone(self) -> "QueryBuilder":  # noqa: UP037
        qb = QueryBuilder(self._snapshot, self._table)
        qb._select_cols = list(self._select_cols)
        qb._conditions = list(self._conditions)
        qb._joins = list(self._joins)
        qb._limit = self._limit
        qb._order_by = self._order_by
        return qb

    # Representation -------------------------------------------------------
    def __repr__(self):
        return f"<QueryBuilder {self.explain()}>"


################################################################################
#  Snapshot Diff invariants
################################################################################


class IgnoreConfig:
    """Configuration for ignoring specific tables, fields, or combinations during diff operations."""

    def __init__(
        self,
        tables: Optional[Set[str]] = None,
        fields: Optional[Set[str]] = None,
        table_fields: Optional[Dict[str, Set[str]]] = None,
    ):
        """
        Args:
            tables: Set of table names to completely ignore
            fields: Set of field names to ignore across all tables
            table_fields: Dict mapping table names to sets of field names to ignore in that table
        """
        self.tables = tables or set()
        self.fields = fields or set()
        self.table_fields = table_fields or {}

    def should_ignore_table(self, table: str) -> bool:
        """Check if a table should be completely ignored."""
        return table in self.tables

    def should_ignore_field(self, table: str, field: str) -> bool:
        """Check if a specific field in a table should be ignored."""
        # Global field ignore
        if field in self.fields:
            return True
        # Table-specific field ignore
        if table in self.table_fields and field in self.table_fields[table]:
            return True
        return False


def _format_row_for_error(row: Dict[str, Any], max_fields: int = 10) -> str:
    """Format a row dictionary for error messages with truncation if needed."""
    if not row:
        return "{empty row}"

    items = list(row.items())
    if len(items) <= max_fields:
        formatted_items = [f"{k}={repr(v)}" for k, v in items]
        return "{" + ", ".join(formatted_items) + "}"
    else:
        # Show first few fields and indicate truncation
        shown_items = [f"{k}={repr(v)}" for k, v in items[:max_fields]]
        remaining = len(items) - max_fields
        return "{" + ", ".join(shown_items) + f", ... +{remaining} more fields" + "}"


def _get_row_identifier(row: Dict[str, Any]) -> str:
    """Extract a meaningful identifier from a row for error messages."""
    # Try common ID fields first
    for id_field in ["id", "pk", "primary_key", "key"]:
        if id_field in row and row[id_field] is not None:
            return f"{id_field}={repr(row[id_field])}"

    # Try name fields
    for name_field in ["name", "title", "label"]:
        if name_field in row and row[name_field] is not None:
            return f"{name_field}={repr(row[name_field])}"

    # Fall back to first non-None field
    for key, value in row.items():
        if value is not None:
            return f"{key}={repr(value)}"

    return "no identifier found"


class SnapshotDiff:
    """Compute & validate changes between two snapshots."""

    def __init__(
        self,
        before: DatabaseSnapshot,
        after: DatabaseSnapshot,
        ignore_config: Optional[IgnoreConfig] = None,
    ):
        from .sql_differ import SQLiteDiffer  # local import to avoid circularity

        self.before = before
        self.after = after
        self.ignore_config = ignore_config or IgnoreConfig()
        self._differ = SQLiteDiffer(before.db_path, after.db_path)
        self._cached: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    def _collect(self):
        if self._cached is not None:
            return self._cached
        all_tables = set(self.before.tables()) | set(self.after.tables())
        diff: Dict[str, Dict[str, Any]] = {}
        for tbl in all_tables:
            if self.ignore_config.should_ignore_table(tbl):
                continue
            diff[tbl] = self._differ.diff_table(tbl)
        self._cached = diff
        return diff

    # ------------------------------------------------------------------
    def expect_only(self, allowed_changes: List[Dict[str, Any]]):
        """Allowed changes is a list of {table, pk, field, after} (before optional)."""
        diff = self._collect()

        def _is_change_allowed(
            table: str, row_id: str, field: Optional[str], after_value: Any
        ) -> bool:
            """Check if a change is in the allowed list using semantic comparison."""
            for allowed in allowed_changes:
                allowed_pk = allowed.get("pk")
                # Handle type conversion for primary key comparison
                # Convert both to strings for comparison to handle int/string mismatches
                pk_match = (
                    str(allowed_pk) == str(row_id) if allowed_pk is not None else False
                )

                if (
                    allowed["table"] == table
                    and pk_match
                    and allowed.get("field") == field
                    and _values_equivalent(allowed.get("after"), after_value)
                ):
                    return True
            return False

        # Collect all unexpected changes for detailed reporting
        unexpected_changes = []

        for tbl, report in diff.items():
            for row in report.get("modified_rows", []):
                for f, vals in row["changes"].items():
                    if self.ignore_config.should_ignore_field(tbl, f):
                        continue
                    if not _is_change_allowed(tbl, row["row_id"], f, vals["after"]):
                        unexpected_changes.append(
                            {
                                "type": "modification",
                                "table": tbl,
                                "row_id": row["row_id"],
                                "field": f,
                                "before": vals.get("before"),
                                "after": vals["after"],
                                "full_row": row,
                            }
                        )

            for row in report.get("added_rows", []):
                if not _is_change_allowed(tbl, row["row_id"], None, "__added__"):
                    unexpected_changes.append(
                        {
                            "type": "insertion",
                            "table": tbl,
                            "row_id": row["row_id"],
                            "field": None,
                            "after": "__added__",
                            "full_row": row,
                        }
                    )

            for row in report.get("removed_rows", []):
                if not _is_change_allowed(tbl, row["row_id"], None, "__removed__"):
                    unexpected_changes.append(
                        {
                            "type": "deletion",
                            "table": tbl,
                            "row_id": row["row_id"],
                            "field": None,
                            "after": "__removed__",
                            "full_row": row,
                        }
                    )

        if unexpected_changes:
            # Build comprehensive error message
            error_lines = ["Unexpected database changes detected:"]
            error_lines.append("")

            for i, change in enumerate(
                unexpected_changes[:5], 1
            ):  # Show first 5 changes
                error_lines.append(
                    f"{i}. {change['type'].upper()} in table '{change['table']}':"
                )
                error_lines.append(f"   Row ID: {change['row_id']}")

                if change["type"] == "modification":
                    error_lines.append(f"   Field: {change['field']}")
                    error_lines.append(f"   Before: {repr(change['before'])}")
                    error_lines.append(f"   After: {repr(change['after'])}")
                elif change["type"] == "insertion":
                    error_lines.append("   New row added")
                elif change["type"] == "deletion":
                    error_lines.append("   Row deleted")

                # Show some context from the row
                if "full_row" in change and change["full_row"]:
                    row_data = change["full_row"]
                    if change["type"] == "modification" and "data" in row_data:
                        # For modifications, show the current state
                        formatted_row = _format_row_for_error(
                            row_data.get("data", {}), max_fields=5
                        )
                        error_lines.append(f"   Row data: {formatted_row}")
                    elif (
                        change["type"] in ["insertion", "deletion"]
                        and "data" in row_data
                    ):
                        # For insertions/deletions, show the row data
                        formatted_row = _format_row_for_error(
                            row_data.get("data", {}), max_fields=5
                        )
                        error_lines.append(f"   Row data: {formatted_row}")

                error_lines.append("")

            if len(unexpected_changes) > 5:
                error_lines.append(
                    f"... and {len(unexpected_changes) - 5} more unexpected changes"
                )
                error_lines.append("")

            # Show what changes were allowed
            error_lines.append("Allowed changes were:")
            if allowed_changes:
                for i, allowed in enumerate(allowed_changes[:3], 1):
                    error_lines.append(
                        f"  {i}. Table: {allowed.get('table')}, "
                        f"ID: {allowed.get('pk')}, "
                        f"Field: {allowed.get('field')}, "
                        f"After: {repr(allowed.get('after'))}"
                    )
                if len(allowed_changes) > 3:
                    error_lines.append(
                        f"  ... and {len(allowed_changes) - 3} more allowed changes"
                    )
            else:
                error_lines.append("  (No changes were allowed)")

            raise AssertionError("\n".join(error_lines))

        return self

    # ------------------------------------------------------------------
    def expect_only_v2(self, allowed_changes: List[Dict[str, Any]]):
        """Allowed changes with bulk field spec support and explicit type field.

        This version supports explicit change types via the "type" field:
        1. Insert specs: {"table": "t", "pk": 1, "type": "insert", "fields": [("name", "value"), ("status", ...)]}
           - ("name", value): check that field equals value
           - ("name", None): check that field is SQL NULL
           - ("name", ...): don't check the value, just acknowledge the field exists
        2. Modify specs: {"table": "t", "pk": 1, "type": "modify", "resulting_fields": [...], "no_other_changes": True/False}
           - Uses "resulting_fields" (not "fields") to be explicit about what's being checked
           - "no_other_changes" is REQUIRED and must be True or False:
             - True: Every changed field must be in resulting_fields (strict mode)
             - False: Only check fields in resulting_fields match, ignore other changes
           - ("field_name", value): check that after value equals value
           - ("field_name", None): check that after value is SQL NULL
           - ("field_name", ...): don't check value, just acknowledge field changed
        3. Delete specs:
           - Without field validation: {"table": "t", "pk": 1, "type": "delete"}
           - With field validation: {"table": "t", "pk": 1, "type": "delete", "fields": [...]}
        4. Whole-row specs (legacy):
           - For additions: {"table": "t", "pk": 1, "fields": None, "after": "__added__"}
           - For deletions: {"table": "t", "pk": 1, "fields": None, "after": "__removed__"}
        
        When using "fields" for inserts, every field must be accounted for in the list.
        For modifications, use "resulting_fields" with explicit "no_other_changes".
        For deletions with "fields", all specified fields are validated against the deleted row.
        """
        diff = self._collect()

        def _is_change_allowed(
            table: str, row_id: str, field: Optional[str], after_value: Any
        ) -> bool:
            """Check if a change is in the allowed list using semantic comparison."""
            for allowed in allowed_changes:
                allowed_pk = allowed.get("pk")
                # Handle type conversion for primary key comparison
                # Convert both to strings for comparison to handle int/string mismatches
                pk_match = (
                    str(allowed_pk) == str(row_id) if allowed_pk is not None else False
                )

                # For whole-row specs, check "fields": None; for field-level, check "field"
                field_match = (
                    ("fields" in allowed and allowed.get("fields") is None)
                    if field is None
                    else allowed.get("field") == field
                )
                if (
                    allowed["table"] == table
                    and pk_match
                    and field_match
                    and _values_equivalent(allowed.get("after"), after_value)
                ):
                    return True
            return False

        def _get_fields_spec_for_type(table: str, row_id: str, change_type: str) -> Optional[List[tuple]]:
            """Get the bulk fields spec for a given table/row/type if it exists.
            
            Args:
                table: The table name
                row_id: The primary key value
                change_type: One of "insert", "modify", or "delete"
                
            Note: For "modify" type, use _get_modify_spec instead.
            """
            for allowed in allowed_changes:
                allowed_pk = allowed.get("pk")
                pk_match = (
                    str(allowed_pk) == str(row_id) if allowed_pk is not None else False
                )
                if (
                    allowed["table"] == table
                    and pk_match
                    and allowed.get("type") == change_type
                    and "fields" in allowed
                ):
                    return allowed["fields"]
            return None

        def _get_modify_spec(table: str, row_id: str) -> Optional[Dict[str, Any]]:
            """Get the modify spec for a given table/row if it exists.
            
            Returns the full spec dict containing:
            - resulting_fields: List of field tuples
            - no_other_changes: Boolean (required)
            
            Returns None if no modify spec found.
            """
            for allowed in allowed_changes:
                allowed_pk = allowed.get("pk")
                pk_match = (
                    str(allowed_pk) == str(row_id) if allowed_pk is not None else False
                )
                if (
                    allowed["table"] == table
                    and pk_match
                    and allowed.get("type") == "modify"
                ):
                    return allowed
            return None

        def _is_type_allowed(table: str, row_id: str, change_type: str) -> bool:
            """Check if a change type is allowed for the given table/row (with or without fields)."""
            for allowed in allowed_changes:
                allowed_pk = allowed.get("pk")
                pk_match = (
                    str(allowed_pk) == str(row_id) if allowed_pk is not None else False
                )
                if allowed["table"] == table and pk_match and allowed.get("type") == change_type:
                    return True
            return False

        def _parse_fields_spec(fields_spec: List[tuple]) -> Dict[str, tuple]:
            """Parse a fields spec into a mapping of field_name -> (should_check_value, expected_value)."""
            spec_map: Dict[str, tuple] = {}
            for spec_tuple in fields_spec:
                if len(spec_tuple) != 2:
                    raise ValueError(
                        f"Invalid field spec tuple: {spec_tuple}. "
                        f"Expected 2-tuple like ('field', value), ('field', None), or ('field', ...)"
                    )
                field_name, expected_value = spec_tuple
                if expected_value is ...:
                    # Ellipsis: don't check value, just acknowledge field exists
                    spec_map[field_name] = (False, None)
                else:
                    # Any other value (including None for NULL check): check value
                    spec_map[field_name] = (True, expected_value)
            return spec_map

        def _validate_row_with_fields_spec(
            table: str,
            row_id: str,
            row_data: Dict[str, Any],
            fields_spec: List[tuple],
        ) -> Optional[List[tuple]]:
            """Validate a row against a bulk fields spec.

            Returns None if validation passes, or a list of (field, actual_value, issue)
            tuples for mismatches.
            
            Field spec semantics:
            - ("field_name", value): check that field equals value
            - ("field_name", None): check that field is SQL NULL
            - ("field_name", ...): don't check value (acknowledge field exists)
            """
            spec_map = _parse_fields_spec(fields_spec)
            unmatched_fields = []

            for field_name, field_value in row_data.items():
                # Skip rowid as it's internal
                if field_name == "rowid":
                    continue
                # Skip ignored fields
                if self.ignore_config.should_ignore_field(table, field_name):
                    continue

                if field_name not in spec_map:
                    # Field not in spec - this is an error
                    unmatched_fields.append(
                        (field_name, field_value, "NOT_IN_FIELDS_SPEC")
                    )
                else:
                    should_check, expected_value = spec_map[field_name]
                    if should_check and not _values_equivalent(
                        expected_value, field_value
                    ):
                        # Value doesn't match
                        unmatched_fields.append(
                            (field_name, field_value, f"expected {repr(expected_value)}")
                        )

            return unmatched_fields if unmatched_fields else None

        def _validate_modification_with_fields_spec(
            table: str,
            row_id: str,
            row_changes: Dict[str, Dict[str, Any]],
            resulting_fields: List[tuple],
            no_other_changes: bool,
        ) -> Optional[List[tuple]]:
            """Validate a modification against a resulting_fields spec.

            Returns None if validation passes, or a list of (field, actual_value, issue)
            tuples for mismatches.
            
            Args:
                table: The table name
                row_id: The row primary key
                row_changes: Dict of field_name -> {"before": ..., "after": ...}
                resulting_fields: List of field tuples to validate
                no_other_changes: If True, all changed fields must be in resulting_fields.
                                  If False, only validate fields in resulting_fields, ignore others.
            
            Field spec semantics for modifications:
            - ("field_name", value): check that after value equals value
            - ("field_name", None): check that after value is SQL NULL
            - ("field_name", ...): don't check value, just acknowledge field changed
            """
            spec_map = _parse_fields_spec(resulting_fields)
            unmatched_fields = []

            for field_name, vals in row_changes.items():
                # Skip ignored fields
                if self.ignore_config.should_ignore_field(table, field_name):
                    continue

                after_value = vals["after"]

                if field_name not in spec_map:
                    # Changed field not in spec
                    if no_other_changes:
                        # Strict mode: all changed fields must be accounted for
                        unmatched_fields.append(
                            (field_name, after_value, "NOT_IN_RESULTING_FIELDS")
                        )
                    # If no_other_changes=False, ignore fields not in spec
                else:
                    should_check, expected_value = spec_map[field_name]
                    if should_check and not _values_equivalent(
                        expected_value, after_value
                    ):
                        # Value doesn't match
                        unmatched_fields.append(
                            (field_name, after_value, f"expected {repr(expected_value)}")
                        )

            return unmatched_fields if unmatched_fields else None


        # Collect all unexpected changes for detailed reporting
        unexpected_changes = []

        for tbl, report in diff.items():
            for row in report.get("modified_rows", []):
                row_changes = row["changes"]

                # Check for modify spec with resulting_fields
                modify_spec = _get_modify_spec(tbl, row["row_id"])
                if modify_spec is not None:
                    resulting_fields = modify_spec.get("resulting_fields")
                    if resulting_fields is not None:
                        # Validate that no_other_changes is provided
                        if "no_other_changes" not in modify_spec:
                            raise ValueError(
                                f"Modify spec for table '{tbl}' pk={row['row_id']} "
                                f"has 'resulting_fields' but missing required 'no_other_changes' field. "
                                f"Set 'no_other_changes': True to verify no other fields changed, "
                                f"or 'no_other_changes': False to only check the specified fields."
                            )
                        no_other_changes = modify_spec["no_other_changes"]
                        if not isinstance(no_other_changes, bool):
                            raise ValueError(
                                f"Modify spec for table '{tbl}' pk={row['row_id']} "
                                f"has 'no_other_changes' but it must be a boolean (True or False), "
                                f"got {type(no_other_changes).__name__}: {repr(no_other_changes)}"
                            )
                        
                        unmatched = _validate_modification_with_fields_spec(
                            tbl, row["row_id"], row_changes, resulting_fields, no_other_changes
                        )
                        if unmatched:
                            unexpected_changes.append(
                                {
                                    "type": "modification",
                                    "table": tbl,
                                    "row_id": row["row_id"],
                                    "field": None,
                                    "before": None,
                                    "after": None,
                                    "full_row": row,
                                    "unmatched_fields": unmatched,
                                }
                            )
                        continue  # Skip to next row
                    else:
                        # Modify spec without resulting_fields - just allow the modification
                        continue  # Skip to next row

                # Fall back to single-field specs (legacy)
                for f, vals in row_changes.items():
                    if self.ignore_config.should_ignore_field(tbl, f):
                        continue
                    if not _is_change_allowed(tbl, row["row_id"], f, vals["after"]):
                        unexpected_changes.append(
                            {
                                "type": "modification",
                                "table": tbl,
                                "row_id": row["row_id"],
                                "field": f,
                                "before": vals.get("before"),
                                "after": vals["after"],
                                "full_row": row,
                            }
                        )

            for row in report.get("added_rows", []):
                row_data = row.get("data", {})

                # Check for bulk fields spec (type: "insert")
                fields_spec = _get_fields_spec_for_type(tbl, row["row_id"], "insert")
                if fields_spec is not None:
                    unmatched = _validate_row_with_fields_spec(
                        tbl, row["row_id"], row_data, fields_spec
                    )
                    if unmatched:
                        unexpected_changes.append(
                            {
                                "type": "insertion",
                                "table": tbl,
                                "row_id": row["row_id"],
                                "field": None,
                                "after": "__added__",
                                "full_row": row,
                                "unmatched_fields": unmatched,
                            }
                        )
                    continue  # Skip to next row

                # Check if insertion is allowed without field validation
                if _is_type_allowed(tbl, row["row_id"], "insert"):
                    continue  # Insertion is allowed, skip to next row

                # Check for whole-row spec (legacy)
                whole_row_allowed = _is_change_allowed(
                    tbl, row["row_id"], None, "__added__"
                )

                if not whole_row_allowed:
                    unexpected_changes.append(
                        {
                            "type": "insertion",
                            "table": tbl,
                            "row_id": row["row_id"],
                            "field": None,
                            "after": "__added__",
                            "full_row": row,
                        }
                    )

            for row in report.get("removed_rows", []):
                row_data = row.get("data", {})

                # Check for bulk fields spec (type: "delete")
                fields_spec = _get_fields_spec_for_type(tbl, row["row_id"], "delete")
                if fields_spec is not None:
                    unmatched = _validate_row_with_fields_spec(
                        tbl, row["row_id"], row_data, fields_spec
                    )
                    if unmatched:
                        unexpected_changes.append(
                            {
                                "type": "deletion",
                                "table": tbl,
                                "row_id": row["row_id"],
                                "field": None,
                                "after": "__removed__",
                                "full_row": row,
                                "unmatched_fields": unmatched,
                            }
                        )
                    continue  # Skip to next row

                # Check if deletion is allowed without field validation
                if _is_type_allowed(tbl, row["row_id"], "delete"):
                    continue  # Deletion is allowed, skip to next row

                # Check for whole-row spec (legacy)
                whole_row_allowed = _is_change_allowed(
                    tbl, row["row_id"], None, "__removed__"
                )

                if not whole_row_allowed:
                    unexpected_changes.append(
                        {
                            "type": "deletion",
                            "table": tbl,
                            "row_id": row["row_id"],
                            "field": None,
                            "after": "__removed__",
                            "full_row": row,
                        }
                    )

        if unexpected_changes:
            # Build comprehensive error message
            error_lines = ["Unexpected database changes detected:"]
            error_lines.append("")

            for i, change in enumerate(
                unexpected_changes[:5], 1
            ):  # Show first 5 changes
                error_lines.append(
                    f"{i}. {change['type'].upper()} in table '{change['table']}':"
                )
                error_lines.append(f"   Row ID: {change['row_id']}")

                if change["type"] == "modification":
                    error_lines.append(f"   Field: {change['field']}")
                    error_lines.append(f"   Before: {repr(change['before'])}")
                    error_lines.append(f"   After: {repr(change['after'])}")
                elif change["type"] == "insertion":
                    error_lines.append("   New row added")
                elif change["type"] == "deletion":
                    error_lines.append("   Row deleted")

                # Show unmatched fields if present (from bulk fields spec validation)
                if "unmatched_fields" in change and change["unmatched_fields"]:
                    error_lines.append("   Unmatched fields:")
                    for field_info in change["unmatched_fields"][:5]:
                        field_name, actual_value, issue = field_info
                        error_lines.append(
                            f"     - {field_name}: {repr(actual_value)} ({issue})"
                        )
                    if len(change["unmatched_fields"]) > 10:
                        error_lines.append(
                            f"     ... and {len(change['unmatched_fields']) - 10} more"
                        )

                # Show some context from the row
                if "full_row" in change and change["full_row"]:
                    row_data = change["full_row"]
                    if change["type"] == "modification" and "data" in row_data:
                        # For modifications, show the current state
                        formatted_row = _format_row_for_error(
                            row_data.get("data", {}), max_fields=5
                        )
                        error_lines.append(f"   Row data: {formatted_row}")
                    elif (
                        change["type"] in ["insertion", "deletion"]
                        and "data" in row_data
                    ):
                        # For insertions/deletions, show the row data
                        formatted_row = _format_row_for_error(
                            row_data.get("data", {}), max_fields=5
                        )
                        error_lines.append(f"   Row data: {formatted_row}")

                error_lines.append("")

            if len(unexpected_changes) > 10:
                error_lines.append(
                    f"... and {len(unexpected_changes) - 10} more unexpected changes"
                )
                error_lines.append("")

            # Show what changes were allowed
            error_lines.append("Allowed changes were:")
            if allowed_changes:
                for i, allowed in enumerate(allowed_changes[:3], 1):
                    change_type = allowed.get("type", "unspecified")
                    
                    # For modify type, use resulting_fields
                    if change_type == "modify" and "resulting_fields" in allowed and allowed["resulting_fields"] is not None:
                        fields_summary = ", ".join(
                            f[0] if len(f) == 1 else f"{f[0]}={'NOT_CHECKED' if f[1] is ... else repr(f[1])}"
                            for f in allowed["resulting_fields"][:3]
                        )
                        if len(allowed["resulting_fields"]) > 3:
                            fields_summary += f", ... +{len(allowed['resulting_fields']) - 3} more"
                        no_other = allowed.get("no_other_changes", "NOT_SET")
                        error_lines.append(
                            f"  {i}. Table: {allowed.get('table')}, "
                            f"ID: {allowed.get('pk')}, "
                            f"Type: {change_type}, "
                            f"resulting_fields: [{fields_summary}], "
                            f"no_other_changes: {no_other}"
                        )
                    elif "fields" in allowed and allowed["fields"] is not None:
                        # Show bulk fields spec (for insert/delete)
                        fields_summary = ", ".join(
                            f[0] if len(f) == 1 else f"{f[0]}={'NOT_CHECKED' if f[1] is ... else repr(f[1])}"
                            for f in allowed["fields"][:3]
                        )
                        if len(allowed["fields"]) > 3:
                            fields_summary += f", ... +{len(allowed['fields']) - 3} more"
                        error_lines.append(
                            f"  {i}. Table: {allowed.get('table')}, "
                            f"ID: {allowed.get('pk')}, "
                            f"Type: {change_type}, "
                            f"Fields: [{fields_summary}]"
                        )
                    else:
                        error_lines.append(
                            f"  {i}. Table: {allowed.get('table')}, "
                            f"ID: {allowed.get('pk')}, "
                            f"Type: {change_type}"
                        )
                if len(allowed_changes) > 3:
                    error_lines.append(
                        f"  ... and {len(allowed_changes) - 3} more allowed changes"
                    )
            else:
                error_lines.append("  (No changes were allowed)")

            raise AssertionError("\n".join(error_lines))

        return self

    def expect_exactly(self, expected_changes: List[Dict[str, Any]]):
        """Verify that EXACTLY the specified changes occurred.

        This is stricter than expect_only_v2:
        1. All changes in diff must match a spec (no unexpected changes)
        2. All specs must have a matching change in diff (no missing expected changes)

        This method is ideal for verifying that an agent performed exactly what was expected -
        not more, not less.

        Args:
            expected_changes: List of expected change specs. Same format as expect_only_v2:
                - Insert: {"table": "t", "pk": 1, "type": "insert", "fields": [...]}
                - Modify: {"table": "t", "pk": 1, "type": "modify", "resulting_fields": [...], "no_other_changes": True/False}
                - Delete: {"table": "t", "pk": 1, "type": "delete"}

        Returns:
            self for method chaining

        Raises:
            AssertionError: If there are unexpected changes OR if expected changes are missing
        """
        diff = self._collect()

        # Use shared validation logic
        success, error_msg, _ = validate_diff_expect_exactly(
            diff, expected_changes, self.ignore_config
        )

        if not success:
            raise AssertionError(error_msg)

        return self

    def expect(
        self,
        *,
        allow: Optional[List[Dict[str, Any]]] = None,
        forbid: Optional[List[Dict[str, Any]]] = None,
    ):
        """More granular: allow / forbid per‑table and per‑field."""
        allow = allow or []
        forbid = forbid or []
        allow_tbl_field = {(c["table"], c.get("field")) for c in allow}
        forbid_tbl_field = {(c["table"], c.get("field")) for c in forbid}
        diff = self._collect()
        for tbl, report in diff.items():
            for row in report.get("modified_rows", []):
                for f in row["changes"].keys():
                    if self.ignore_config.should_ignore_field(tbl, f):
                        continue
                    key = (tbl, f)
                    if key in forbid_tbl_field:
                        raise AssertionError(f"Modification to forbidden field {key}")
                    if allow_tbl_field and key not in allow_tbl_field:
                        raise AssertionError(f"Modification to unallowed field {key}")
            if (tbl, None) in forbid_tbl_field and (
                report.get("added_rows") or report.get("removed_rows")
            ):
                raise AssertionError(f"Changes in forbidden table {tbl}")
        return self


################################################################################
#  DatabaseSnapshot with DSL entrypoints
################################################################################


class DatabaseSnapshot:
    """Represents a snapshot of an SQLite DB with DSL entrypoints."""

    def __init__(self, db_path: str, *, name: Optional[str] = None):
        self.db_path = db_path
        self.name = name or f"snapshot_{datetime.utcnow().isoformat()}"
        self.created_at = datetime.utcnow()

    # DSL entry ------------------------------------------------------------
    def table(self, table: str) -> QueryBuilder:
        return QueryBuilder(self, table)

    # Metadata -------------------------------------------------------------
    def tables(self) -> List[str]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tbls = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return tbls

    # Diff interface -------------------------------------------------------
    def diff(
        self,
        other: "DatabaseSnapshot",  # noqa: UP037
        ignore_config: Optional[IgnoreConfig] = None,
    ) -> SnapshotDiff:
        return SnapshotDiff(self, other, ignore_config)

    ############################################################################
    # Convenience, schema‑agnostic expectation helpers
    ############################################################################

    def expect_row(
        self, table: str, where: Dict[str, SQLValue], expect: Dict[str, SQLValue]
    ):
        qb = self.table(table)
        for k, v in where.items():
            qb = qb.eq(k, v)
        qb.assert_exists()
        for col, val in expect.items():
            qb.assert_eq(col, val)
        return self

    def expect_rows(
        self,
        table: str,
        where: Dict[str, SQLValue],
        *,
        count: Optional[int] = None,
        contains: Optional[List[Dict[str, SQLValue]]] = None,
    ):
        qb = self.table(table)
        for k, v in where.items():
            qb = qb.eq(k, v)
        if count is not None:
            qb.count().assert_eq(count)
        if contains:
            rows = qb.all()
            for cond in contains:
                matched = any(all(r.get(k) == v for k, v in cond.items()) for r in rows)
                if not matched:
                    raise AssertionError(f"Expected a row matching {cond} in {table}")
        return self

    def expect_absent_row(self, table: str, where: Dict[str, SQLValue]):
        qb = self.table(table)
        for k, v in where.items():
            qb = qb.eq(k, v)
        qb.assert_none()
        return self

    # ---------------------------------------------------------------------
    def __repr__(self):
        return f"<DatabaseSnapshot {self.name} at {self.db_path}>"
