import fleet as flt
from fleet.verifiers.verifier import verifier
from fleet.verifiers.db import IgnoreConfig


@verifier(key="validate_finish_blue_green_deployment")
def validate_finish_blue_green_deployment(
    env: flt.Environment, final_answer: str | None = None
) -> int:
    """Validate that DEBT-722 and DEBT-720 are marked as Done"""
    before = env.db("seed")
    after = env.db("current")

    # Check final state
    try:
        after.table("issues").eq("id", "DEBT-722").assert_eq("board_list", "Done")
    except:
        return 0
    try:
        after.table("issues").eq("id", "DEBT-720").assert_eq("board_list", "Done")
    except:
        return 0

    # Configure ignore settings for this validation
    ignore_config = IgnoreConfig(
        tables={"activities", "pageviews"},
        table_fields={
            "issues": {"updated_at", "created_at", "rowid"},
            "boards": {"updated_at", "created_at", "rowid"},
            "projects": {"updated_at", "created_at", "rowid"},
            "sprints": {"updated_at", "created_at", "rowid"},
            "users": {"updated_at", "created_at", "rowid"},
        },
    )

    # Enforce invariant: nothing else changed (with ignore configuration)
    try:
        before.diff(after, ignore_config).expect_only(
            [
                {
                    "table": "issues",
                    "pk": "DEBT-722",
                    "field": "board_list",
                    "after": "Done",
                },
                {
                    "table": "issues",
                    "pk": "DEBT-720",
                    "field": "board_list",
                    "after": "Done",
                },
            ]
        )
    except:
        return 0

    return 1


def main():
    env = flt.env.make("fira:v1.3.1")
    print(f"New Instance: {env.instance_id}")

    print(validate_finish_blue_green_deployment(env))
    print(validate_finish_blue_green_deployment.remote(env))

    env.close()


if __name__ == "__main__":
    main()
