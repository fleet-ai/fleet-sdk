import asyncio
import fleet
from fleet.verifiers import DatabaseSnapshot, IgnoreConfig, TASK_SUCCESSFUL_SCORE
from dotenv import load_dotenv

load_dotenv()


def validate_new_deal_creation(
    before: DatabaseSnapshot,
    after: DatabaseSnapshot,
    transcript: str | None = None,
) -> int:
    """Validate that a new deal was created"""

    # Find the new deal entry
    new_deal = after.table("entries").eq("id", 32302).first()
    if not new_deal:
        raise AssertionError("Expected new deal with id 32302 not found")

    # Verify it's a deal type
    if new_deal["type"] != "deal":
        raise AssertionError(
            f"Expected entry type to be 'deal', got '{new_deal['type']}'"
        )

    # Verify the deal has a name (should be "testing" based on the diff)
    if not new_deal["name"]:
        raise AssertionError("Expected deal to have a name")

    # Parse the properties JSON to check basic deal properties
    import json

    properties = json.loads(new_deal["properties"])

    # Verify it has basic deal properties
    if "dealstage" not in properties:
        raise AssertionError("Expected deal to have a dealstage property")

    if "deal_type" not in properties:
        raise AssertionError("Expected deal to have a deal_type property")

    if "priority" not in properties:
        raise AssertionError("Expected deal to have a priority property")

    # Configure ignore settings
    ignore_config = IgnoreConfig(
        tables={"pageviews"},
        table_fields={
            "entries": {"createdDate", "lastModifiedDate", "createdAt", "updatedAt"},
        },
    )

    # Build expected changes
    expected_changes = [
        {
            "table": "entries",
            "pk": 32302,
            "field": None,
            "after": "__added__",
        }
    ]

    before.diff(after, ignore_config).expect_only(expected_changes)
    return TASK_SUCCESSFUL_SCORE


async def main():
    # Create a new instance
    print("Creating new Hubspot instance...")
    env = await fleet.env.make_async("hubspot")
    print(f"New Instance: {env.instance_id}")

    try:
        # Reset the instance
        response = await env.reset(seed=42)
        print(f"Reset response: {response}")

        # Run verifier before insertion (should fail)
        print("\nRunning verifier before insertion...")
        response = await env.verify(validate_new_deal_creation)
        print(f"Success: {response.success}")
        print(f"Result: {response.result}")
        print(f"Error: {response.error}")
        print(f"Message: {response.message}")

        # Get the database resource
        await env.instance.load()
        db = env.db()

        # Take a snapshot before insertion
        print("\nTaking snapshot before insertion...")
        snapshot_before = await db.snapshot("before_insertion")
        print(f"Snapshot created: {snapshot_before.name}")

        # Insert the deal entry
        print("\nInserting deal entry...")
        insert_query = """
        INSERT INTO entries (id, name, type, owner_id, createdDate, lastModifiedDate, createdAt, updatedAt, archivedAt, properties)
        VALUES (
            32302,
            'testing',
            'deal',
            1,
            '2025-07-10T01:32:01.089Z',
            '2025-07-10T01:32:01.089Z',
            '2025-07-10 01:32:01',
            '2025-07-10 01:32:01',
            NULL,
            '{"amount":null,"closedate":"2025-08-09","close_date":"2025-08-09","dealstage":"appointmentscheduled","pipeline":"default","description":null,"priority":"medium","deal_stage_probability":null,"deal_type":"newbusiness","hs_createdate":"2025-07-10T01:32:01.089Z","hs_object_source":"INTEGRATION","hs_object_source_id":"14696758","hs_object_source_label":"INTEGRATION","hs_is_closed":"false","hs_is_closed_count":"0","hs_is_closed_lost":"false","hs_is_closed_won":"false","hs_is_deal_split":"false","hs_is_open_count":"1","hs_num_associated_active_deal_registrations":"0","hs_num_associated_deal_registrations":"0","hs_num_associated_deal_splits":"0","hs_num_of_associated_line_items":"0","hs_num_target_accounts":"0","hs_number_of_call_engagements":"0","hs_number_of_inbound_calls":"0","hs_number_of_outbound_calls":"0","hs_number_of_overdue_tasks":"0","num_associated_contacts":"0","num_notes":"0","hs_closed_amount":"0","hs_closed_amount_in_home_currency":"0","hs_closed_deal_close_date":"0","hs_closed_deal_create_date":"0","hs_closed_won_count":"0","hs_v2_date_entered_current_stage":"2025-07-10T01:32:01.089Z","hs_v2_time_in_current_stage":"2025-07-10T01:32:01.089Z","hs_duration":"1752111121089","hs_open_deal_create_date":"1752111121089","days_to_close":"29","hs_days_to_close_raw":"29.936098506944443"}'
        )
        """

        print("RESOURCES", await env.resources())
        insert_result = await db.exec(insert_query)
        print(f"Insert result: {insert_result}")

        # Verify the insertion
        print("\nVerifying insertion...")
        query_result = await db.query("SELECT * FROM entries WHERE id = 32302")
        print(f"Query result: {query_result}")

        # Also verify using the new query builder
        print("\nVerifying with query builder:")
        entry = await db.table("entries").eq("id", 32302).first()
        if entry:
            print(f"Found entry: {entry['name']} (type: {entry['type']})")
            # Can also use assertions
            await db.table("entries").eq("id", 32302).assert_eq("type", "deal")
            print("✓ Entry type assertion passed")

        # Take a snapshot after insertion
        print("\nTaking snapshot after insertion...")
        snapshot_after = await db.snapshot("after_insertion")
        print(f"Snapshot created: {snapshot_after.name}")

        # Compare snapshots
        print("\nComparing snapshots...")
        ignore_config = IgnoreConfig(
            tables={"pageviews"},
            table_fields={
                "entries": {
                    "createdDate",
                    "lastModifiedDate",
                    "createdAt",
                    "updatedAt",
                },
            },
        )

        diff = await snapshot_before.diff(snapshot_after, ignore_config)

        # Check diff results
        print("\nDiff validation:")
        expected_changes = [
            {
                "table": "entries",
                "pk": 32302,
                "field": None,
                "after": "__added__",
            }
        ]

        try:
            await diff.expect_only(expected_changes)
            print("✓ Diff validation passed - only expected changes detected")
        except AssertionError as e:
            print(f"✗ Diff validation failed: {e}")

        # Run verifier after insertion (should succeed)
        print("\nRunning verifier after insertion...")
        response = await env.verify(validate_new_deal_creation)
        print(f"Success: {response.success}")
        print(f"Result: {response.result}")
        print(f"Error: {response.error}")
        print(f"Message: {response.message}")

    finally:
        # Delete the instance
        print("\nDeleting instance...")
        await env.close()
        print("Instance deleted.")


if __name__ == "__main__":
    asyncio.run(main())
