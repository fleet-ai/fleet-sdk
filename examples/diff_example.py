import asyncio
import fleet
from fleet.verifiers import IgnoreConfig
from dotenv import load_dotenv

load_dotenv()


async def main():
    # Create a new instance
    print("Creating new Hubspot instance...")
    env = await fleet.env.make_async("hubspot:v1.2.7")
    print(f"New Instance: {env.instance_id}")

    try:
        # Reset the instance
        response = await env.reset(seed=42)
        print(f"Reset response: {response}")

        # Get the database resource
        db = env.db()

        # Take initial snapshot
        print("\n=== Taking Initial Snapshot ===")
        snapshot1 = await db.snapshot("initial_state")
        print(f"Snapshot created: {snapshot1.name}")

        # Show current entries
        entries_count = await db.table("entries").count()
        print(f"Initial entry count: {entries_count}")

        # Make some changes
        print("\n=== Making Database Changes ===")

        # 1. Insert a new deal
        print("\n1. Inserting new deal...")
        await db.exec("""
            INSERT INTO entries (id, name, type, owner_id, createdDate, lastModifiedDate, createdAt, updatedAt, properties)
            VALUES (
                99001,
                'Test Deal 1',
                'deal',
                1,
                datetime('now'),
                datetime('now'),
                datetime('now'),
                datetime('now'),
                '{}'
            )
        """)

        # 2. Update an existing entry
        print("2. Updating existing entry...")
        await db.exec("""
            UPDATE entries 
            SET name = 'Updated Contact Name'
            WHERE id = 1
        """)

        # 3. Insert another entry
        print("3. Inserting another deal...")
        await db.exec("""
            INSERT INTO entries (id, name, type, owner_id, createdDate, lastModifiedDate, createdAt, updatedAt, properties)
            VALUES (
                99002,
                'Test Deal 2',
                'deal',
                1,
                datetime('now'),
                datetime('now'),
                datetime('now'),
                datetime('now'),
                '{}'
            )
        """)

        # Take second snapshot
        print("\n=== Taking Second Snapshot ===")
        snapshot2 = await db.snapshot("after_changes")
        print(f"Snapshot created: {snapshot2.name}")

        new_entries_count = await db.table("entries").count()
        print(f"New entry count: {new_entries_count}")

        # Compare snapshots
        print("\n=== Comparing Snapshots ===")

        # Configure what to ignore in diff
        ignore_config = IgnoreConfig(
            tables={"pageviews"},  # Ignore entire pageviews table
            fields={
                "createdDate",
                "lastModifiedDate",
                "createdAt",
                "updatedAt",
            },  # Ignore timestamp fields
        )

        diff = await snapshot1.diff(snapshot2, ignore_config)

        # Test 1: Validate all expected changes
        print("\nTest 1: Validating expected changes...")
        expected_changes = [
            # New deals added
            {"table": "entries", "pk": 99001, "field": None, "after": "__added__"},
            {"table": "entries", "pk": 99002, "field": None, "after": "__added__"},
            # Name updated
            {
                "table": "entries",
                "pk": 1,
                "field": "name",
                "after": "Updated Contact Name",
            },
        ]

        try:
            await diff.expect_only(expected_changes)
            print("✓ All changes validated successfully!")
        except AssertionError as e:
            print(f"✗ Validation failed: {e}")

        # Test 2: Try with incorrect expectations (should fail)
        print("\nTest 2: Testing with incorrect expectations...")
        incorrect_changes = [
            {"table": "entries", "pk": 99001, "field": None, "after": "__added__"},
            # Missing the second insert and the update
        ]

        try:
            await diff.expect_only(incorrect_changes)
            print("✗ This should have failed!")
        except AssertionError as e:
            print("✓ Correctly detected unexpected changes")
            print(f"   Error (first 200 chars): {str(e)[:200]}...")

        # Test 3: Query snapshot data directly
        print("\n=== Querying Snapshot Data ===")

        # Query from first snapshot
        print("\nQuerying from initial snapshot:")
        initial_entry = await snapshot1.table("entries").eq("id", 1).first()
        if initial_entry:
            print(f"Entry 1 name in snapshot1: {initial_entry['name']}")

        # Query from second snapshot
        print("\nQuerying from second snapshot:")
        updated_entry = await snapshot2.table("entries").eq("id", 1).first()
        if updated_entry:
            print(f"Entry 1 name in snapshot2: {updated_entry['name']}")

        # Count deals in each snapshot
        deals_before = await snapshot1.table("entries").eq("type", "deal").all()
        deals_after = await snapshot2.table("entries").eq("type", "deal").all()
        print(f"\nDeals in snapshot1: {len(deals_before)}")
        print(f"Deals in snapshot2: {len(deals_after)}")

        # Show new deals
        print("\nNew deals added:")
        for deal in deals_after:
            if deal["id"] in [99001, 99002]:
                print(f"  - {deal['name']} (id: {deal['id']})")

    finally:
        # Delete the instance
        print("\n\nDeleting instance...")
        await env.close()
        print("Instance deleted.")


if __name__ == "__main__":
    asyncio.run(main())
