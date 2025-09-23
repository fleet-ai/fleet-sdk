import sqlite3
from typing import Any, Optional, List, Dict, Tuple


class SQLiteDiffer:
    def __init__(self, before_db: str, after_db: str):
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

    def get_table_data(
        self,
        db_path: str,
        table_name: str,
        primary_key_columns: Optional[List[str]] = None,
    ) -> Tuple[Dict[Any, dict], List[str]]:
        """Get table data indexed by primary key (single column or composite)"""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # If no primary key specified, try to detect it
        if primary_key_columns is None:
            primary_key_columns = self.get_primary_key_columns(db_path, table_name)

            # Fallback strategies if no primary key found
            if not primary_key_columns:
                columns = self.get_table_schema(db_path, table_name)
                if "id" in columns:
                    primary_key_columns = ["id"]
                else:
                    primary_key_columns = ["rowid"]

        cursor.execute(f"SELECT rowid, * FROM {table_name}")
        rows = cursor.fetchall()

        data = {}
        for row in rows:
            row_dict = dict(row)

            # Create primary key value (single value or tuple for composite keys)
            if len(primary_key_columns) == 1:
                pk_col = primary_key_columns[0]
                if pk_col == "rowid":
                    pk_value = row_dict["rowid"]
                else:
                    pk_value = row_dict.get(pk_col)
            else:
                # Composite primary key - use tuple of values
                pk_values = []
                for pk_col in primary_key_columns:
                    pk_values.append(row_dict.get(pk_col))
                pk_value = tuple(pk_values)

            if pk_value is not None and (
                not isinstance(pk_value, tuple) or all(v is not None for v in pk_value)
            ):
                data[pk_value] = row_dict

        conn.close()
        return data, primary_key_columns

    def compare_rows(self, before_row: dict, after_row: dict) -> Dict[str, dict]:
        """Compare two rows field by field"""
        changes = {}

        all_fields = set(before_row.keys()) | set(after_row.keys())

        for field in all_fields:
            before_val = before_row.get(field)
            after_val = after_row.get(field)

            if before_val != after_val:
                changes[field] = {"before": before_val, "after": after_val}

        return changes

    def diff_table(
        self, table_name: str, primary_key_columns: Optional[List[str]] = None
    ) -> dict:
        """Create comprehensive diff of a table"""
        before_data, detected_pk = self.get_table_data(
            self.before_db, table_name, primary_key_columns
        )
        after_data, _ = self.get_table_data(
            self.after_db, table_name, primary_key_columns or detected_pk
        )

        before_keys = set(before_data.keys())
        after_keys = set(after_data.keys())

        # Find different types of changes
        added_keys = after_keys - before_keys
        removed_keys = before_keys - after_keys
        common_keys = before_keys & after_keys

        result = {
            "table_name": table_name,
            "primary_key": primary_key_columns or detected_pk,
            "added_rows": [],
            "removed_rows": [],
            "modified_rows": [],
            "unchanged_count": 0,
            "total_changes": 0,
        }

        # Added rows
        for key in added_keys:
            result["added_rows"].append({"row_id": key, "data": after_data[key]})

        # Removed rows
        for key in removed_keys:
            result["removed_rows"].append({"row_id": key, "data": before_data[key]})

        # Check for modifications in existing rows
        for key in common_keys:
            field_changes = self.compare_rows(before_data[key], after_data[key])

            if field_changes:
                result["modified_rows"].append(
                    {
                        "row_id": key,
                        "changes": field_changes,
                        "before_row": before_data[key],
                        "after_row": after_data[key],
                    }
                )
            else:
                result["unchanged_count"] += 1

        result["total_changes"] = (
            len(result["added_rows"])
            + len(result["removed_rows"])
            + len(result["modified_rows"])
        )

        return result

    def diff_all_tables(self) -> dict:
        """Diff all tables in the database"""
        tables = self.get_all_tables(self.before_db)
        results = {}

        for table in tables:
            try:
                results[table] = self.diff_table(table)
            except Exception as e:
                results[table] = {"error": str(e)}

        return results
