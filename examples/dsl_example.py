from typing import Optional
import json
from fleet.verifiers import DatabaseSnapshot, IgnoreConfig, TASK_SUCCESSFUL_SCORE


def validate_new_deal_creation(
    before: "DatabaseSnapshot",
    after: "DatabaseSnapshot",
    transcript: Optional[str] = None,
) -> int:
    """Validate that a new deal (id 30835, name 'testing') was created correctly."""

    # 1️⃣ Locate the new deal entry
    new_deal = after.table("entries").eq("id", 30835).first()
    if not new_deal:
        raise AssertionError("Expected new deal with id 30835 not found")

    # 2️⃣ Basic field checks
    if new_deal["type"] != "deal":
        raise AssertionError(f"Expected entry type 'deal', got '{new_deal['type']}'")
    if new_deal["name"] != "testing":
        raise AssertionError(f"Expected deal name 'testing', got '{new_deal['name']}'")

    # 3️⃣ Property-level checks
    properties = json.loads(new_deal["properties"])

    if properties.get("dealstage") != "appointmentscheduled":
        raise AssertionError(
            f"Expected deal stage 'appointmentscheduled', got '{properties.get('dealstage')}'"
        )
    if properties.get("deal_type") != "newbusiness":
        raise AssertionError(
            f"Expected deal type 'newbusiness', got '{properties.get('deal_type')}'"
        )
    if properties.get("priority") != "medium":
        raise AssertionError(
            f"Expected priority 'medium', got '{properties.get('priority')}'"
        )
    if properties.get("pipeline") != "default":
        raise AssertionError(
            f"Expected pipeline 'default', got '{properties.get('pipeline')}'"
        )

    # 4️⃣ Diff settings
    ignore_config = IgnoreConfig(
        tables={"pageviews"},
        table_fields={
            "entries": {"createdDate", "lastModifiedDate", "createdAt", "updatedAt"},
        },
    )

    expected_changes = [
        {
            "table": "entries",
            "pk": 30835,
            "field": None,
            "after": "__added__",
        }
    ]

    before.diff(after, ignore_config).expect_only(expected_changes)

    return TASK_SUCCESSFUL_SCORE
