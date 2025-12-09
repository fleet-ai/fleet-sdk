from typing import Any, List, Optional, Dict, Tuple
from ..instance.models import Resource as ResourceModel
from ..instance.models import DescribeResponse, QueryRequest, QueryResponse
from .base import Resource
from datetime import datetime
import tempfile
import sqlite3
import os

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..instance.base import SyncWrapper


# Import types from verifiers module
from fleet.verifiers.db import (
    IgnoreConfig,
    _get_row_identifier,
    _format_row_for_error,
    _values_equivalent,
)


class SyncDatabaseSnapshot:
    """Lazy database snapshot that fetches data on-demand through API."""

    def __init__(self, resource: "SQLiteResource", name: Optional[str] = None):
        self.resource = resource
        self.name = name or f"snapshot_{datetime.utcnow().isoformat()}"
        self.created_at = datetime.utcnow()
        self._data: Dict[str, List[Dict[str, Any]]] = {}
        self._schemas: Dict[str, List[str]] = {}
        self._table_names: Optional[List[str]] = None
        self._fetched_tables: set = set()

    def _ensure_tables_list(self):
        """Fetch just the list of table names if not already fetched."""
        if self._table_names is not None:
            return

        # Get all tables
        tables_response = self.resource.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )

        if not tables_response.rows:
            self._table_names = []
            return

        self._table_names = [row[0] for row in tables_response.rows]

    def _ensure_table_data(self, table: str):
        """Fetch data for a specific table on demand."""
        if table in self._fetched_tables:
            return

        # Get table schema
        schema_response = self.resource.query(f"PRAGMA table_info({table})")
        if schema_response.rows:
            self._schemas[table] = [row[1] for row in schema_response.rows]  # Column names

        # Get all data for this table
        data_response = self.resource.query(f"SELECT * FROM {table}")
        if data_response.rows and data_response.columns:
            self._data[table] = [
                dict(zip(data_response.columns, row)) for row in data_response.rows
            ]
        else:
            self._data[table] = []

        self._fetched_tables.add(table)

    def tables(self) -> List[str]:
        """Get list of all tables in the snapshot."""
        self._ensure_tables_list()
        return list(self._table_names) if self._table_names else []

    def table(self, table_name: str) -> "SyncSnapshotQueryBuilder":
        """Create a query builder for snapshot data."""
        return SyncSnapshotQueryBuilder(self, table_name)

    def diff(
        self,
        other: "SyncDatabaseSnapshot",
        ignore_config: Optional[IgnoreConfig] = None,
    ) -> "SyncSnapshotDiff":
        """Compare this snapshot with another."""
        # No need to fetch all data upfront - diff will fetch on demand
        return SyncSnapshotDiff(self, other, ignore_config)


class SyncSnapshotQueryBuilder:
    """Query builder that works on snapshot data - can use targeted queries when possible."""

    def __init__(self, snapshot: SyncDatabaseSnapshot, table: str):
        self._snapshot = snapshot
        self._table = table
        self._select_cols: List[str] = ["*"]
        self._conditions: List[Tuple[str, str, Any]] = []
        self._limit: Optional[int] = None
        self._order_by: Optional[str] = None
        self._order_desc: bool = False
        self._use_targeted_query = True  # Try to use targeted queries when possible

    def _can_use_targeted_query(self) -> bool:
        """Check if we can use a targeted query instead of loading all data."""
        # We can use targeted query if:
        # 1. We have simple equality conditions
        # 2. No complex operations like joins
        # 3. The query is selective (has conditions)
        if not self._conditions:
            return False
        for col, op, val in self._conditions:
            if op not in ["=", "IS", "IS NOT"]:
                return False
        return True

    def _execute_targeted_query(self) -> List[Dict[str, Any]]:
        """Execute a targeted query directly instead of loading all data."""
        # Build WHERE clause
        where_parts = []
        for col, op, val in self._conditions:
            if op == "=" and val is None:
                where_parts.append(f"{col} IS NULL")
            elif op == "IS":
                where_parts.append(f"{col} IS NULL")
            elif op == "IS NOT":
                where_parts.append(f"{col} IS NOT NULL")
            elif op == "=":
                if isinstance(val, str):
                    escaped_val = val.replace("'", "''")
                    where_parts.append(f"{col} = '{escaped_val}'")
                else:
                    where_parts.append(f"{col} = '{val}'")

        where_clause = " AND ".join(where_parts)

        # Build full query
        cols = ", ".join(self._select_cols)
        query = f"SELECT {cols} FROM {self._table} WHERE {where_clause}"

        if self._order_by:
            query += f" ORDER BY {self._order_by}"
        if self._limit is not None:
            query += f" LIMIT {self._limit}"

        # Execute query
        response = self._snapshot.resource.query(query)
        if response.rows and response.columns:
            return [dict(zip(response.columns, row)) for row in response.rows]
        return []

    def _get_data(self) -> List[Dict[str, Any]]:
        """Get table data - use targeted query if possible, otherwise load all data."""
        if self._use_targeted_query and self._can_use_targeted_query():
            return self._execute_targeted_query()

        # Fall back to loading all data
        self._snapshot._ensure_table_data(self._table)
        return self._snapshot._data.get(self._table, [])

    def eq(self, column: str, value: Any) -> "SyncSnapshotQueryBuilder":
        qb = self._clone()
        qb._conditions.append((column, "=", value))
        return qb

    def where(
        self,
        conditions: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "SyncSnapshotQueryBuilder":
        qb = self._clone()
        merged: Dict[str, Any] = {}
        if conditions:
            merged.update(conditions)
        if kwargs:
            merged.update(kwargs)
        for column, value in merged.items():
            qb._conditions.append((column, "=", value))
        return qb

    def limit(self, n: int) -> "SyncSnapshotQueryBuilder":
        qb = self._clone()
        qb._limit = n
        return qb

    def sort(self, column: str, desc: bool = False) -> "SyncSnapshotQueryBuilder":
        qb = self._clone()
        qb._order_by = column
        qb._order_desc = desc
        return qb

    def first(self) -> Optional[Dict[str, Any]]:
        rows = self.all()
        return rows[0] if rows else None

    def all(self) -> List[Dict[str, Any]]:
        # If we can use targeted query, _get_data already applies filters
        if self._use_targeted_query and self._can_use_targeted_query():
            return self._get_data()

        # Otherwise, get all data and apply filters manually
        data = self._get_data()

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

    def assert_exists(self):
        row = self.first()
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

    def _clone(self) -> "SyncSnapshotQueryBuilder":
        qb = SyncSnapshotQueryBuilder(self._snapshot, self._table)
        qb._select_cols = list(self._select_cols)
        qb._conditions = list(self._conditions)
        qb._limit = self._limit
        qb._order_by = self._order_by
        qb._order_desc = self._order_desc
        return qb


class SyncSnapshotDiff:
    """Compute & validate changes between two snapshots fetched via API."""

    def __init__(
        self,
        before: SyncDatabaseSnapshot,
        after: SyncDatabaseSnapshot,
        ignore_config: Optional[IgnoreConfig] = None,
    ):
        self.before = before
        self.after = after
        self.ignore_config = ignore_config or IgnoreConfig()
        self._cached: Optional[Dict[str, Any]] = None
        self._targeted_mode = False  # Flag to use targeted queries

    def _get_primary_key_columns(self, table: str) -> List[str]:
        """Get primary key columns for a table."""
        # Try to get from schema
        schema_response = self.after.resource.query(f"PRAGMA table_info({table})")
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

    def _collect(self):
        """Collect all differences between snapshots."""
        if self._cached is not None:
            return self._cached

        all_tables = set(self.before.tables()) | set(self.after.tables())
        diff: Dict[str, Dict[str, Any]] = {}

        for tbl in all_tables:
            if self.ignore_config.should_ignore_table(tbl):
                continue

            # Get primary key columns
            pk_columns = self._get_primary_key_columns(tbl)

            # Ensure data is fetched for this table
            self.before._ensure_table_data(tbl)
            self.after._ensure_table_data(tbl)

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
        """Expose the computed diff so callers can introspect like the legacy API."""
        return self._collect()

    def _can_use_targeted_queries(self, allowed_changes: List[Dict[str, Any]]) -> bool:
        """Check if we can use targeted queries for optimization."""
        # We can use targeted queries if all allowed changes specify table and pk
        for change in allowed_changes:
            if "table" not in change or "pk" not in change:
                return False
        return True

    def _build_pk_where_clause(self, pk_columns: List[str], pk_value: Any) -> str:
        """Build WHERE clause for primary key lookup."""
        # Escape single quotes in values to prevent SQL injection
        def escape_value(val: Any) -> str:
            if val is None:
                return "NULL"
            elif isinstance(val, str):
                escaped = str(val).replace("'", "''")
                return f"'{escaped}'"
            else:
                return f"'{val}'"

        if len(pk_columns) == 1:
            return f"{pk_columns[0]} = {escape_value(pk_value)}"
        else:
            # Composite key
            if isinstance(pk_value, tuple):
                conditions = [
                    f"{col} = {escape_value(val)}"
                    for col, val in zip(pk_columns, pk_value)
                ]
                return " AND ".join(conditions)
            else:
                # Shouldn't happen if data is consistent
                return f"{pk_columns[0]} = {escape_value(pk_value)}"

    def _expect_no_changes(self):
        """Efficiently verify that no changes occurred between snapshots using row counts."""
        try:
            import concurrent.futures
            from threading import Lock

            # Get all tables from both snapshots
            before_tables = set(self.before.tables())
            after_tables = set(self.after.tables())

            # Check for added/removed tables (excluding ignored ones)
            added_tables = after_tables - before_tables
            removed_tables = before_tables - after_tables

            for table in added_tables:
                if not self.ignore_config.should_ignore_table(table):
                    raise AssertionError(f"Unexpected table added: {table}")

            for table in removed_tables:
                if not self.ignore_config.should_ignore_table(table):
                    raise AssertionError(f"Unexpected table removed: {table}")

            # Prepare tables to check
            tables_to_check = []
            all_tables = before_tables | after_tables
            for table in all_tables:
                if not self.ignore_config.should_ignore_table(table):
                    tables_to_check.append(table)

            # If no tables to check, we're done
            if not tables_to_check:
                return self

            # Use ThreadPoolExecutor to parallelize count queries
            errors = []
            errors_lock = Lock()
            tables_needing_verification = []
            verification_lock = Lock()

            def check_table_counts(table: str):
                """Check row counts for a single table."""
                try:
                    # Get row counts from both snapshots
                    before_count = 0
                    after_count = 0

                    if table in before_tables:
                        before_count_response = self.before.resource.query(
                            f"SELECT COUNT(*) FROM {table}"
                        )
                        before_count = (
                            before_count_response.rows[0][0]
                            if before_count_response.rows
                            else 0
                        )

                    if table in after_tables:
                        after_count_response = self.after.resource.query(
                            f"SELECT COUNT(*) FROM {table}"
                        )
                        after_count = (
                            after_count_response.rows[0][0]
                            if after_count_response.rows
                            else 0
                        )

                    if before_count != after_count:
                        error_msg = (
                            f"Unexpected change in table '{table}': "
                            f"row count changed from {before_count} to {after_count}"
                        )
                        with errors_lock:
                            errors.append(AssertionError(error_msg))
                    elif before_count > 0 and before_count <= 1000:
                        # Mark for detailed verification
                        with verification_lock:
                            tables_needing_verification.append(table)

                except Exception as e:
                    with errors_lock:
                        errors.append(e)

            # Execute count checks in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(check_table_counts, table)
                    for table in tables_to_check
                ]
                concurrent.futures.wait(futures)

            # Check if any errors occurred during count checking
            if errors:
                raise errors[0]

            # Now verify small tables for data changes (also in parallel)
            if tables_needing_verification:
                verification_errors = []

                def verify_table(table: str):
                    """Verify a single table's data hasn't changed."""
                    try:
                        self._verify_table_unchanged(table)
                    except AssertionError as e:
                        with errors_lock:
                            verification_errors.append(e)

                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [
                        executor.submit(verify_table, table)
                        for table in tables_needing_verification
                    ]
                    concurrent.futures.wait(futures)

                # Check if any errors occurred during verification
                if verification_errors:
                    raise verification_errors[0]

            return self

        except AssertionError:
            # Re-raise assertion errors (these are expected failures)
            raise
        except Exception as e:
            # If the optimized check fails for other reasons, fall back to full diff
            print(f"Warning: Optimized no-changes check failed: {e}")
            print("Falling back to full diff...")
            return self._validate_diff_against_allowed_changes(self._collect(), [])

    def _verify_table_unchanged(self, table: str):
        """Verify that a table's data hasn't changed (for small tables)."""
        # Get primary key columns
        pk_columns = self._get_primary_key_columns(table)

        # Get sorted data from both snapshots
        order_by = ", ".join(pk_columns) if pk_columns else "rowid"

        before_response = self.before.resource.query(
            f"SELECT * FROM {table} ORDER BY {order_by}"
        )
        after_response = self.after.resource.query(
            f"SELECT * FROM {table} ORDER BY {order_by}"
        )

        # Quick check: if column counts differ, there's a schema change
        if before_response.columns != after_response.columns:
            raise AssertionError(f"Schema changed in table '{table}'")

        # Compare row by row
        if len(before_response.rows) != len(after_response.rows):
            raise AssertionError(
                f"Row count mismatch in table '{table}': "
                f"{len(before_response.rows)} vs {len(after_response.rows)}"
            )

        for i, (before_row, after_row) in enumerate(
            zip(before_response.rows, after_response.rows)
        ):
            before_dict = dict(zip(before_response.columns, before_row))
            after_dict = dict(zip(after_response.columns, after_row))

            # Compare fields, ignoring those in ignore config
            for field in before_response.columns:
                if self.ignore_config.should_ignore_field(table, field):
                    continue

                if not _values_equivalent(
                    before_dict.get(field), after_dict.get(field)
                ):
                    pk_val = before_dict.get(pk_columns[0]) if pk_columns else i
                    raise AssertionError(
                        f"Unexpected change in table '{table}', row {pk_val}, "
                        f"field '{field}': {repr(before_dict.get(field))} -> {repr(after_dict.get(field))}"
                    )

    def _is_field_change_allowed(
        self, table_changes: List[Dict[str, Any]], pk: Any, field: str, after_val: Any
    ) -> bool:
        """Check if a specific field change is allowed."""
        for change in table_changes:
            if (
                str(change.get("pk")) == str(pk)
                and change.get("field") == field
                and _values_equivalent(change.get("after"), after_val)
            ):
                return True
        return False

    def _is_row_change_allowed(
        self, table_changes: List[Dict[str, Any]], pk: Any, change_type: str
    ) -> bool:
        """Check if a row addition/deletion is allowed."""
        for change in table_changes:
            if str(change.get("pk")) == str(pk) and change.get("after") == change_type:
                return True
        return False

    def _expect_only_targeted(self, allowed_changes: List[Dict[str, Any]]):
        """Optimized version that only queries specific rows mentioned in allowed_changes."""
        import concurrent.futures
        from threading import Lock

        # Group allowed changes by table
        changes_by_table: Dict[str, List[Dict[str, Any]]] = {}
        for change in allowed_changes:
            table = change["table"]
            if table not in changes_by_table:
                changes_by_table[table] = []
            changes_by_table[table].append(change)

        errors = []
        errors_lock = Lock()

        # Function to check a single row
        def check_row(
            table: str,
            pk: Any,
            table_changes: List[Dict[str, Any]],
            pk_columns: List[str],
        ):
            try:
                # Build WHERE clause for this PK
                where_sql = self._build_pk_where_clause(pk_columns, pk)

                # Query before snapshot
                before_query = f"SELECT * FROM {table} WHERE {where_sql}"
                before_response = self.before.resource.query(before_query)
                before_row = (
                    dict(zip(before_response.columns, before_response.rows[0]))
                    if before_response.rows
                    else None
                )

                # Query after snapshot
                after_response = self.after.resource.query(before_query)
                after_row = (
                    dict(zip(after_response.columns, after_response.rows[0]))
                    if after_response.rows
                    else None
                )

                # Check changes for this row
                if before_row and after_row:
                    # Modified row - check fields
                    for field in set(before_row.keys()) | set(after_row.keys()):
                        if self.ignore_config.should_ignore_field(table, field):
                            continue
                        before_val = before_row.get(field)
                        after_val = after_row.get(field)
                        if not _values_equivalent(before_val, after_val):
                            # Check if this change is allowed
                            if not self._is_field_change_allowed(
                                table_changes, pk, field, after_val
                            ):
                                error_msg = (
                                    f"Unexpected change in table '{table}', "
                                    f"row {pk}, field '{field}': "
                                    f"{repr(before_val)} -> {repr(after_val)}"
                                )
                                with errors_lock:
                                    errors.append(AssertionError(error_msg))
                                return  # Stop checking this row
                elif not before_row and after_row:
                    # Added row
                    if not self._is_row_change_allowed(table_changes, pk, "__added__"):
                        error_msg = f"Unexpected row added in table '{table}': {pk}"
                        with errors_lock:
                            errors.append(AssertionError(error_msg))
                elif before_row and not after_row:
                    # Removed row
                    if not self._is_row_change_allowed(table_changes, pk, "__removed__"):
                        error_msg = f"Unexpected row removed from table '{table}': {pk}"
                        with errors_lock:
                            errors.append(AssertionError(error_msg))
            except Exception as e:
                with errors_lock:
                    errors.append(e)

        # Prepare all row checks
        row_checks = []
        for table, table_changes in changes_by_table.items():
            if self.ignore_config.should_ignore_table(table):
                continue

            # Get primary key columns once per table
            pk_columns = self._get_primary_key_columns(table)

            # Extract unique PKs to check
            pks_to_check = {change["pk"] for change in table_changes}

            for pk in pks_to_check:
                row_checks.append((table, pk, table_changes, pk_columns))

        # Execute row checks in parallel
        if row_checks:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(check_row, table, pk, table_changes, pk_columns)
                    for table, pk, table_changes, pk_columns in row_checks
                ]
                concurrent.futures.wait(futures)

        # Check for errors from row checks
        if errors:
            raise errors[0]

        # Now check tables not mentioned in allowed_changes to ensure no changes
        all_tables = set(self.before.tables()) | set(self.after.tables())
        tables_to_verify = []

        for table in all_tables:
            if (
                table not in changes_by_table
                and not self.ignore_config.should_ignore_table(table)
            ):
                tables_to_verify.append(table)

        # Function to verify no changes in a table
        def verify_no_changes(table: str):
            try:
                # For tables with no allowed changes, just check row counts
                before_count_response = self.before.resource.query(
                    f"SELECT COUNT(*) FROM {table}"
                )
                before_count = (
                    before_count_response.rows[0][0]
                    if before_count_response.rows
                    else 0
                )

                after_count_response = self.after.resource.query(
                    f"SELECT COUNT(*) FROM {table}"
                )
                after_count = (
                    after_count_response.rows[0][0] if after_count_response.rows else 0
                )

                if before_count != after_count:
                    error_msg = (
                        f"Unexpected change in table '{table}': "
                        f"row count changed from {before_count} to {after_count}"
                    )
                    with errors_lock:
                        errors.append(AssertionError(error_msg))
            except Exception as e:
                with errors_lock:
                    errors.append(e)

        # Execute table verification in parallel
        if tables_to_verify:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(verify_no_changes, table) for table in tables_to_verify
                ]
                concurrent.futures.wait(futures)

        # Final error check
        if errors:
            raise errors[0]

        return self

    def _validate_diff_against_allowed_changes(
        self, diff: Dict[str, Any], allowed_changes: List[Dict[str, Any]]
    ):
        """Validate a collected diff against allowed changes."""

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

    def _validate_diff_against_allowed_changes_v2(
        self, diff: Dict[str, Any], allowed_changes: List[Dict[str, Any]]
    ):
        """Validate a collected diff against allowed changes with field-level spec support.

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

        def _get_fields_spec_for_type(
            table: str, row_id: Any, change_type: str
        ) -> Optional[List[Tuple[str, Any]]]:
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

        def _get_modify_spec(table: str, row_id: Any) -> Optional[Dict[str, Any]]:
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

        def _is_type_allowed(table: str, row_id: Any, change_type: str) -> bool:
            """Check if a change type is allowed for the given table/row (with or without fields)."""
            for allowed in allowed_changes:
                allowed_pk = allowed.get("pk")
                pk_match = (
                    str(allowed_pk) == str(row_id) if allowed_pk is not None else False
                )
                if (
                    allowed["table"] == table
                    and pk_match
                    and allowed.get("type") == change_type
                ):
                    return True
            return False

        def _parse_fields_spec(
            fields_spec: List[Tuple[str, Any]]
        ) -> Dict[str, Tuple[bool, Any]]:
            """Parse a fields spec into a mapping of field_name -> (should_check_value, expected_value)."""
            spec_map: Dict[str, Tuple[bool, Any]] = {}
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
            row_id: Any,
            row_data: Dict[str, Any],
            fields_spec: List[Tuple[str, Any]],
        ) -> Optional[List[Tuple[str, Any, str]]]:
            """Validate a row against a bulk fields spec.

            Returns None if validation passes, or a list of (field, actual_value, issue)
            tuples for mismatches.

            Field spec semantics:
            - ("field_name", value): check that field equals value
            - ("field_name", None): check that field is SQL NULL
            - ("field_name", ...): don't check value (acknowledge field exists)
            """
            spec_map = _parse_fields_spec(fields_spec)
            unmatched_fields: List[Tuple[str, Any, str]] = []

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
            row_id: Any,
            row_changes: Dict[str, Dict[str, Any]],
            resulting_fields: List[Tuple[str, Any]],
            no_other_changes: bool,
        ) -> Optional[List[Tuple[str, Any, str]]]:
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
            unmatched_fields: List[Tuple[str, Any, str]] = []

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

            if len(unexpected_changes) > 5:
                error_lines.append(
                    f"... and {len(unexpected_changes) - 5} more unexpected changes"
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

    def expect_only(self, allowed_changes: List[Dict[str, Any]]):
        """Ensure only specified changes occurred."""
        # Special case: empty allowed_changes means no changes should have occurred
        if not allowed_changes:
            return self._expect_no_changes()

        # For expect_only, we can optimize by only checking the specific rows mentioned
        if self._can_use_targeted_queries(allowed_changes):
            return self._expect_only_targeted(allowed_changes)

        # Fall back to full diff for complex cases
        diff = self._collect()
        return self._validate_diff_against_allowed_changes(diff, allowed_changes)

    def expect_only_v2(self, allowed_changes: List[Dict[str, Any]]):
        """Ensure only specified changes occurred, with field-level spec support.

        This version supports field-level specifications for added/removed rows,
        allowing users to specify expected field values instead of just whole-row specs.
        """
        # Special case: empty allowed_changes means no changes should have occurred
        if not allowed_changes:
            return self._expect_no_changes()

        # Fall back to full diff for v2 (no targeted optimization yet)
        diff = self._collect()
        return self._validate_diff_against_allowed_changes_v2(diff, allowed_changes)

    def _ensure_all_fetched(self):
        """Fetch ALL data from ALL tables upfront (non-lazy loading).
        
        This is the old approach before lazy loading was introduced.
        Used by expect_only_v1 for simpler, non-optimized diffing.
        """
        # Get all tables
        tables_response = self.before.resource.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        
        if tables_response.rows:
            before_tables = [row[0] for row in tables_response.rows]
            for table in before_tables:
                self.before._ensure_table_data(table)
        
        # Also fetch from after snapshot
        tables_response = self.after.resource.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        
        if tables_response.rows:
            after_tables = [row[0] for row in tables_response.rows]
            for table in after_tables:
                self.after._ensure_table_data(table)

    def expect_only_v1(self, allowed_changes: List[Dict[str, Any]]):
        """Ensure only specified changes occurred using the original (non-optimized) approach.
        
        This version attempts to use the /api/v1/env/diff/structured endpoint if available,
        falling back to local diff computation if the endpoint is not available.
        
        Use this when you want the simpler, more predictable behavior of the original
        implementation without any query optimizations.
        """
        # Try to use the structured diff endpoint if we have an HTTP client
        resource = self.after.resource
        if resource.client is not None and resource._mode == "http":
            try:
                response = resource.client.request(
                    "POST",
                    "/api/v1/env/diff/structured",
                    json={},
                )
                result = response.json()
                if result.get("success") and "diff" in result:
                    diff = result["diff"]
                    return self._validate_diff_against_allowed_changes(diff, allowed_changes)
            except Exception as e:
                # Fall back to local diff if API call fails
                print(f"Warning: Failed to fetch structured diff from API: {e}")
                print("Falling back to local diff computation...")
        
        # Fall back to local diff computation
        self._ensure_all_fetched()
        diff = self._collect()
        return self._validate_diff_against_allowed_changes(diff, allowed_changes)


class SyncQueryBuilder:
    """Async query builder that translates DSL to SQL and executes through the API."""

    def __init__(self, resource: "SQLiteResource", table: str):
        self._resource = resource
        self._table = table
        self._select_cols: List[str] = ["*"]
        self._conditions: List[Tuple[str, str, Any]] = []
        self._joins: List[Tuple[str, Dict[str, str]]] = []
        self._limit: Optional[int] = None
        self._order_by: Optional[str] = None

    # Column projection / limiting / ordering
    def select(self, *columns: str) -> "SyncQueryBuilder":
        qb = self._clone()
        qb._select_cols = list(columns) if columns else ["*"]
        return qb

    def limit(self, n: int) -> "SyncQueryBuilder":
        qb = self._clone()
        qb._limit = n
        return qb

    def sort(self, column: str, desc: bool = False) -> "SyncQueryBuilder":
        qb = self._clone()
        qb._order_by = f"{column} {'DESC' if desc else 'ASC'}"
        return qb

    # WHERE helpers
    def _add_condition(self, column: str, op: str, value: Any) -> "SyncQueryBuilder":
        qb = self._clone()
        qb._conditions.append((column, op, value))
        return qb

    def eq(self, column: str, value: Any) -> "SyncQueryBuilder":
        return self._add_condition(column, "=", value)

    def where(
        self,
        conditions: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "SyncQueryBuilder":
        qb = self._clone()
        merged: Dict[str, Any] = {}
        if conditions:
            merged.update(conditions)
        if kwargs:
            merged.update(kwargs)
        for column, value in merged.items():
            qb._conditions.append((column, "=", value))
        return qb

    def neq(self, column: str, value: Any) -> "SyncQueryBuilder":
        return self._add_condition(column, "!=", value)

    def gt(self, column: str, value: Any) -> "SyncQueryBuilder":
        return self._add_condition(column, ">", value)

    def gte(self, column: str, value: Any) -> "SyncQueryBuilder":
        return self._add_condition(column, ">=", value)

    def lt(self, column: str, value: Any) -> "SyncQueryBuilder":
        return self._add_condition(column, "<", value)

    def lte(self, column: str, value: Any) -> "SyncQueryBuilder":
        return self._add_condition(column, "<=", value)

    def in_(self, column: str, values: List[Any]) -> "SyncQueryBuilder":
        qb = self._clone()
        qb._conditions.append((column, "IN", tuple(values)))
        return qb

    def not_in(self, column: str, values: List[Any]) -> "SyncQueryBuilder":
        qb = self._clone()
        qb._conditions.append((column, "NOT IN", tuple(values)))
        return qb

    def is_null(self, column: str) -> "SyncQueryBuilder":
        return self._add_condition(column, "IS", None)

    def not_null(self, column: str) -> "SyncQueryBuilder":
        return self._add_condition(column, "IS NOT", None)

    def ilike(self, column: str, pattern: str) -> "SyncQueryBuilder":
        qb = self._clone()
        qb._conditions.append((column, "LIKE", pattern))
        return qb

    # JOIN
    def join(self, other_table: str, on: Dict[str, str]) -> "SyncQueryBuilder":
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
    def count(self) -> int:
        qb = self.select("COUNT(*) AS __cnt__").limit(None)
        sql, params = qb._compile()
        response = self._resource.query(sql, params)
        if response.rows and len(response.rows) > 0:
            # Convert row list to dict
            row_dict = dict(zip(response.columns or [], response.rows[0]))
            return row_dict.get("__cnt__", 0)
        return 0

    def first(self) -> Optional[Dict[str, Any]]:
        rows = self.limit(1).all()
        return rows[0] if rows else None

    def all(self) -> List[Dict[str, Any]]:
        sql, params = self._compile()
        response = self._resource.query(sql, params)
        if not response.rows:
            return []
        # Convert List[List] to List[dict] using column names
        return [dict(zip(response.columns or [], row)) for row in response.rows]

    # Assertions
    def assert_exists(self):
        row = self.first()
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

    def assert_none(self):
        row = self.first()
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

    def assert_eq(self, column: str, value: Any):
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

    def _clone(self) -> "SyncQueryBuilder":
        qb = SyncQueryBuilder(self._resource, self._table)
        qb._select_cols = list(self._select_cols)
        qb._conditions = list(self._conditions)
        qb._joins = list(self._joins)
        qb._limit = self._limit
        qb._order_by = self._order_by
        return qb


class SQLiteResource(Resource):
    def __init__(
        self,
        resource: ResourceModel,
        client: Optional["SyncWrapper"] = None,
        db_path: Optional[str] = None,
    ):
        super().__init__(resource)
        self.client = client
        self.db_path = db_path
        self._mode = "direct" if db_path else "http"

    @property
    def mode(self) -> str:
        """Return the mode of this resource: 'direct' (local file) or 'http' (remote API)."""
        return self._mode

    def describe(self) -> DescribeResponse:
        """Describe the SQLite database schema."""
        if self._mode == "direct":
            return self._describe_direct()
        else:
            return self._describe_http()

    def _describe_http(self) -> DescribeResponse:
        """Describe database schema via HTTP API."""
        response = self.client.request(
            "GET", f"/resources/sqlite/{self.resource.name}/describe"
        )
        return DescribeResponse(**response.json())

    def _describe_direct(self) -> DescribeResponse:
        """Describe database schema from local file or in-memory database."""
        try:
            # Check if we need URI mode (for shared memory databases)
            use_uri = 'mode=memory' in self.db_path
            conn = sqlite3.connect(self.db_path, uri=use_uri)
            cursor = conn.cursor()

            # Get all tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            table_names = [row[0] for row in cursor.fetchall()]

            tables = []
            for table_name in table_names:
                # Get table info
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()

                # Get CREATE TABLE SQL
                cursor.execute(
                    f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,)
                )
                sql_row = cursor.fetchone()
                create_sql = sql_row[0] if sql_row else ""

                table_schema = {
                    "name": table_name,
                    "sql": create_sql,
                    "columns": [
                        {
                            "name": col[1],
                            "type": col[2],
                            "notnull": bool(col[3]),
                            "default_value": col[4],
                            "primary_key": col[5] > 0,
                        }
                        for col in columns
                    ],
                }
                tables.append(table_schema)

            conn.close()

            return DescribeResponse(
                success=True,
                resource_name=self.resource.name,
                tables=tables,
                message="Schema retrieved from local file",
            )
        except Exception as e:
            return DescribeResponse(
                success=False,
                resource_name=self.resource.name,
                tables=None,
                error=str(e),
                message=f"Failed to describe database: {str(e)}",
            )

    def query(self, query: str, args: Optional[List[Any]] = None) -> QueryResponse:
        return self._query(query, args, read_only=True)

    def exec(self, query: str, args: Optional[List[Any]] = None) -> QueryResponse:
        return self._query(query, args, read_only=False)

    def _query(
        self, query: str, args: Optional[List[Any]] = None, read_only: bool = True
    ) -> QueryResponse:
        if self._mode == "direct":
            return self._query_direct(query, args, read_only)
        else:
            return self._query_http(query, args, read_only)

    def _query_http(
        self, query: str, args: Optional[List[Any]] = None, read_only: bool = True
    ) -> QueryResponse:
        """Execute query via HTTP API."""
        request = QueryRequest(query=query, args=args, read_only=read_only)
        response = self.client.request(
            "POST",
            f"/resources/sqlite/{self.resource.name}/query",
            json=request.model_dump(),
        )
        return QueryResponse(**response.json())

    def _query_direct(
        self, query: str, args: Optional[List[Any]] = None, read_only: bool = True
    ) -> QueryResponse:
        """Execute query directly on local SQLite file or in-memory database."""
        try:
            # Check if we need URI mode (for shared memory databases)
            use_uri = 'mode=memory' in self.db_path
            conn = sqlite3.connect(self.db_path, uri=use_uri)
            cursor = conn.cursor()

            # Execute the query
            if args:
                cursor.execute(query, args)
            else:
                cursor.execute(query)

            # For write operations, commit the transaction
            if not read_only:
                conn.commit()

            # Get column names if available
            columns = [desc[0] for desc in cursor.description] if cursor.description else []

            # Fetch results for SELECT queries
            rows = []
            rows_affected = 0
            last_insert_id = None

            if cursor.description:  # SELECT query
                rows = cursor.fetchall()
            else:  # INSERT/UPDATE/DELETE
                rows_affected = cursor.rowcount
                last_insert_id = cursor.lastrowid if cursor.lastrowid else None

            conn.close()

            return QueryResponse(
                success=True,
                columns=columns if columns else None,
                rows=rows if rows else None,
                rows_affected=rows_affected if rows_affected > 0 else None,
                last_insert_id=last_insert_id,
                message="Query executed successfully",
            )
        except Exception as e:
            return QueryResponse(
                success=False,
                columns=None,
                rows=None,
                error=str(e),
                message=f"Query failed: {str(e)}",
            )

    def table(self, table_name: str) -> SyncQueryBuilder:
        """Create a query builder for the specified table."""
        return SyncQueryBuilder(self, table_name)

    def snapshot(self, name: Optional[str] = None) -> SyncDatabaseSnapshot:
        """Create a snapshot of the current database state."""
        snapshot = SyncDatabaseSnapshot(self, name)
        return snapshot

    def diff(
        self,
        other: "SQLiteResource",
        ignore_config: Optional[IgnoreConfig] = None,
    ) -> SyncSnapshotDiff:
        """Compare this database with another AsyncSQLiteResource.

        Args:
            other: Another AsyncSQLiteResource to compare against
            ignore_config: Optional configuration for ignoring specific tables/fields

        Returns:
            AsyncSnapshotDiff: Object containing the differences between the two databases
        """
        # Create snapshots of both databases
        before_snapshot = self.snapshot(name=f"before_{datetime.utcnow().isoformat()}")
        after_snapshot = other.snapshot(name=f"after_{datetime.utcnow().isoformat()}")

        # Return the diff between the snapshots
        return before_snapshot.diff(after_snapshot, ignore_config)
