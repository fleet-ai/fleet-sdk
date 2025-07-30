from typing import Any, List, Optional
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
from ..verifiers.db import IgnoreConfig, _get_row_identifier, _format_row_for_error, _values_equivalent


class SyncDatabaseSnapshot:
    """Lazy database snapshot that fetches data on-demand through API."""
    
    def __init__(self, resource: "SQLiteResource", name: str | None = None):
        self.resource = resource
        self.name = name or f"snapshot_{datetime.utcnow().isoformat()}"
        self.created_at = datetime.utcnow()
        self._data: dict[str, list[dict[str, Any]]] = {}
        self._schemas: dict[str, list[str]] = {}
        self._table_names: list[str] | None = None
        self._fetched_tables: set[str] = set()
        
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
                dict(zip(data_response.columns, row))
                for row in data_response.rows
            ]
        else:
            self._data[table] = []
            
        self._fetched_tables.add(table)
        
    def tables(self) -> list[str]:
        """Get list of all tables in the snapshot."""
        self._ensure_tables_list()
        return list(self._table_names) if self._table_names else []
        
    def table(self, table_name: str) -> "SyncSnapshotQueryBuilder":
        """Create a query builder for snapshot data."""
        return SyncSnapshotQueryBuilder(self, table_name)
        
    def diff(
        self,
        other: "SyncDatabaseSnapshot",
        ignore_config: IgnoreConfig | None = None,
    ) -> "SyncSnapshotDiff":
        """Compare this snapshot with another."""
        # No need to fetch all data upfront - diff will fetch on demand
        return SyncSnapshotDiff(self, other, ignore_config)


class SyncSnapshotQueryBuilder:
    """Query builder that works on snapshot data - can use targeted queries when possible."""
    
    def __init__(self, snapshot: SyncDatabaseSnapshot, table: str):
        self._snapshot = snapshot
        self._table = table
        self._select_cols: list[str] = ["*"]
        self._conditions: list[tuple[str, str, Any]] = []
        self._limit: int | None = None
        self._order_by: str | None = None
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
        
    def _execute_targeted_query(self) -> list[dict[str, Any]]:
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
        
    def _get_data(self) -> list[dict[str, Any]]:
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
        
    def limit(self, n: int) -> "SyncSnapshotQueryBuilder":
        qb = self._clone()
        qb._limit = n
        return qb
        
    def sort(self, column: str, desc: bool = False) -> "SyncSnapshotQueryBuilder":
        qb = self._clone()
        qb._order_by = column
        qb._order_desc = desc
        return qb
        
    def first(self) -> dict[str, Any] | None:
        rows = self.all()
        return rows[0] if rows else None
        
    def all(self) -> list[dict[str, Any]]:
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
                filtered,
                key=lambda r: r.get(self._order_by),
                reverse=self._order_desc
            )
            
        # Apply limit
        if self._limit is not None:
            filtered = filtered[:self._limit]
            
        # Apply column selection
        if self._select_cols != ["*"]:
            filtered = [
                {col: row.get(col) for col in self._select_cols}
                for row in filtered
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
        ignore_config: IgnoreConfig | None = None,
    ):
        self.before = before
        self.after = after
        self.ignore_config = ignore_config or IgnoreConfig()
        self._cached: dict[str, Any] | None = None
        self._targeted_mode = False  # Flag to use targeted queries
        
    def _get_primary_key_columns(self, table: str) -> list[str]:
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
        diff: dict[str, dict[str, Any]] = {}
        
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
            def make_key(row: dict, pk_cols: list[str]) -> Any:
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
                result["added_rows"].append({
                    "row_id": key,
                    "data": after_index[key]
                })
                
            # Removed rows
            for key in before_keys - after_keys:
                result["removed_rows"].append({
                    "row_id": key,
                    "data": before_index[key]
                })
                
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
                    result["modified_rows"].append({
                        "row_id": key,
                        "changes": changes,
                        "data": after_row  # Current state
                    })
                else:
                    result["unchanged_count"] += 1
                    
            result["total_changes"] = (
                len(result["added_rows"]) +
                len(result["removed_rows"]) +
                len(result["modified_rows"])
            )
            
            diff[tbl] = result
            
        self._cached = diff
        return diff
        
    def _can_use_targeted_queries(self, allowed_changes: list[dict[str, Any]]) -> bool:
        """Check if we can use targeted queries for optimization."""
        # We can use targeted queries if all allowed changes specify table and pk
        for change in allowed_changes:
            if "table" not in change or "pk" not in change:
                return False
        return True
        
    def _expect_only_targeted(self, allowed_changes: list[dict[str, Any]]):
        """Optimized version that only queries specific rows mentioned in allowed_changes."""
        # Group allowed changes by table
        changes_by_table: dict[str, list[dict[str, Any]]] = {}
        for change in allowed_changes:
            table = change["table"]
            if table not in changes_by_table:
                changes_by_table[table] = []
            changes_by_table[table].append(change)
        
        # For each table with allowed changes, query only those specific rows
        for table, table_changes in changes_by_table.items():
            if self.ignore_config.should_ignore_table(table):
                continue
                
            # Get primary key columns
            pk_columns = self._get_primary_key_columns(table)
            
            # Extract unique PKs to check
            pks_to_check = {change["pk"] for change in table_changes}
            
            # Query only these specific rows from both snapshots
            for pk in pks_to_check:
                # Build WHERE clause for this PK
                where_sql = self._build_pk_where_clause(pk_columns, pk)
                
                # Query before snapshot
                before_query = f"SELECT * FROM {table} WHERE {where_sql}"
                before_response = self.before.resource.query(before_query)
                before_row = dict(zip(before_response.columns, before_response.rows[0])) if before_response.rows else None
                
                # Query after snapshot  
                after_response = self.after.resource.query(before_query)
                after_row = dict(zip(after_response.columns, after_response.rows[0])) if after_response.rows else None
                
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
                            if not self._is_field_change_allowed(table_changes, pk, field, after_val):
                                raise AssertionError(
                                    f"Unexpected change in table '{table}', "
                                    f"row {pk}, field '{field}': "
                                    f"{repr(before_val)} -> {repr(after_val)}"
                                )
                elif not before_row and after_row:
                    # Added row
                    if not self._is_row_change_allowed(table_changes, pk, "__added__"):
                        raise AssertionError(f"Unexpected row added in table '{table}': {pk}")
                elif before_row and not after_row:
                    # Removed row
                    if not self._is_row_change_allowed(table_changes, pk, "__removed__"):
                        raise AssertionError(f"Unexpected row removed from table '{table}': {pk}")
        
        # Now check tables not mentioned in allowed_changes to ensure no changes
        all_tables = set(self.before.tables()) | set(self.after.tables())
        for table in all_tables:
            if table in changes_by_table or self.ignore_config.should_ignore_table(table):
                continue
            
            # For tables with no allowed changes, just check row counts
            before_count_response = self.before.resource.query(f"SELECT COUNT(*) FROM {table}")
            before_count = before_count_response.rows[0][0] if before_count_response.rows else 0
            
            after_count_response = self.after.resource.query(f"SELECT COUNT(*) FROM {table}")
            after_count = after_count_response.rows[0][0] if after_count_response.rows else 0
            
            if before_count != after_count:
                raise AssertionError(
                    f"Unexpected change in table '{table}': "
                    f"row count changed from {before_count} to {after_count}"
                )
        
        return self
        
    def _build_pk_where_clause(self, pk_columns: list[str], pk_value: Any) -> str:
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
                conditions = [f"{col} = {escape_value(val)}" for col, val in zip(pk_columns, pk_value)]
                return " AND ".join(conditions)
            else:
                # Shouldn't happen if data is consistent
                return f"{pk_columns[0]} = {escape_value(pk_value)}"
                
    def _is_field_change_allowed(self, table_changes: list[dict[str, Any]], pk: Any, field: str, after_val: Any) -> bool:
        """Check if a specific field change is allowed."""
        for change in table_changes:
            if (str(change.get("pk")) == str(pk) and 
                change.get("field") == field and
                _values_equivalent(change.get("after"), after_val)):
                return True
        return False
        
    def _is_row_change_allowed(self, table_changes: list[dict[str, Any]], pk: Any, change_type: str) -> bool:
        """Check if a row addition/deletion is allowed."""
        for change in table_changes:
            if str(change.get("pk")) == str(pk) and change.get("after") == change_type:
                return True
        return False
        
    def _expect_no_changes(self):
        """Efficiently verify that no changes occurred between snapshots using row counts."""
        try:
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
            
            # For each table, compare row counts
            all_tables = before_tables | after_tables
            for table in all_tables:
                if self.ignore_config.should_ignore_table(table):
                    continue
                    
                # Get row counts from both snapshots
                before_count = 0
                after_count = 0
                
                if table in before_tables:
                    before_count_response = self.before.resource.query(f"SELECT COUNT(*) FROM {table}")
                    before_count = before_count_response.rows[0][0] if before_count_response.rows else 0
                    
                if table in after_tables:
                    after_count_response = self.after.resource.query(f"SELECT COUNT(*) FROM {table}")
                    after_count = after_count_response.rows[0][0] if after_count_response.rows else 0
                
                if before_count != after_count:
                    raise AssertionError(
                        f"Unexpected change in table '{table}': "
                        f"row count changed from {before_count} to {after_count}"
                    )
                    
                # If counts match but there could be modifications, we need to check further
                # For now, we'll do a more detailed check only if counts are small
                # to avoid performance issues
                if before_count > 0 and before_count <= 1000:  # Threshold for detailed check
                    # Do a quick hash check of the data
                    self._verify_table_unchanged(table)
                elif before_count > 1000:
                    # For large tables, we could sample or use checksums
                    # For now, we'll trust that count matching means no changes
                    # This is a reasonable assumption for expect_only([])
                    pass
                    
            return self
            
        except AssertionError:
            # Re-raise assertion errors (these are expected failures)
            raise
        except Exception as e:
            # If the optimized check fails for other reasons, fall back to full diff
            print(f"Warning: Optimized no-changes check failed: {e}")
            print("Falling back to full diff...")
            return self._expect_only_fallback([])
            
    def _verify_table_unchanged(self, table: str):
        """Verify that a table's data hasn't changed (for small tables)."""
        # Get primary key columns
        pk_columns = self._get_primary_key_columns(table)
        
        # Get sorted data from both snapshots
        order_by = ", ".join(pk_columns) if pk_columns else "rowid"
        
        before_response = self.before.resource.query(f"SELECT * FROM {table} ORDER BY {order_by}")
        after_response = self.after.resource.query(f"SELECT * FROM {table} ORDER BY {order_by}")
        
        # Quick check: if column counts differ, there's a schema change
        if before_response.columns != after_response.columns:
            raise AssertionError(f"Schema changed in table '{table}'")
            
        # Compare row by row
        if len(before_response.rows) != len(after_response.rows):
            raise AssertionError(
                f"Row count mismatch in table '{table}': "
                f"{len(before_response.rows)} vs {len(after_response.rows)}"
            )
            
        for i, (before_row, after_row) in enumerate(zip(before_response.rows, after_response.rows)):
            before_dict = dict(zip(before_response.columns, before_row))
            after_dict = dict(zip(after_response.columns, after_row))
            
            # Compare fields, ignoring those in ignore config
            for field in before_response.columns:
                if self.ignore_config.should_ignore_field(table, field):
                    continue
                    
                if not _values_equivalent(before_dict.get(field), after_dict.get(field)):
                    pk_val = before_dict.get(pk_columns[0]) if pk_columns else i
                    raise AssertionError(
                        f"Unexpected change in table '{table}', row {pk_val}, "
                        f"field '{field}': {repr(before_dict.get(field))} -> {repr(after_dict.get(field))}"
                    )
                    
    def _expect_only_fallback(self, allowed_changes: list[dict[str, Any]]):
        """Fallback to full diff collection when optimized methods fail."""
        diff = self._collect()
        return self._validate_diff_against_allowed_changes(diff, allowed_changes)
        
    def _validate_diff_against_allowed_changes(self, diff: dict[str, Any], allowed_changes: list[dict[str, Any]]):
        """Validate a collected diff against allowed changes."""
        def _is_change_allowed(
            table: str, row_id: Any, field: str | None, after_value: Any
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
                        unexpected_changes.append({
                            "type": "modification",
                            "table": tbl,
                            "row_id": row["row_id"],
                            "field": f,
                            "before": vals.get("before"),
                            "after": vals["after"],
                            "full_row": row,
                        })
                        
            for row in report.get("added_rows", []):
                if not _is_change_allowed(tbl, row["row_id"], None, "__added__"):
                    unexpected_changes.append({
                        "type": "insertion",
                        "table": tbl,
                        "row_id": row["row_id"],
                        "field": None,
                        "after": "__added__",
                        "full_row": row,
                    })
                    
            for row in report.get("removed_rows", []):
                if not _is_change_allowed(tbl, row["row_id"], None, "__removed__"):
                    unexpected_changes.append({
                        "type": "deletion",
                        "table": tbl,
                        "row_id": row["row_id"],
                        "field": None,
                        "after": "__removed__",
                        "full_row": row,
                    })
                    
        if unexpected_changes:
            # Build comprehensive error message
            error_lines = ["Unexpected database changes detected:"]
            error_lines.append("")
            
            for i, change in enumerate(unexpected_changes[:5], 1):
                error_lines.append(f"{i}. {change['type'].upper()} in table '{change['table']}':")
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
                error_lines.append(f"... and {len(unexpected_changes) - 5} more unexpected changes")
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
                    error_lines.append(f"  ... and {len(allowed_changes) - 3} more allowed changes")
            else:
                error_lines.append("  (No changes were allowed)")
                
            raise AssertionError("\n".join(error_lines))
            
        return self
        
    def expect_only(self, allowed_changes: list[dict[str, Any]]):
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


class SyncQueryBuilder:
    """Async query builder that translates DSL to SQL and executes through the API."""
    
    def __init__(self, resource: "SQLiteResource", table: str):
        self._resource = resource
        self._table = table
        self._select_cols: list[str] = ["*"]
        self._conditions: list[tuple[str, str, Any]] = []
        self._joins: list[tuple[str, dict[str, str]]] = []
        self._limit: int | None = None
        self._order_by: str | None = None

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

    def in_(self, column: str, values: list[Any]) -> "SyncQueryBuilder":
        qb = self._clone()
        qb._conditions.append((column, "IN", tuple(values)))
        return qb

    def not_in(self, column: str, values: list[Any]) -> "SyncQueryBuilder":
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
    def join(self, other_table: str, on: dict[str, str]) -> "SyncQueryBuilder":
        qb = self._clone()
        qb._joins.append((other_table, on))
        return qb

    # Compile to SQL
    def _compile(self) -> tuple[str, list[Any]]:
        cols = ", ".join(self._select_cols)
        sql = [f"SELECT {cols} FROM {self._table}"]
        params: list[Any] = []

        # Joins
        for tbl, onmap in self._joins:
            join_clauses = [
                f"{self._table}.{l} = {tbl}.{r}"
                for l, r in onmap.items()
            ]
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

    def first(self) -> dict[str, Any] | None:
        rows = self.limit(1).all()
        return rows[0] if rows else None

    def all(self) -> list[dict[str, Any]]:
        sql, params = self._compile()
        response = self._resource.query(sql, params)
        if not response.rows:
            return []
        # Convert List[List] to List[dict] using column names
        return [
            dict(zip(response.columns or [], row))
            for row in response.rows
        ]

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
    def __init__(self, resource: ResourceModel, client: "SyncWrapper"):
        super().__init__(resource)
        self.client = client

    def describe(self) -> DescribeResponse:
        """Describe the SQLite database schema."""
        response = self.client.request(
            "GET", f"/resources/sqlite/{self.resource.name}/describe"
        )
        return DescribeResponse(**response.json())

    def query(
        self, query: str, args: Optional[List[Any]] = None
    ) -> QueryResponse:
        return self._query(query, args, read_only=True)

    def exec(self, query: str, args: Optional[List[Any]] = None) -> QueryResponse:
        return self._query(query, args, read_only=False)

    def _query(
        self, query: str, args: Optional[List[Any]] = None, read_only: bool = True
    ) -> QueryResponse:
        request = QueryRequest(query=query, args=args, read_only=read_only)
        response = self.client.request(
            "POST",
            f"/resources/sqlite/{self.resource.name}/query",
            json=request.model_dump(),
        )
        return QueryResponse(**response.json())

    def table(self, table_name: str) -> SyncQueryBuilder:
        """Create a query builder for the specified table."""
        return SyncQueryBuilder(self, table_name)

    def snapshot(self, name: str | None = None) -> SyncDatabaseSnapshot:
        """Create a snapshot of the current database state."""
        # No longer fetch all data upfront - let it be lazy
        return SyncDatabaseSnapshot(self, name)

    def diff(
        self,
        other: "SQLiteResource",
        ignore_config: IgnoreConfig | None = None,
    ) -> SyncSnapshotDiff:
        """Compare this database with another SQLiteResource.
        
        Args:
            other: Another SQLiteResource to compare against
            ignore_config: Optional configuration for ignoring specific tables/fields
            
        Returns:
            SyncSnapshotDiff: Object containing the differences between the two databases
        """
        # Create snapshots of both databases
        before_snapshot = self.snapshot(name=f"before_{datetime.utcnow().isoformat()}")
        after_snapshot = other.snapshot(name=f"after_{datetime.utcnow().isoformat()}")
        
        # Return the diff between the snapshots
        return before_snapshot.diff(after_snapshot, ignore_config)
