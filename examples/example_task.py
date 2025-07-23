#!/usr/bin/env python3
"""Example demonstrating task with verifier for Jira environment.

This example shows how to create a simple task with the @verifier decorator
that can be verified in a Jira environment, including remote execution.
"""

import os
import asyncio
from datetime import datetime
from fleet import AsyncFleet, verifier, TASK_SUCCESSFUL_SCORE, Task
from dotenv import load_dotenv

# Constants for task failure
TASK_FAILED_SCORE = 0.0

load_dotenv()


# Define the synchronous version for remote execution
def create_bug_issue_sync(
    env, project_key: str = "SCRUM", issue_title: str = "Sample Bug"
) -> float:
    """Synchronous verifier that checks if a bug issue was created.
    
    This is used for remote execution which doesn't support async functions.
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


# Create the async decorated version with sync_version for remote execution
@verifier(key="create_bug_issue_v1", sync_version=create_bug_issue_sync)
async def create_bug_issue(
    env, project_key: str = "SCRUM", issue_title: str = "Sample Bug"
) -> float:
    """Async verifier for local execution and Task integration.
    
    This verifier:
    1. Queries the database to find issues with the specified title
    2. Checks if the issue is a Bug type
    3. Returns 1.0 if found, 0.0 otherwise
    """
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

    # Create task using the Task pydantic model
    task = Task(
        key="create-sample-bug",
        prompt="Create a new bug issue titled 'Login button not working' in the SCRUM project",
        env_id="fira:v1.3.1",
        verifier=create_bug_issue,
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

        # Run the verifier (simulating task completion check)
        print("Running verifier to check task completion...")

        # First check - should fail since we haven't created the issue
        result = await task.verifier(
            env, project_key="SCRUM", issue_title="Login button not working"
        )
        print(f"  Initial check result: {result}")
        print()

        # Test remote execution of the verifier
        print("Testing remote verifier execution...")
        try:
            # Now we can use .remote() directly on the decorated function!
            remote_result = await task.verifier.remote(
                env, project_key="SCRUM", issue_title="Login button not working"
            )
            print(f"  ✓ Remote check result: {remote_result}")
            print(
                f"  ✓ Remote execution {'matches' if remote_result == result else 'differs from'} local result"
            )
        except Exception as e:
            print(f"  ✗ Remote execution failed: {e}")
        print()

        # In a real scenario, an agent would perform the task here
        # For this example, we'll just show how the verifier would work
        print("💡 In a real scenario, an agent would now:")
        print("   1. Navigate to the Jira UI or use the API")
        print("   2. Create a new bug issue with the specified title")
        print("   3. The verifier would then confirm task completion")
        print()

        # Example of creating the issue programmatically
        print("Creating the bug issue programmatically...")
        db = env.db()

        # Get current timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Insert the bug issue
        await db.exec(
            """
            INSERT INTO issues (id, project_key, issue_type, name, status, created_at, updated_at)
            VALUES ('SCRUM-9999', 'SCRUM', 'Bug', 'Login button not working', 'Todo', ?, ?)
        """,
            args=[timestamp, timestamp],
        )

        print("✓ Bug issue created")
        print()

        # Run verifier again - should pass now
        print("Running verifier again after creating the issue...")
        result = await task.verifier(
            env, project_key="SCRUM", issue_title="Login button not working"
        )
        print(f"  Final check result: {result}")
        print(
            f"  Task {'completed successfully' if result == TASK_SUCCESSFUL_SCORE else 'failed'}!"
        )
        print()

        # Test remote execution after issue creation
        print("Testing remote verifier execution after issue creation...")
        try:
            remote_result = await task.verifier.remote(
                env, project_key="SCRUM", issue_title="Login button not working"
            )
            print(f"  ✓ Remote check result: {remote_result}")
            print(
                f"  ✓ Remote execution {'matches' if remote_result == result else 'differs from'} local result"
            )
            print(
                f"  ✓ Task {'completed successfully' if remote_result == TASK_SUCCESSFUL_SCORE else 'failed'} (remote check)!"
            )
        except Exception as e:
            print(f"  ✗ Remote execution failed: {e}")
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
