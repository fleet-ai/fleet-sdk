"""
Shared validation logic for database diff verification.

This module contains pure functions for validating database diffs against
expected change specifications. Used by both SyncSnapshotDiff and SnapshotDiff.
"""

from typing import Any, Dict, List, Optional, Tuple


def _values_equivalent(expected: Any, actual: Any) -> bool:
    """Check if two values are equivalent, handling type coercion."""
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    # Handle numeric comparisons (int vs float)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return float(expected) == float(actual)
    # Handle string comparisons
    if isinstance(expected, str) and isinstance(actual, str):
        return expected == actual
    # Default comparison
    return expected == actual


def _parse_fields_spec(fields_spec: List[Tuple[str, Any]]) -> Dict[str, Tuple[bool, Any]]:
    """Parse a fields spec into a mapping of field_name -> (should_check_value, expected_value)."""
    spec_map = {}
    for item in fields_spec:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError(
                f"Invalid field spec: {item!r}. "
                f"Each field must be a 2-tuple: (field_name, expected_value). "
                f"Use (field_name, ...) to accept any value."
            )
        field_name, expected_value = item
        if expected_value is ...:
            spec_map[field_name] = (False, None)  # Don't check value
        else:
            spec_map[field_name] = (True, expected_value)
    return spec_map


def validate_diff_expect_exactly(
    diff: Dict[str, Any],
    expected_changes: List[Dict[str, Any]],
    ignore_config: Any = None,
) -> Tuple[bool, Optional[str], List[Tuple[str, str, str]]]:
    """
    Validate that EXACTLY the specified changes occurred in the diff.

    This is stricter than expect_only_v2:
    1. All changes in diff must match a spec (no unexpected changes)
    2. All specs must have a matching change in diff (no missing expected changes)

    Args:
        diff: The database diff dictionary
        expected_changes: List of expected change specs
        ignore_config: Optional ignore configuration with should_ignore_field method

    Returns:
        Tuple of (success, error_message, matched_specs)
        - success: True if validation passed
        - error_message: Error message if validation failed, None otherwise
        - matched_specs: List of (table, pk, type) tuples that matched
    """
    # Validate all specs have required fields
    for i, spec in enumerate(expected_changes):
        if "type" not in spec:
            raise ValueError(
                f"Spec at index {i} is missing required 'type' field. "
                f"expect_exactly requires explicit type: 'insert', 'modify', or 'delete'. "
                f"Got: {spec}"
            )
        if spec["type"] not in ("insert", "modify", "delete"):
            raise ValueError(
                f"Spec at index {i} has invalid type '{spec['type']}'. "
                f"Must be 'insert', 'modify', or 'delete'."
            )
        if "table" not in spec:
            raise ValueError(
                f"Spec at index {i} is missing required 'table' field. Got: {spec}"
            )
        if "pk" not in spec:
            raise ValueError(
                f"Spec at index {i} is missing required 'pk' field. Got: {spec}"
            )

    # Collect all errors into categories
    field_mismatches = []      # Changes that happened but with wrong field values
    unexpected_changes = []     # Changes that happened but no spec allows them
    missing_changes = []        # Specs that expect changes that didn't happen
    matched_specs = []          # Successfully matched specs
    near_matches = []           # Potential matches for hints

    # Build lookup for specs by (table, pk, type)
    spec_lookup = {}
    for spec in expected_changes:
        key = (spec.get("table"), str(spec.get("pk")), spec.get("type"))
        spec_lookup[key] = spec

    def should_ignore_field(table: str, field: str) -> bool:
        if ignore_config is None:
            return False
        if hasattr(ignore_config, 'should_ignore_field'):
            return ignore_config.should_ignore_field(table, field)
        return False

    # Check each change in the diff
    for tbl, report in diff.items():
        # Check insertions
        for row in report.get("added_rows", []):
            row_id = row["row_id"]
            row_data = row.get("data", {})
            spec_key = (tbl, str(row_id), "insert")
            spec = spec_lookup.get(spec_key)

            if spec is None:
                # No spec for this insertion
                unexpected_changes.append({
                    "type": "insert",
                    "table": tbl,
                    "pk": row_id,
                    "row_data": row_data,
                    "reason": "no spec provided",
                })
            elif "fields" in spec and spec["fields"] is not None:
                # Validate fields
                spec_map = _parse_fields_spec(spec["fields"])
                mismatches = []
                for field_name, field_value in row_data.items():
                    if field_name == "rowid":
                        continue
                    if should_ignore_field(tbl, field_name):
                        continue
                    if field_name not in spec_map:
                        mismatches.append((field_name, None, field_value, "not in spec"))
                    else:
                        should_check, expected = spec_map[field_name]
                        if should_check and not _values_equivalent(expected, field_value):
                            mismatches.append((field_name, expected, field_value, "value mismatch"))

                if mismatches:
                    field_mismatches.append({
                        "type": "insert",
                        "table": tbl,
                        "pk": row_id,
                        "mismatches": mismatches,
                        "row_data": row_data,
                    })
                else:
                    matched_specs.append(spec_key)
            else:
                # Spec without fields - just check it exists
                matched_specs.append(spec_key)

        # Check deletions
        for row in report.get("removed_rows", []):
            row_id = row["row_id"]
            row_data = row.get("data", {})
            spec_key = (tbl, str(row_id), "delete")
            spec = spec_lookup.get(spec_key)

            if spec is None:
                unexpected_changes.append({
                    "type": "delete",
                    "table": tbl,
                    "pk": row_id,
                    "row_data": row_data,
                    "reason": "no spec provided",
                })
            else:
                # For deletes, just matching the pk is enough (unless fields specified)
                if "fields" in spec and spec["fields"] is not None:
                    spec_map = _parse_fields_spec(spec["fields"])
                    mismatches = []
                    for field_name, field_value in row_data.items():
                        if field_name == "rowid":
                            continue
                        if should_ignore_field(tbl, field_name):
                            continue
                        if field_name in spec_map:
                            should_check, expected = spec_map[field_name]
                            if should_check and not _values_equivalent(expected, field_value):
                                mismatches.append((field_name, expected, field_value, "value mismatch"))
                    if mismatches:
                        field_mismatches.append({
                            "type": "delete",
                            "table": tbl,
                            "pk": row_id,
                            "mismatches": mismatches,
                            "row_data": row_data,
                        })
                    else:
                        matched_specs.append(spec_key)
                else:
                    matched_specs.append(spec_key)

        # Check modifications
        for row in report.get("modified_rows", []):
            row_id = row["row_id"]
            row_changes = row.get("changes", {})
            row_data = row.get("data", {})
            spec_key = (tbl, str(row_id), "modify")
            spec = spec_lookup.get(spec_key)

            if spec is None:
                unexpected_changes.append({
                    "type": "modify",
                    "table": tbl,
                    "pk": row_id,
                    "changes": row_changes,
                    "row_data": row_data,
                    "reason": "no spec provided",
                })
            elif "resulting_fields" in spec and spec["resulting_fields"] is not None:
                # Validate that no_other_changes is provided and is a boolean
                if "no_other_changes" not in spec:
                    raise ValueError(
                        f"Modify spec for table '{tbl}' pk={row_id} "
                        f"has 'resulting_fields' but missing required 'no_other_changes' field. "
                        f"Set 'no_other_changes': True to verify no other fields changed, "
                        f"or 'no_other_changes': False to only check the specified fields."
                    )
                no_other_changes = spec["no_other_changes"]
                if not isinstance(no_other_changes, bool):
                    raise ValueError(
                        f"Modify spec for table '{tbl}' pk={row_id} "
                        f"has 'no_other_changes' but it must be a boolean (True or False), "
                        f"got {type(no_other_changes).__name__}: {repr(no_other_changes)}"
                    )

                spec_map = _parse_fields_spec(spec["resulting_fields"])
                mismatches = []

                for field_name, vals in row_changes.items():
                    if should_ignore_field(tbl, field_name):
                        continue
                    after_value = vals["after"]
                    if field_name not in spec_map:
                        if no_other_changes:
                            mismatches.append((field_name, None, after_value, "not in resulting_fields"))
                    else:
                        should_check, expected = spec_map[field_name]
                        if should_check and not _values_equivalent(expected, after_value):
                            mismatches.append((field_name, expected, after_value, "value mismatch"))

                if mismatches:
                    field_mismatches.append({
                        "type": "modify",
                        "table": tbl,
                        "pk": row_id,
                        "mismatches": mismatches,
                        "changes": row_changes,
                        "row_data": row_data,
                    })
                else:
                    matched_specs.append(spec_key)
            else:
                # Spec without resulting_fields - just check it exists
                matched_specs.append(spec_key)

    # Check for missing expected changes (specs that weren't matched)
    for spec in expected_changes:
        spec_key = (spec.get("table"), str(spec.get("pk")), spec.get("type"))
        if spec_key not in matched_specs:
            # Check if it's already in field_mismatches (partially matched but wrong values)
            already_reported = any(
                fm["table"] == spec.get("table") and
                str(fm["pk"]) == str(spec.get("pk")) and
                fm["type"] == spec.get("type")
                for fm in field_mismatches
            )
            if not already_reported:
                missing_changes.append({
                    "type": spec.get("type"),
                    "table": spec.get("table"),
                    "pk": spec.get("pk"),
                    "spec": spec,
                })

    # Detect near-matches (potential wrong-row scenarios)
    for uc in unexpected_changes:
        for mc in missing_changes:
            if uc["table"] == mc["table"] and uc["type"] == mc["type"]:
                # Same table and operation type, different pk - might be wrong row
                near_matches.append({
                    "unexpected": uc,
                    "missing": mc,
                    "actual_pk": uc["pk"],
                    "expected_pk": mc["pk"],
                    "operation": uc["type"],
                })

    # Build error message if there are any errors
    total_errors = len(field_mismatches) + len(unexpected_changes) + len(missing_changes)

    if total_errors == 0:
        return True, None, matched_specs

    # Format error message
    error_msg = _format_expect_exactly_error(
        field_mismatches=field_mismatches,
        unexpected_changes=unexpected_changes,
        missing_changes=missing_changes,
        matched_specs=matched_specs,
        near_matches=near_matches,
        total_errors=total_errors,
    )

    return False, error_msg, matched_specs


def _format_expect_exactly_error(
    field_mismatches: List[Dict],
    unexpected_changes: List[Dict],
    missing_changes: List[Dict],
    matched_specs: List[Tuple],
    near_matches: List[Dict],
    total_errors: int,
) -> str:
    """Format the error message for expect_exactly failures."""
    lines = []
    lines.append("=" * 80)
    lines.append(f"VERIFICATION FAILED: {total_errors} error(s) detected")
    lines.append("=" * 80)
    lines.append("")

    # Summary
    lines.append("SUMMARY")
    lines.append(f"  Matched:  {len(matched_specs)} change(s) verified successfully")
    lines.append(f"  Errors:   {total_errors}")
    if field_mismatches:
        pks = ", ".join(str(fm["pk"]) for fm in field_mismatches)
        lines.append(f"    - Field mismatches:     {len(field_mismatches)} (pk: {pks})")
    if unexpected_changes:
        pks = ", ".join(str(uc["pk"]) for uc in unexpected_changes)
        lines.append(f"    - Unexpected changes:   {len(unexpected_changes)} (pk: {pks})")
    if missing_changes:
        pks = ", ".join(str(mc["pk"]) for mc in missing_changes)
        lines.append(f"    - Missing changes:      {len(missing_changes)} (pk: {pks})")
    lines.append("")

    error_num = 1

    # Field mismatches section
    if field_mismatches:
        lines.append("-" * 80)
        lines.append(f"FIELD MISMATCHES ({len(field_mismatches)})")
        lines.append("-" * 80)
        lines.append("")

        for fm in field_mismatches:
            op_type = fm["type"].upper()
            lines.append(f"[{error_num}] {op_type} '{fm['table']}' pk={fm['pk']}")
            lines.append("")
            # Side-by-side comparison table
            lines.append("    FIELD                EXPECTED                                      ACTUAL")
            lines.append("    " + "-" * 85)
            for field_name, expected, actual, reason in fm["mismatches"]:
                # Truncate field name if too long
                field_display = field_name if len(field_name) <= 20 else field_name[:17] + "..."

                # Generate clear error message based on reason
                if reason == "not in spec":
                    # Insert: field in row but not in fields spec
                    exp_str = f"(field '{field_name}' not specified in expected fields)"
                elif reason == "not in resulting_fields":
                    # Modify: field changed but not in resulting_fields
                    exp_str = f"(field '{field_name}' not specified in resulting_fields)"
                elif expected is None:
                    exp_str = "None"  # Explicitly expected NULL
                else:
                    exp_str = repr(expected)
                act_str = repr(actual)
                # Truncate long values (but not the descriptive error messages)
                if not exp_str.startswith("(field"):
                    if len(exp_str) > 20:
                        exp_str = exp_str[:17] + "..."
                if len(act_str) > 20:
                    act_str = act_str[:17] + "..."
                lines.append(f"    {field_display:<20} {exp_str:<45} {act_str:<20}")
            lines.append("")
            error_num += 1

    # Unexpected changes section
    if unexpected_changes:
        lines.append("-" * 80)
        lines.append(f"UNEXPECTED CHANGES ({len(unexpected_changes)})")
        lines.append("-" * 80)
        lines.append("")

        for uc in unexpected_changes:
            op_type = uc["type"].upper()
            lines.append(f"[{error_num}] {op_type} '{uc['table']}' pk={uc['pk']}")
            lines.append(f"    No spec was provided for this {uc['type']}.")
            if "row_data" in uc and uc["row_data"]:
                # Format row data compactly
                data_parts = []
                for k, v in list(uc["row_data"].items())[:4]:
                    if k != "rowid":
                        data_parts.append(f"{k}={repr(v)}")
                data_str = ", ".join(data_parts)
                if len(uc["row_data"]) > 4:
                    data_str += f", ... +{len(uc['row_data']) - 4} more"
                lines.append(f"    Row data: {{{data_str}}}")
            lines.append("")
            error_num += 1

    # Missing expected changes section
    if missing_changes:
        lines.append("-" * 80)
        lines.append(f"MISSING EXPECTED CHANGES ({len(missing_changes)})")
        lines.append("-" * 80)
        lines.append("")

        for mc in missing_changes:
            op_type = mc["type"].upper()
            lines.append(f"[{error_num}] {op_type} '{mc['table']}' pk={mc['pk']}")
            if mc["type"] == "insert":
                lines.append(f"    Expected this row to be INSERTED, but it was not added.")
                if "spec" in mc and "fields" in mc["spec"] and mc["spec"]["fields"]:
                    lines.append("    Expected fields:")
                    for field_name, value in mc["spec"]["fields"][:5]:
                        if value is ...:
                            lines.append(f"      - {field_name}: (any value)")
                        else:
                            lines.append(f"      - {field_name}: {repr(value)}")
                    if len(mc["spec"]["fields"]) > 5:
                        lines.append(f"      ... +{len(mc['spec']['fields']) - 5} more")
            elif mc["type"] == "delete":
                lines.append(f"    Expected this row to be DELETED, but it still exists.")
            elif mc["type"] == "modify":
                lines.append(f"    Expected this row to be MODIFIED, but it was not changed.")
                if "spec" in mc and "resulting_fields" in mc["spec"] and mc["spec"]["resulting_fields"]:
                    lines.append("    Expected resulting values:")
                    for field_name, value in mc["spec"]["resulting_fields"][:5]:
                        if value is ...:
                            lines.append(f"      - {field_name}: (any value)")
                        else:
                            lines.append(f"      - {field_name}: {repr(value)}")
            lines.append("")
            error_num += 1

    # Near-match hints section
    if near_matches:
        lines.append("-" * 80)
        lines.append("HINTS: Possible related errors (near-matches detected)")
        lines.append("-" * 80)
        lines.append("")
        for nm in near_matches:
            op_type = nm["operation"].upper()
            lines.append(f"  * {op_type} row {nm['actual_pk']} might be intended as row {nm['expected_pk']}")
        lines.append("")

    lines.append("=" * 80)

    return "\n".join(lines)
