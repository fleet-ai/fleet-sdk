from fleet.verifiers import DatabaseSnapshot, IgnoreConfig

async def validate_give_me_more_tasks(
    before: DatabaseSnapshot,
    after: DatabaseSnapshot,
    transcript: str | None = None,
) -> int:
    """Validate that bugs are moved to sprint 3 and assigned correctly."""

    # Get user IDs
    raj_user = after.table("users").eq("name", "Raj Patel").first()
    sarah_kim_user = after.table("users").eq("name", "Sarah Kim").first()

    if not raj_user:
        raise AssertionError("User 'Raj Patel' not found")
    if not sarah_kim_user:
        raise AssertionError("User 'Sarah Kim' not found")

    raj_id = raj_user["id"]
    sarah_kim_id = sarah_kim_user["id"]

    # Verify SCRUM-555 (data pipeline bug) is assigned to Sarah Kim
    after.table("issues").eq("id", "SCRUM-555").assert_eq("owner", sarah_kim_id)

    # Verify other bugs are assigned to Raj Patel
    other_bugs = [
        "SCRUM-780",
        "SCRUM-781",
        "SCRUM-790",
        "SCRUM-822",
        "SCRUM-882",
        "SCRUM-897",
        "SCRUM-956",
        "SCRUM-1331",
        "SCRUM-1312",
        "SCRUM-1210",
        "SCRUM-1230",
        "SCRUM-1282",
    ]
    for bug_id in other_bugs:
        after.table("issues").eq("id", bug_id).assert_eq("owner", raj_id)

    # Verify all bugs are in sprint_3
    all_bugs = ["SCRUM-555"] + other_bugs
    for bug_id in all_bugs:
        after.table("sprint_issues").eq("issue_id", bug_id).assert_eq(
            "sprint_id", "sprint_3"
        )

    # Configure ignore settings
    ignore_config = IgnoreConfig(
        tables={"activities", "pageviews", "sprint_issues"},
        table_fields={
            "issues": {"updated_at", "created_at", "rowid"},
            "users": {"updated_at", "created_at", "rowid"},
            "sprint_issues": {"updated_at", "created_at", "rowid"},
        },
    )

    # Build expected changes
    expected_changes: list[dict] = []

    # Assignment changes
    expected_changes.append(
        {
            "table": "issues",
            "pk": "SCRUM-555",
            "field": "owner",
            "after": sarah_kim_id,
        }
    )
    for bug_id in other_bugs:
        expected_changes.append(
            {
                "table": "issues",
                "pk": bug_id,
                "field": "owner",
                "after": raj_id,
            }
        )

    # Sprint changes
    for bug_id in all_bugs:
        # Remove from previous sprint if present
        before_assignment = (
            before.table("sprint_issues").eq("issue_id", bug_id).first()
        )
        if before_assignment:
            old_sprint = before_assignment.get("sprint_id")
            expected_changes.append(
                {
                    "table": "sprint_issues",
                    "pk": (old_sprint, bug_id),
                    "field": None,
                    "after": "__removed__",
                }
            )

        # Add to sprint_3
        expected_changes.append(
            {
                "table": "sprint_issues",
                "pk": ("sprint_3", bug_id),
                "field": None,
                "after": "__added__",
            }
        )

    # Enforce invariant
    before.diff(after, ignore_config).expect_only(expected_changes)

    return TASK_SUCCESSFUL_SCORE
