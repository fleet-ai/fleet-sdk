from typing import Any, List, Optional, Dict, Tuple
from ...instance.models import Resource as ResourceModel
from ...instance.models import DescribeResponse, QueryRequest, QueryResponse
from .base import Resource
from datetime import datetime
import tempfile
import sqlite3
import os

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..instance.base import AsyncWrapper


# Import types from verifiers module
from fleet.verifiers.db import (
    IgnoreConfig,
    _get_row_identifier,
    _format_row_for_error,
    _values_equivalent,
)


class AsyncDatabaseSnapshot:
    """Async database snapshot that fetches data through API and stores locally for diffing."""

    def __init__(self, resource: "AsyncSQLiteResource", name: Optional[str] = None):
        self.resource = resource
        self.name = name or f"snapshot_{datetime.utcnow().isoformat()}"
        self.created_at = datetime.utcnow()
        self._data: Dict[str, List[Dict[str, Any]]] = {}
        self._schemas: Dict[str, List[str]] = {}
        self._fetched = False

    async def _ensure_fetched(self):
        """Fetch all data from remote database if not already fetched."""
        if self._fetched:
            return

        # Get all tables
        tables_response = await self.resource.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )

        if not tables_response.rows:
            self._fetched = True
            return

        table_names = [row[0] for row in tables_response.rows]

        # Fetch data from each table
        for table in table_names:
            # Get table schema
            schema_response = await self.resource.query(f"PRAGMA table_info({table})")
            if schema_response.rows:
                self._schemas[table] = [
                    row[1] for row in schema_response.rows
                ]  # Column names

            # Get all data
            data_response = await self.resource.query(f"SELECT * FROM {table}")
            if data_response.rows and data_response.columns:
                self._data[table] = [
                    dict(zip(data_response.columns, row)) for row in data_response.rows
                ]
            else:
                self._data[table] = []

        self._fetched = True

    async def tables(self) -> List[str]:
        """Get list of all tables in the snapshot."""
        await self._ensure_fetched()
        return list(self._data.keys())

    def table(self, table_name: str) -> "AsyncSnapshotQueryBuilder":
        """Create a query builder for snapshot data."""
        return AsyncSnapshotQueryBuilder(self, table_name)

    async def diff(
        self,
        other: "AsyncDatabaseSnapshot",
        ignore_config: Optional[IgnoreConfig] = None,
    ) -> "AsyncSnapshotDiff":
        """Compare this snapshot with another."""
        await self._ensure_fetched()
        await other._ensure_fetched()
        return AsyncSnapshotDiff(self, other, ignore_config)


class AsyncSnapshotQueryBuilder:
    """Query builder that works on local snapshot data."""

    def __init__(self, snapshot: AsyncDatabaseSnapshot, table: str):
        self._snapshot = snapshot
        self._table = table
        self._select_cols: List[str] = ["*"]
        self._conditions: List[Tuple[str, str, Any]] = []
        self._limit: Optional[int] = None
        self._order_by: Optional[str] = None
        self._order_desc: bool = False

    async def _get_data(self) -> List[Dict[str, Any]]:
        """Get table data from snapshot."""
        await self._snapshot._ensure_fetched()
        return self._snapshot._data.get(self._table, [])

    def eq(self, column: str, value: Any) -> "AsyncSnapshotQueryBuilder":
        qb = self._clone()
        qb._conditions.append((column, "=", value))
        return qb

    def where(
        self,
        conditions: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "AsyncSnapshotQueryBuilder":
        qb = self._clone()
        merged: Dict[str, Any] = {}
        if conditions:
            merged.update(conditions)
        if kwargs:
            merged.update(kwargs)
        for column, value in merged.items():
            qb._conditions.append((column, "=", value))
        return qb

    def limit(self, n: int) -> "AsyncSnapshotQueryBuilder":
        qb = self._clone()
        qb._limit = n
        return qb

    def sort(self, column: str, desc: bool = False) -> "AsyncSnapshotQueryBuilder":
        qb = self._clone()
        qb._order_by = column
        qb._order_desc = desc
        return qb

    async def first(self) -> Optional[Dict[str, Any]]:
        rows = await self.all()
        return rows[0] if rows else None

    async def all(self) -> List[Dict[str, Any]]:
        data = await self._get_data()

        # Apply filters
        filtered = data
        for col, op, val in self._conditions:
            if op == "=":
                filtered = [row for row in filtered if row.get(col) == val]

        # Apply sorting
        if self._order_by:
            filtered = sorted(
                filtered, key=lambda r: r.get(self._order_by), reverse=self._order_desc
            )

        # Apply limit
        if self._limit is not None:
            filtered = filtered[: self._limit]

        # Apply column selection
        if self._select_cols != ["*"]:
            filtered = [
                {col: row.get(col) for col in self._select_cols} for row in filtered
            ]

        return filtered

    async def assert_exists(self):
        row = await self.first()
        if row is None:
            error_msg = (
                f"Expected at least one matching row, but found none.\n"
                f"Table: {self._table}"
            )
            if self._conditions:
                conditions_str = ", ".join(
                    [f"{col} {op} {val}" for col, op, val in self._conditions]
                )
                error_msg += f"\nConditions: {conditions_str}"
            raise AssertionError(error_msg)
        return self

    def _clone(self) -> "AsyncSnapshotQueryBuilder":
        qb = AsyncSnapshotQueryBuilder(self._snapshot, self._table)
        qb._select_cols = list(self._select_cols)
        qb._conditions = list(self._conditions)
        qb._limit = self._limit
        qb._order_by = self._order_by
        qb._order_desc = self._order_desc
        return qb


class AsyncSnapshotDiff:
    """Compute & validate changes between two snapshots fetched via API."""

    def __init__(
        self,
        before: AsyncDatabaseSnapshot,
        after: AsyncDatabaseSnapshot,
        ignore_config: Optional[IgnoreConfig] = None,
    ):
        self.before = before
        self.after = after
        self.ignore_config = ignore_config or IgnoreConfig()
        self._cached: Optional[Dict[str, Any]] = None

    async def _get_primary_key_columns(self, table: str) -> List[str]:
        """Get primary key columns for a table."""
        # Try to get from schema
        schema_response = await self.after.resource.query(f"PRAGMA table_info({table})")
        if not schema_response.rows:
            return ["id"]  # Default fallback

        pk_columns = []
        for row in schema_response.rows:
            # row format: (cid, name, type, notnull, dflt_value, pk)
            if row[5] > 0:  # pk > 0 means it's part of primary key
                pk_columns.append((row[5], row[1]))  # (pk_position, column_name)

        if not pk_columns:
            # Try common defaults
            all_columns = [row[1] for row in schema_response.rows]
            if "id" in all_columns:
                return ["id"]
            return ["rowid"]

        # Sort by primary key position and return just the column names
        pk_columns.sort(key=lambda x: x[0])
        return [col[1] for col in pk_columns]

    async def _collect(self):
        """Collect all differences between snapshots."""
        if self._cached is not None:
            return self._cached

        all_tables = set(await self.before.tables()) | set(await self.after.tables())
        diff: Dict[str, Dict[str, Any]] = {}

        for tbl in all_tables:
            if self.ignore_config.should_ignore_table(tbl):
                continue

            # Get primary key columns
            pk_columns = await self._get_primary_key_columns(tbl)

            # Get data from both snapshots
            before_data = self.before._data.get(tbl, [])
            after_data = self.after._data.get(tbl, [])

            # Create indexes by primary key
            def make_key(row: dict, pk_cols: List[str]) -> Any:
                if len(pk_cols) == 1:
                    return row.get(pk_cols[0])
                return tuple(row.get(col) for col in pk_cols)

            before_index = {make_key(row, pk_columns): row for row in before_data}
            after_index = {make_key(row, pk_columns): row for row in after_data}

            before_keys = set(before_index.keys())
            after_keys = set(after_index.keys())

            # Find changes
            result = {
                "table_name": tbl,
                "primary_key": pk_columns,
                "added_rows": [],
                "removed_rows": [],
                "modified_rows": [],
                "unchanged_count": 0,
                "total_changes": 0,
            }

            # Added rows
            for key in after_keys - before_keys:
                result["added_rows"].append({"row_id": key, "data": after_index[key]})

            # Removed rows
            for key in before_keys - after_keys:
                result["removed_rows"].append(
                    {"row_id": key, "data": before_index[key]}
                )

            # Modified rows
            for key in before_keys & after_keys:
                before_row = before_index[key]
                after_row = after_index[key]
                changes = {}

                for field in set(before_row.keys()) | set(after_row.keys()):
                    if self.ignore_config.should_ignore_field(tbl, field):
                        continue
                    before_val = before_row.get(field)
                    after_val = after_row.get(field)
                    if not _values_equivalent(before_val, after_val):
                        changes[field] = {"before": before_val, "after": after_val}

                if changes:
                    result["modified_rows"].append(
                        {
                            "row_id": key,
                            "changes": changes,
                            "data": after_row,  # Current state
                        }
                    )
                else:
                    result["unchanged_count"] += 1

            result["total_changes"] = (
                len(result["added_rows"])
                + len(result["removed_rows"])
                + len(result["modified_rows"])
            )

            diff[tbl] = result

        self._cached = diff
        return diff

    @property
    def changes(self) -> Dict[str, Dict[str, Any]]:
        """Expose cached changes; ensure callers awaited a diff-producing method first."""
        if self._cached is None:
            raise RuntimeError(
                "Diff not collected yet; await an operation like expect_only() first."
            )
        return self._cached

    async def expect_only(self, allowed_changes: List[Dict[str, Any]]):
        """Ensure only specified changes occurred."""
        diff = await self._collect()

        def _is_change_allowed(
            table: str, row_id: Any, field: Optional[str], after_value: Any
        ) -> bool:
            """Check if a change is in the allowed list using semantic comparison."""
            for allowed in allowed_changes:
                allowed_pk = allowed.get("pk")
                # Handle type conversion for primary key comparison
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

        # Collect all unexpected changes
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

            for i, change in enumerate(unexpected_changes[:5], 1):
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
                    if "data" in row_data:
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


class AsyncQueryBuilder:
    """Async query builder that translates DSL to SQL and executes through the API."""

    def __init__(self, resource: "AsyncSQLiteResource", table: str):
        self._resource = resource
        self._table = table
        self._select_cols: List[str] = ["*"]
        self._conditions: List[Tuple[str, str, Any]] = []
        self._joins: List[Tuple[str, Dict[str, str]]] = []
        self._limit: Optional[int] = None
        self._order_by: Optional[str] = None

    # Column projection / limiting / ordering
    def select(self, *columns: str) -> "AsyncQueryBuilder":
        qb = self._clone()
        qb._select_cols = list(columns) if columns else ["*"]
        return qb

    def limit(self, n: int) -> "AsyncQueryBuilder":
        qb = self._clone()
        qb._limit = n
        return qb

    def sort(self, column: str, desc: bool = False) -> "AsyncQueryBuilder":
        qb = self._clone()
        qb._order_by = f"{column} {'DESC' if desc else 'ASC'}"
        return qb

    # WHERE helpers
    def _add_condition(self, column: str, op: str, value: Any) -> "AsyncQueryBuilder":
        qb = self._clone()
        qb._conditions.append((column, op, value))
        return qb

    def eq(self, column: str, value: Any) -> "AsyncQueryBuilder":
        return self._add_condition(column, "=", value)

    def where(
        self,
        conditions: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "AsyncQueryBuilder":
        qb = self._clone()
        merged: Dict[str, Any] = {}
        if conditions:
            merged.update(conditions)
        if kwargs:
            merged.update(kwargs)
        for column, value in merged.items():
            qb._conditions.append((column, "=", value))
        return qb

    def neq(self, column: str, value: Any) -> "AsyncQueryBuilder":
        return self._add_condition(column, "!=", value)

    def gt(self, column: str, value: Any) -> "AsyncQueryBuilder":
        return self._add_condition(column, ">", value)

    def gte(self, column: str, value: Any) -> "AsyncQueryBuilder":
        return self._add_condition(column, ">=", value)

    def lt(self, column: str, value: Any) -> "AsyncQueryBuilder":
        return self._add_condition(column, "<", value)

    def lte(self, column: str, value: Any) -> "AsyncQueryBuilder":
        return self._add_condition(column, "<=", value)

    def in_(self, column: str, values: List[Any]) -> "AsyncQueryBuilder":
        qb = self._clone()
        qb._conditions.append((column, "IN", tuple(values)))
        return qb

    def not_in(self, column: str, values: List[Any]) -> "AsyncQueryBuilder":
        qb = self._clone()
        qb._conditions.append((column, "NOT IN", tuple(values)))
        return qb

    def is_null(self, column: str) -> "AsyncQueryBuilder":
        return self._add_condition(column, "IS", None)

    def not_null(self, column: str) -> "AsyncQueryBuilder":
        return self._add_condition(column, "IS NOT", None)

    def ilike(self, column: str, pattern: str) -> "AsyncQueryBuilder":
        qb = self._clone()
        qb._conditions.append((column, "LIKE", pattern))
        return qb

    # JOIN
    def join(self, other_table: str, on: Dict[str, str]) -> "AsyncQueryBuilder":
        qb = self._clone()
        qb._joins.append((other_table, on))
        return qb

    # Compile to SQL
    def _compile(self) -> Tuple[str, List[Any]]:
        cols = ", ".join(self._select_cols)
        sql = [f"SELECT {cols} FROM {self._table}"]
        params: List[Any] = []

        # Joins
        for tbl, onmap in self._joins:
            join_clauses = [f"{self._table}.{l} = {tbl}.{r}" for l, r in onmap.items()]
            sql.append(f"JOIN {tbl} ON {' AND '.join(join_clauses)}")

        # WHERE
        if self._conditions:
            placeholders = []
            for col, op, val in self._conditions:
                if op in ("IN", "NOT IN") and isinstance(val, tuple):
                    ph = ", ".join(["?" for _ in val])
                    placeholders.append(f"{col} {op} ({ph})")
                    params.extend(val)
                elif op in ("IS", "IS NOT"):
                    placeholders.append(f"{col} {op} NULL")
                else:
                    placeholders.append(f"{col} {op} ?")
                    params.append(val)
            sql.append("WHERE " + " AND ".join(placeholders))

        # ORDER / LIMIT
        if self._order_by:
            sql.append(f"ORDER BY {self._order_by}")
        if self._limit is not None:
            sql.append(f"LIMIT {self._limit}")

        return " ".join(sql), params

    # Execution methods
    async def count(self) -> int:
        qb = self.select("COUNT(*) AS __cnt__").limit(None)
        sql, params = qb._compile()
        response = await self._resource.query(sql, params)
        if response.rows and len(response.rows) > 0:
            # Convert row list to dict
            row_dict = dict(zip(response.columns or [], response.rows[0]))
            return row_dict.get("__cnt__", 0)
        return 0

    async def first(self) -> Optional[Dict[str, Any]]:
        rows = await self.limit(1).all()
        return rows[0] if rows else None

    async def all(self) -> List[Dict[str, Any]]:
        sql, params = self._compile()
        response = await self._resource.query(sql, params)
        if not response.rows:
            return []
        # Convert List[List] to List[dict] using column names
        return [dict(zip(response.columns or [], row)) for row in response.rows]

    # Assertions
    async def assert_exists(self):
        row = await self.first()
        if row is None:
            sql, params = self._compile()
            error_msg = (
                f"Expected at least one matching row, but found none.\n"
                f"Query: {sql}\n"
                f"Parameters: {params}\n"
                f"Table: {self._table}"
            )
            if self._conditions:
                conditions_str = ", ".join(
                    [f"{col} {op} {val}" for col, op, val in self._conditions]
                )
                error_msg += f"\nConditions: {conditions_str}"
            raise AssertionError(error_msg)
        return self

    async def assert_none(self):
        row = await self.first()
        if row is not None:
            sql, params = self._compile()
            error_msg = (
                f"Expected no matching rows, but found at least one.\n"
                f"Found row: {row}\n"
                f"Query: {sql}\n"
                f"Parameters: {params}\n"
                f"Table: {self._table}"
            )
            raise AssertionError(error_msg)
        return self

    async def assert_eq(self, column: str, value: Any):
        row = await self.first()
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
            error_msg = (
                f"Field value assertion failed.\n"
                f"Field: {column}\n"
                f"Expected: {repr(value)}\n"
                f"Actual: {repr(actual_value)}\n"
                f"Full row data: {row}\n"
                f"Table: {self._table}"
            )
            raise AssertionError(error_msg)
        return self

    def _clone(self) -> "AsyncQueryBuilder":
        qb = AsyncQueryBuilder(self._resource, self._table)
        qb._select_cols = list(self._select_cols)
        qb._conditions = list(self._conditions)
        qb._joins = list(self._joins)
        qb._limit = self._limit
        qb._order_by = self._order_by
        return qb


class AsyncSQLiteResource(Resource):
    def __init__(self, resource: ResourceModel, client: "AsyncWrapper"):
        super().__init__(resource)
        self.client = client

    async def describe(self) -> DescribeResponse:
        """Describe the SQLite database schema."""
        response = await self.client.request(
            "GET", f"/resources/sqlite/{self.resource.name}/describe"
        )
        return DescribeResponse(**response.json())

    async def query(
        self, query: str, args: Optional[List[Any]] = None
    ) -> QueryResponse:
        return await self._query(query, args, read_only=True)

    async def exec(self, query: str, args: Optional[List[Any]] = None) -> QueryResponse:
        return await self._query(query, args, read_only=False)

    async def _query(
        self, query: str, args: Optional[List[Any]] = None, read_only: bool = True
    ) -> QueryResponse:
        request = QueryRequest(query=query, args=args, read_only=read_only)
        response = await self.client.request(
            "POST",
            f"/resources/sqlite/{self.resource.name}/query",
            json=request.model_dump(),
        )
        return QueryResponse(**response.json())

    def table(self, table_name: str) -> AsyncQueryBuilder:
        """Create a query builder for the specified table."""
        return AsyncQueryBuilder(self, table_name)

    async def snapshot(self, name: Optional[str] = None) -> AsyncDatabaseSnapshot:
        """Create a snapshot of the current database state."""
        snapshot = AsyncDatabaseSnapshot(self, name)
        await snapshot._ensure_fetched()
        return snapshot

    async def diff(
        self,
        other: "AsyncSQLiteResource",
        ignore_config: Optional[IgnoreConfig] = None,
    ) -> AsyncSnapshotDiff:
        """Compare this database with another AsyncSQLiteResource.

        Args:
            other: Another AsyncSQLiteResource to compare against
            ignore_config: Optional configuration for ignoring specific tables/fields

        Returns:
            AsyncSnapshotDiff: Object containing the differences between the two databases
        """
        # Create snapshots of both databases
        before_snapshot = await self.snapshot(
            name=f"before_{datetime.utcnow().isoformat()}"
        )
        after_snapshot = await other.snapshot(
            name=f"after_{datetime.utcnow().isoformat()}"
        )

        # Return the diff between the snapshots
        return await before_snapshot.diff(after_snapshot, ignore_config)
