import asyncio
import fleet
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

        # Example 1: Query with the builder pattern
        print("\n=== Query Builder Examples ===")

        # Find all entries of type 'deal'
        print("\n1. Finding all deals:")
        deals = await db.table("entries").eq("type", "deal").all()
        print(f"Found {len(deals)} deals")

        # Count entries
        print("\n2. Counting entries:")
        entry_count = await db.table("entries").count()
        print(f"Total entries: {entry_count}")

        # Find a specific entry
        print("\n3. Finding specific entry:")
        entry = await db.table("entries").eq("id", 1).first()
        if entry:
            print(f"Found entry: {entry['name']} (type: {entry['type']})")

        # Complex query with multiple conditions
        print("\n4. Complex query with conditions:")
        recent_deals = await (
            db.table("entries")
            .eq("type", "deal")
            .not_null("name")
            .select("id", "name", "type", "createdDate")
            .sort("createdDate", desc=True)
            .limit(5)
            .all()
        )
        print(f"Recent deals: {len(recent_deals)}")
        for deal in recent_deals:
            print(f"  - {deal['name']} (id: {deal['id']})")

        # Using assertions
        print("\n5. Using assertions:")
        try:
            # This should succeed if there are entries
            await db.table("entries").assert_exists()
            print("✓ Entries table has records")
        except AssertionError as e:
            print(f"✗ Assertion failed: {e}")

        # Check for non-existent record
        try:
            await db.table("entries").eq("id", 999999).assert_none()
            print("✓ No entry with id 999999")
        except AssertionError as e:
            print(f"✗ Assertion failed: {e}")

        # Insert a new entry and verify with query builder
        print("\n6. Insert and verify with query builder:")
        insert_query = """
        INSERT INTO entries (id, name, type, owner_id, createdDate, lastModifiedDate, createdAt, updatedAt, properties)
        VALUES (
            99999,
            'Test Deal via Query Builder',
            'deal',
            1,
            datetime('now'),
            datetime('now'),
            datetime('now'),
            datetime('now'),
            '{}'
        )
        """
        await db.exec(insert_query)

        # Verify insertion with query builder
        new_deal = await db.table("entries").eq("id", 99999).first()
        if new_deal:
            print(f"✓ Successfully inserted: {new_deal['name']}")

            # Assert specific field value
            await (
                db.table("entries")
                .eq("id", 99999)
                .assert_eq("name", "Test Deal via Query Builder")
            )
            print("✓ Name assertion passed")

        # Using IN clause
        print("\n7. Using IN clause:")
        specific_entries = await db.table("entries").in_("id", [1, 2, 3]).all()
        print(f"Found {len(specific_entries)} entries with ids in [1, 2, 3]")

        # Pattern matching with LIKE
        print("\n8. Pattern matching:")
        test_entries = await db.table("entries").ilike("name", "%test%").all()
        print(f"Found {len(test_entries)} entries with 'test' in name")

    finally:
        # Delete the instance
        print("\n\nDeleting instance...")
        await env.close()
        print("Instance deleted.")


if __name__ == "__main__":
    asyncio.run(main())
