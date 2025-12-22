import sqlite3
import subprocess
import re
import shutil
from typing import Any, Optional, List, Dict, Tuple


class SQLDiffNotFoundError(RuntimeError):
    """Raised when sqldiff CLI tool is not installed."""
    pass


def _check_sqldiff_available() -> None:
    """Check if sqldiff command is available, raise if not."""
    if shutil.which("sqldiff") is None:
        raise SQLDiffNotFoundError(
            "sqldiff CLI tool is not installed. "
            "Install it via: brew install sqlite (macOS) or apt install sqlite3 (Linux)"
        )


class SQLiteDiffer:
    """Efficient database differ using SQLite's sqldiff tool.
    
    Instead of loading all rows into memory, uses sqldiff to get only the
    differences between databases, then fetches row data only for changed rows.
    """
    
    def __init__(self, before_db: str, after_db: str):
        _check_sqldiff_available()
        self.before_db = before_db
        self.after_db = after_db

    def get_table_schema(self, db_path: str, table_name: str) -> List[str]:
        """Get column names for a table"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
        return columns

    def get_primary_key_columns(self, db_path: str, table_name: str) -> List[str]:
        """Get all primary key columns for a table, ordered by their position"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")

        pk_columns = []
        for row in cursor.fetchall():
            # row format: (cid, name, type, notnull, dflt_value, pk)
            if row[5] > 0:  # pk > 0 means it's part of primary key
                pk_columns.append((row[5], row[1]))  # (pk_position, column_name)

        conn.close()

        # Sort by primary key position and return just the column names
        pk_columns.sort(key=lambda x: x[0])
        return [col[1] for col in pk_columns]

    def get_all_tables(self, db_path: str) -> List[str]:
        """Get all table names from database"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        return tables

    def _run_sqldiff(self, table_name: Optional[str] = None) -> str:
        """Run sqldiff and return the output."""
        cmd = ["sqldiff", "--primarykey"]
        if table_name:
            cmd.extend(["--table", table_name])
        cmd.extend([self.before_db, self.after_db])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout

    def _parse_sql_value(self, value_str: str) -> Any:
        """Parse a SQL literal value to Python type.
        
        Handles:
        - NULL
        - String literals: 'hello'
        - Hex blobs: X'0a'
        - Integers and floats
        - SQL concatenation: 'part1'||X'0a'||'part2'
        """
        value_str = value_str.strip()
        
        if value_str.upper() == "NULL":
            return None
        
        # Check for SQL concatenation (contains ||)
        if "||" in value_str:
            return self._parse_sql_concat(value_str)
        
        # String literal (single quotes)
        if value_str.startswith("'") and value_str.endswith("'"):
            # Unescape single quotes
            return value_str[1:-1].replace("''", "'")
        
        # Hex blob
        if value_str.upper().startswith("X'") and value_str.endswith("'"):
            hex_str = value_str[2:-1]
            try:
                return bytes.fromhex(hex_str).decode('utf-8')
            except (ValueError, UnicodeDecodeError):
                return bytes.fromhex(hex_str)
        
        # Try integer
        try:
            return int(value_str)
        except ValueError:
            pass
        
        # Try float
        try:
            return float(value_str)
        except ValueError:
            pass
        
        return value_str

    def _parse_sql_concat(self, expr: str) -> str:
        """Parse SQL concatenation expression like 'a'||X'0a'||'b' into a string."""
        result = []
        parts = expr.split("||")
        
        for part in parts:
            part = part.strip()
            if part.upper().startswith("X'") and part.endswith("'"):
                # Hex literal
                hex_str = part[2:-1]
                try:
                    result.append(bytes.fromhex(hex_str).decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    result.append(bytes.fromhex(hex_str).decode('latin-1'))
            elif part.startswith("'") and part.endswith("'"):
                # String literal
                result.append(part[1:-1].replace("''", "'"))
            else:
                result.append(part)
        
        return "".join(result)

    def _split_sql_statements(self, sql_output: str) -> List[str]:
        """Split sqldiff output into individual SQL statements.
        
        Handles multiline statements (values with embedded newlines are output
        as concatenation expressions spanning multiple lines).
        """
        statements = []
        current = []
        in_string = False
        
        for char in sql_output:
            if char == "'" and not in_string:
                in_string = True
                current.append(char)
            elif char == "'" and in_string:
                current.append(char)
                # Check if next char is also a quote (escaped quote)
                # This is handled by the caller checking for ''
                in_string = False
            elif char == ";" and not in_string:
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt + ";")
                current = []
            else:
                current.append(char)
        
        # Handle any remaining content
        stmt = "".join(current).strip()
        if stmt:
            statements.append(stmt)
        
        return statements

    def _parse_values_list(self, values_str: str) -> List[Any]:
        """Parse a comma-separated list of SQL values, handling nested parens and quotes."""
        values = []
        current = []
        depth = 0
        in_string = False
        escape_next = False
        
        for char in values_str:
            if escape_next:
                current.append(char)
                escape_next = False
                continue
                
            if char == "'" and not escape_next:
                in_string = not in_string
                current.append(char)
            elif char == "(" and not in_string:
                depth += 1
                current.append(char)
            elif char == ")" and not in_string:
                depth -= 1
                current.append(char)
            elif char == "," and not in_string and depth == 0:
                values.append(self._parse_sql_value("".join(current)))
                current = []
            else:
                current.append(char)
        
        if current:
            values.append(self._parse_sql_value("".join(current)))
        
        return values

    def _parse_insert(self, sql: str, table_name: str) -> Optional[Dict[str, Any]]:
        """Parse INSERT statement and return row data."""
        # Pattern: INSERT INTO table(col1,col2,...) VALUES(val1,val2,...);
        pattern = rf"INSERT\s+INTO\s+{re.escape(table_name)}\s*\(([^)]+)\)\s*VALUES\s*\((.+)\)\s*;"
        match = re.match(pattern, sql, re.IGNORECASE | re.DOTALL)
        
        if not match:
            return None
        
        columns_str = match.group(1)
        values_str = match.group(2)
        
        columns = [c.strip().strip('"').strip("'") for c in columns_str.split(",")]
        values = self._parse_values_list(values_str)
        
        if len(columns) != len(values):
            return None
        
        return dict(zip(columns, values))

    def _parse_delete_where(self, sql: str, table_name: str) -> Optional[Dict[str, Any]]:
        """Parse DELETE statement and return WHERE conditions."""
        # Pattern: DELETE FROM table WHERE col1=val1 AND col2=val2;
        pattern = rf"DELETE\s+FROM\s+{re.escape(table_name)}\s+WHERE\s+(.+)\s*;"
        match = re.match(pattern, sql, re.IGNORECASE | re.DOTALL)
        
        if not match:
            return None
        
        where_clause = match.group(1)
        return self._parse_where_conditions(where_clause)

    def _parse_update(self, sql: str, table_name: str) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Parse UPDATE statement and return (set_values, where_conditions)."""
        # Pattern: UPDATE table SET col1=val1, col2=val2 WHERE col3=val3;
        pattern = rf"UPDATE\s+{re.escape(table_name)}\s+SET\s+(.+?)\s+WHERE\s+(.+)\s*;"
        match = re.match(pattern, sql, re.IGNORECASE | re.DOTALL)
        
        if not match:
            return None
        
        set_clause = match.group(1)
        where_clause = match.group(2)
        
        set_values = self._parse_set_clause(set_clause)
        where_conditions = self._parse_where_conditions(where_clause)
        
        return set_values, where_conditions

    def _parse_set_clause(self, set_clause: str) -> Dict[str, Any]:
        """Parse SET clause: col1=val1, col2=val2, ..."""
        result = {}
        # Split on comma, but be careful with quoted strings
        parts = self._split_sql_list(set_clause)
        
        for part in parts:
            if "=" in part:
                col, val = part.split("=", 1)
                col = col.strip().strip('"').strip("'")
                result[col] = self._parse_sql_value(val)
        
        return result

    def _parse_where_conditions(self, where_clause: str) -> Dict[str, Any]:
        """Parse WHERE clause: col1=val1 AND col2=val2 ..."""
        result = {}
        # Split on AND
        parts = re.split(r"\s+AND\s+", where_clause, flags=re.IGNORECASE)
        
        for part in parts:
            part = part.strip()
            if "=" in part:
                col, val = part.split("=", 1)
                col = col.strip().strip('"').strip("'")
                result[col] = self._parse_sql_value(val)
        
        return result

    def _split_sql_list(self, s: str) -> List[str]:
        """Split a comma-separated SQL list, respecting quotes."""
        parts = []
        current = []
        in_string = False
        
        for char in s:
            if char == "'" and not in_string:
                in_string = True
                current.append(char)
            elif char == "'" and in_string:
                current.append(char)
                # Check for escaped quote
                if len(current) >= 2 and current[-2] == "'":
                    continue
                in_string = False
            elif char == "," and not in_string:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        
        if current:
            parts.append("".join(current).strip())
        
        return parts

    def _get_row_by_conditions(self, db_path: str, table_name: str, conditions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fetch a single row from DB matching the given conditions."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        where_parts = []
        params = []
        for col, val in conditions.items():
            if val is None:
                where_parts.append(f'"{col}" IS NULL')
            else:
                where_parts.append(f'"{col}" = ?')
                params.append(val)
        
        where_clause = " AND ".join(where_parts)
        query = f"SELECT rowid, * FROM {table_name} WHERE {where_clause}"
        
        cursor.execute(query, params)
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None

    def _get_pk_value(self, row_data: Dict[str, Any], pk_columns: List[str]) -> Any:
        """Extract primary key value from row data."""
        if len(pk_columns) == 1:
            pk_col = pk_columns[0]
            if pk_col == "rowid":
                return row_data.get("rowid")
            return row_data.get(pk_col)
        else:
            return tuple(row_data.get(col) for col in pk_columns)

    def diff_table(
        self, table_name: str, primary_key_columns: Optional[List[str]] = None
    ) -> dict:
        """Create comprehensive diff of a table using sqldiff."""
        # Get primary key columns
        if primary_key_columns is None:
            primary_key_columns = self.get_primary_key_columns(self.before_db, table_name)
            if not primary_key_columns:
                columns = self.get_table_schema(self.before_db, table_name)
                if not columns:
                    columns = self.get_table_schema(self.after_db, table_name)
                if "id" in columns:
                    primary_key_columns = ["id"]
                else:
                    primary_key_columns = ["rowid"]

        result = {
            "table_name": table_name,
            "primary_key": primary_key_columns,
            "added_rows": [],
            "removed_rows": [],
            "modified_rows": [],
            "unchanged_count": 0,
            "total_changes": 0,
        }

        # Run sqldiff for this table
        sqldiff_output = self._run_sqldiff(table_name)
        
        if not sqldiff_output.strip():
            # No changes - count rows to report unchanged_count
            conn = sqlite3.connect(self.before_db)
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            conn.close()
            result["unchanged_count"] = count
            return result

        # Parse each SQL statement (split by semicolon, not newline, 
        # because values with embedded newlines span multiple lines)
        statements = self._split_sql_statements(sqldiff_output)
        
        for stmt in statements:
            stmt_upper = stmt.upper()
            
            if stmt_upper.startswith("INSERT"):
                row_data = self._parse_insert(stmt, table_name)
                if row_data:
                    pk_value = self._get_pk_value(row_data, primary_key_columns)
                    result["added_rows"].append({
                        "row_id": pk_value,
                        "data": row_data
                    })
            
            elif stmt_upper.startswith("DELETE"):
                where_conditions = self._parse_delete_where(stmt, table_name)
                if where_conditions:
                    # Fetch the actual row data from before database
                    row_data = self._get_row_by_conditions(self.before_db, table_name, where_conditions)
                    if row_data:
                        pk_value = self._get_pk_value(row_data, primary_key_columns)
                        result["removed_rows"].append({
                            "row_id": pk_value,
                            "data": row_data
                        })
            
            elif stmt_upper.startswith("UPDATE"):
                parsed = self._parse_update(stmt, table_name)
                if parsed:
                    set_values, where_conditions = parsed
                    
                    # Fetch before and after rows
                    before_row = self._get_row_by_conditions(self.before_db, table_name, where_conditions)
                    after_row = self._get_row_by_conditions(self.after_db, table_name, where_conditions)
                    
                    if before_row and after_row:
                        pk_value = self._get_pk_value(before_row, primary_key_columns)
                        
                        # Build changes dict from the SET clause
                        changes = {}
                        for field, after_val in set_values.items():
                            before_val = before_row.get(field)
                            changes[field] = {
                                "before": before_val,
                                "after": after_val
                            }
                        
                        result["modified_rows"].append({
                            "row_id": pk_value,
                            "changes": changes,
                            "before_row": before_row,
                            "after_row": after_row,
                        })

        result["total_changes"] = (
            len(result["added_rows"])
            + len(result["removed_rows"])
            + len(result["modified_rows"])
        )

        return result

    def diff_all_tables(self) -> dict:
        """Diff all tables in the database"""
        # Get tables from both databases
        before_tables = set(self.get_all_tables(self.before_db))
        after_tables = set(self.get_all_tables(self.after_db))
        all_tables = before_tables | after_tables
        
        results = {}

        for table in all_tables:
            try:
                results[table] = self.diff_table(table)
            except Exception as e:
                results[table] = {"error": str(e)}

        return results
