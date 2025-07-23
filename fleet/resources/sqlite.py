from typing import Any, List, Optional
from ..instance.models import Resource as ResourceModel
from ..instance.models import DescribeResponse, QueryRequest, QueryResponse
from .base import Resource
from datetime import datetime

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..instance.base import SyncWrapper

# Import types from verifiers module
from ..verifiers.db import IgnoreConfig, _get_row_identifier, _format_row_for_error, _values_equivalent


class SyncQueryBuilder:
    """Sync query builder that translates DSL to SQL and executes through the API."""
    
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
