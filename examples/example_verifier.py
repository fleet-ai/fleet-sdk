#!/usr/bin/env python3
"""Example demonstrating verifier functionality with Fleet SDK.

This example shows how to use the @verifier decorator to create
functions that can be executed both locally and remotely.

Key features demonstrated:
1. Basic verifier with score return
2. Verifier with detailed results (dict with "score" key)
3. Complex verifier with configuration
4. Verifier with local function dependencies (bundled automatically)
5. Bundle creation and caching
"""

import asyncio
import fleet as flt
from fleet._async.verifiers import verifier, DatabaseSnapshot, TASK_SUCCESSFUL_SCORE
from dotenv import load_dotenv

load_dotenv()


@verifier(name="check_user_count", extra_requirements=["pandas>=2.0.0"])
def check_user_count(env, expected_count: int) -> float:
    """Verify that the database has at least the expected number of users."""
    print(f"   Checking user count >= {expected_count}")

    # Mock result
    actual_count = 3  # Simulated count

    if actual_count >= expected_count:
        return TASK_SUCCESSFUL_SCORE  # 1.0
    else:
        return 0.0


@verifier(
    name="validate_database_state",
    extra_requirements=["pandas>=2.0.0", "numpy>=1.24.0"],
)
def validate_database_state(env, table_name: str, min_rows: int = 10) -> dict:
    """Validate that a table exists and has minimum number of rows."""
    print(f"   Validating table '{table_name}' has >= {min_rows} rows")

    # Mock validation
    # In real usage, you would query the database
    # db = env.db()
    # result = db.query(f"SELECT COUNT(*) FROM {table_name}")

    # Simulate result
    row_count = 15

    if row_count >= min_rows:
        return {
            "score": 1.0,
            "details": f"Table '{table_name}' has {row_count} rows (min required: {min_rows})",
        }
    else:
        return {
            "score": 0.5,
            "details": f"Table '{table_name}' has only {row_count} rows (min required: {min_rows})",
        }


@verifier(name="complex_data_validation")
def complex_validation(env, config: dict) -> float:
    """Example of a more complex verifier that uses configuration."""
    score = 0.0
    checks_passed = 0
    total_checks = len(config.get("checks", []))

    print(f"   Running {total_checks} validation checks")

    for check in config.get("checks", []):
        check_type = check.get("type")

        if check_type == "table_exists":
            table_name = check.get("table")
            # Simulate table existence check
            print(f"     - Checking if table '{table_name}' exists")
            checks_passed += 1  # Mock: assume all tables exist

        elif check_type == "row_count":
            table_name = check.get("table")
            expected = check.get("count", 0)
            # Simulate row count check
            print(f"     - Checking if table '{table_name}' has >= {expected} rows")
            checks_passed += 1  # Mock: assume all counts are satisfied

    if total_checks > 0:
        score = checks_passed / total_checks

    return score


# Helper function that will be bundled
def calculate_score_percentage(passed: int, total: int) -> float:
    """Calculate percentage score."""
    if total == 0:
        return 0.0
    return (passed / total) * 100


@verifier(name="example_with_local_import", extra_requirements=[])
def verifier_with_local_dependency(env, threshold: float = 80.0) -> float:
    """Example verifier that uses a local function (will be bundled)."""
    print("   Running verifier with local dependency")

    # Simulate some checks
    checks_passed = 8
    total_checks = 10

    # Use local function that will be bundled
    percentage = calculate_score_percentage(checks_passed, total_checks)
    print(f"   Score percentage: {percentage}%")

    # Return 1.0 if above threshold, 0.0 otherwise
    return 1.0 if percentage >= threshold else 0.0


async def main():
    # Create environment
    env = await flt.env.make_async("hubspot")

    print("=== Fleet Verifier Examples ===\n")

    # Example 1: Local execution
    print("1. Local execution of verifier:")
    local_score = await check_user_count(env, expected_count=5)
    print(f"   Local score: {local_score}")

    # Example 2: Remote execution (when API endpoints are ready)
    print("\n2. Remote execution of verifier:")
    try:
        # This will bundle the function and its dependencies, then execute remotely
        remote_score = await check_user_count.remote(env, expected_count=5)
        print(f"   Remote score: {remote_score}")
    except Exception as e:
        print(f"   Remote execution not available yet: {e}")

    # Example 3: Verifier with detailed results
    print("\n3. Database validation with details:")
    validation_result = await validate_database_state(env, "users", min_rows=10)
    print(f"   Score: {validation_result}")

    # Example 4: Complex configuration-based verifier
    print("\n4. Complex validation with configuration:")
    config = {
        "checks": [
            {"type": "table_exists", "table": "users"},
            {"type": "table_exists", "table": "orders"},
            {"type": "row_count", "table": "users", "count": 5},
            {"type": "row_count", "table": "orders", "count": 1},
        ]
    }
    complex_score = await complex_validation(env, config)
    print(f"   Complex validation score: {complex_score}")

    # Example 5: Verifier with local dependencies
    print("\n5. Verifier with local function dependency:")
    local_dep_score = await verifier_with_local_dependency(env, threshold=75.0)
    print(f"   Local dependency verifier score: {local_dep_score}")

    # Example 6: Demonstrate bundler functionality
    print("\n6. Bundler functionality demonstration:")
    try:
        # The bundler will automatically detect and include the calculate_score_percentage function
        # when creating the bundle for verifier_with_local_dependency
        bundle_data, bundle_sha = verifier_with_local_dependency._get_or_create_bundle()
        print(f"   Bundle created with SHA: {bundle_sha[:8]}...")
        print(f"   Bundle size: {len(bundle_data)} bytes")
        
        # Show bundle contents
        import base64
        import zipfile
        import io
        
        # Convert bundle to base64 and show truncated version
        bundle_b64 = base64.b64encode(bundle_data).decode('utf-8')
        print(f"   Bundle base64 (first 100 chars): {bundle_b64[:100]}...")
        
        # Examine bundle contents
        print("\n   Bundle contents:")
        with zipfile.ZipFile(io.BytesIO(bundle_data), 'r') as zf:
            for filename in sorted(zf.namelist()):
                file_info = zf.getinfo(filename)
                print(f"     - {filename} ({file_info.file_size} bytes)")
                
                # Show content of key files
                if filename in ['requirements.txt', 'metadata.json']:
                    content = zf.read(filename).decode('utf-8')
                    print(f"       Content: {content.strip()}")
                elif filename == 'verifier.py':
                    # Show that the helper function was bundled
                    content = zf.read(filename).decode('utf-8')
                    # Check if helper function is included
                    if 'calculate_score_percentage' in content:
                        print(f"       ✓ Contains helper function 'calculate_score_percentage'")
                    print(f"       Preview (first 200 chars): {content[:200]}...")
                    
    except Exception as e:
        print(f"   Bundle creation demonstration: {e}")

    # Example 7: Using DatabaseSnapshot for state comparison
    print("\n7. Database snapshot comparison:")
    try:
        # Take initial snapshot
        initial_snapshot = await DatabaseSnapshot.create(env)
        print("   Initial snapshot taken")

        # Make some changes (simulate)
        # await env.db().query("INSERT INTO users (name) VALUES ('test_user')")

        # Take new snapshot and compare
        # new_snapshot = await DatabaseSnapshot.create(env)
        # diff = initial_snapshot.diff(new_snapshot)
        # print(f"   Changes detected: {diff}")
    except Exception as e:
        print(f"   Snapshot feature requires database access: {e}")

    print("\n=== Bundler Information ===")
    print("The verifier decorator automatically:")
    print("- Detects and bundles function dependencies")
    print("- Creates a deployable package with requirements.txt")
    print("- Caches bundles based on SHA to avoid re-uploads")
    print("- Supports both local and remote execution")
    print("\nBundle contents include:")
    print("- The verifier function itself")
    print("- Any local functions it imports or uses")
    print("- A requirements.txt with specified dependencies")
    print("- Auto-generated __init__.py files")

    await env.close()


if __name__ == "__main__":
    asyncio.run(main())
