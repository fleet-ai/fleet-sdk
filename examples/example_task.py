#!/usr/bin/env python3
"""Example demonstrating task with verifier for Jira environment.

This example shows how to create a simple task with the @verifier decorator
that can be verified in a Jira environment.

Both sync and async verifiers are now supported for remote execution.
"""

import os
import asyncio
from datetime import datetime
from fleet import AsyncFleet, verifier, TASK_SUCCESSFUL_SCORE, Task
from dotenv import load_dotenv

# Constants for task failure
TASK_FAILED_SCORE = 0.0

load_dotenv()


# For remote execution, use a synchronous verifier
# This won't work locally with async environments, but works remotely
@verifier(key="create_bug_issue_sync")
def create_bug_issue_sync(
    env, project_key: str = "SCRUM", issue_title: str = "Sample Bug"
) -> float:
    """Synchronous verifier for remote execution.

    Note: This is designed for remote execution where env.db() returns sync resources.
    """
    # Define constants locally for remote execution
    TASK_SUCCESSFUL_SCORE = 1.0
    TASK_FAILED_SCORE = 0.0

    try:
        # Get the database resource
        db = env.db()

        # Query for issues with the specified title and project
        query = """
        SELECT id, issue_type, name, project_key 
        FROM issues 
        WHERE project_key = ? AND name = ? AND issue_type = 'Bug'
        """

        result = db.query(query, args=[project_key, issue_title])

        if result.rows and len(result.rows) > 0:
            print(f"✓ Found bug issue: {result.rows[0][0]} - {result.rows[0][2]}")
            return TASK_SUCCESSFUL_SCORE
        else:
            print(
                f"✗ No bug issue found with title '{issue_title}' in project {project_key}"
            )
            return TASK_FAILED_SCORE

    except Exception as e:
        print(f"✗ Error checking for bug issue: {e}")
        return TASK_FAILED_SCORE


# For local execution with async environments
@verifier(key="create_bug_issue_async")
async def create_bug_issue_async(
    env, project_key: str = "SCRUM", issue_title: str = "Sample Bug"
) -> float:
    """Async verifier for local execution with async environments."""
    try:
        # Get the database resource
        db = env.db()

        # Query for issues with the specified title and project
        query = """
        SELECT id, issue_type, name, project_key 
        FROM issues 
        WHERE project_key = ? AND name = ? AND issue_type = 'Bug'
        """

        result = await db.query(query, args=[project_key, issue_title])

        if result.rows and len(result.rows) > 0:
            print(f"✓ Found bug issue: {result.rows[0][0]} - {result.rows[0][2]}")
            return TASK_SUCCESSFUL_SCORE
        else:
            print(
                f"✗ No bug issue found with title '{issue_title}' in project {project_key}"
            )
            return TASK_FAILED_SCORE

    except Exception as e:
        print(f"✗ Error checking for bug issue: {e}")
        return TASK_FAILED_SCORE


async def main():
    """Run the task example."""
    print("=== Fleet Task Example with Jira ===\n")
    print(
        "Note: Both sync and async verifiers are now supported for remote execution.\n"
    )

    # Create task using the async verifier for local execution
    task = Task(
        key="create-sample-bug",
        prompt="Create a new bug issue titled 'Login button not working' in the SCRUM project",
        env_id="fira:v1.3.1",
        verifier=create_bug_issue_async,
        metadata={"category": "issue_creation", "difficulty": "easy"},
    )

    print(f"Task definition:")
    print(f"  Key: {task.key}")
    print(f"  Prompt: {task.prompt}")
    print(f"  Environment: {task.env_id}")
    print(
        f"  Verifier: {task.verifier.key if hasattr(task.verifier, 'key') else 'create_bug_issue'}"
    )
    print(f"  Created at: {task.created_at}")
    print(f"  Metadata: {task.metadata}")
    print()

    # Create Fleet client and environment
    fleet_client = AsyncFleet()

    print("Creating Jira environment...")
    try:
        # Create a new Jira v1.3.1 environment
        env = await fleet_client.make("fira:v1.3.1")
        print(f"✓ Environment created: {env.instance_id}")
        print(f"  URL: {env.manager_url}")
        print()

        # Run the async verifier locally
        print("Running async verifier locally...")
        result = await create_bug_issue_async(
            env, project_key="SCRUM", issue_title="Login button not working"
        )
        print(f"  Initial check result: {result}")
        print()

        # Test remote execution with sync verifier
        print("Testing remote execution with sync verifier...")
        try:
            # Use the sync verifier for remote execution
            remote_result = await create_bug_issue_sync.remote(
                env, project_key="SCRUM", issue_title="Login button not working"
            )
            print(f"  ✓ Remote check result: {remote_result}")
            print(f"  ✓ Both returned failure as expected (issue doesn't exist yet)")
        except NotImplementedError as e:
            print(f"  ℹ️  {e}")
        except Exception as e:
            print(f"  ✗ Remote execution failed: {e}")
        print()

        # Test async verifier remote execution
        print("Testing remote execution with async verifier...")
        try:
            result = await create_bug_issue_async.remote(
                env, project_key="SCRUM", issue_title="Login button not working"
            )
            print(f"  ✓ Async remote check result: {result}")
        except NotImplementedError as e:
            print(f"  ✓ Expected error: {e}")
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")
            import traceback

            traceback.print_exc()
        print()

        # Create the issue
        print("Creating the bug issue programmatically...")
        db = env.db()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        await db.exec(
            """
            INSERT INTO issues (id, project_key, issue_type, name, status, created_at, updated_at)
            VALUES ('SCRUM-9999', 'SCRUM', 'Bug', 'Login button not working', 'Todo', ?, ?)
        """,
            args=[timestamp, timestamp],
        )

        print("✓ Bug issue created")
        print()

        # Run verifier again locally
        print("Running async verifier locally after creating the issue...")
        result = await create_bug_issue_async(
            env, project_key="SCRUM", issue_title="Login button not working"
        )
        print(f"  Final check result: {result}")
        print(
            f"  Task {'completed successfully' if result == TASK_SUCCESSFUL_SCORE else 'failed'}!"
        )
        print()

        # Clean up
        print("Cleaning up...")
        await env.close()
        print("✓ Environment closed")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
