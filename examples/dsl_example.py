import asyncio
import fleet as flt
from fleet.verifiers import DatabaseSnapshot, IgnoreConfig, TASK_SUCCESSFUL_SCORE


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
    env = await flt.env.get("4379cf6c")
    response = await env.verify(validate_new_deal_creation)
    print(f"Success: {response.success}")
    print(f"Result: {response.result}")
    print(f"Error: {response.error}")
    print(f"Message: {response.message}")


if __name__ == "__main__":
    asyncio.run(main())
