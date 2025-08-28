import re
import asyncio
import argparse
import json
from typing import TypedDict, List, Optional, Tuple
from pathlib import Path
import fleet
from nova_act import NovaAct, ActResult
from dotenv import load_dotenv

load_dotenv()


MAX_STEPS = 30
MAX_CONCURRENT_TASKS = 5  # Limit concurrent tasks to avoid overwhelming the system


class Problem(TypedDict):
    id: str
    problem: str
    category: str
    difficulty: str
    verifier_func: str


def extract_function_name(function_str: str) -> str | None:
    match = re.search(r"(?:async\s+)?def\s+(\w+)\s*\(", function_str)
    if match:
        return match.group(1)
    raise ValueError(f"No function name found in {function_str}")


async def process_problem(
    problem: Problem, problem_idx: int, total_problems: int, env_key: str
) -> Tuple[str, bool, Optional[str]]:
    env = None
    try:
        # Create a new environment instance for this problem
        env = await fleet.env.make_async(env_key)
        print(
            f"[Problem {problem_idx + 1}/{total_problems}] Created environment for {problem['id']}: {env.urls.app}"
        )

        # Run NovaAct in a thread (since it's synchronous)
        def run_nova() -> ActResult:
            with NovaAct(starting_page=env.urls.app, headless=True) as nova:
                return nova.act(problem["problem"], max_steps=MAX_STEPS)

        try:
            print(
                f"[Problem {problem_idx + 1}/{total_problems}] Solving {problem['id']}..."
            )
            await asyncio.to_thread(run_nova)
        except Exception as e:
            print(
                f"[Problem {problem_idx + 1}/{total_problems}] Error during solving {problem['id']}: {e}"
            )
            error_msg = str(e)
        else:
            error_msg = None

        # Verify the solution
        function_name = extract_function_name(problem["verifier_func"])
        print(
            f"[Problem {problem_idx + 1}/{total_problems}] Verifying {function_name} ({problem['id']})..."
        )
        response = await env.verify_raw(problem["verifier_func"], function_name)

        print(
            f"[Problem {problem_idx + 1}/{total_problems}] Result for {problem['id']}: {'✓' if response.success else '✗'}"
        )

        return problem["id"], response.success, error_msg

    except Exception as e:
        print(
            f"[Problem {problem_idx + 1}/{total_problems}] Fatal error processing {problem['id']}: {e}"
        )
        return problem["id"], False, str(e)
    finally:
        # Clean up the environment
        if env:
            try:
                await env.close()
                print(
                    f"[Problem {problem_idx + 1}/{total_problems}] Closed environment for {problem['id']}"
                )
            except Exception as e:
                print(
                    f"[Problem {problem_idx + 1}/{total_problems}] Error closing environment for {problem['id']}: {e}"
                )


async def main():
    parser = argparse.ArgumentParser(
        description="Load and display Jira problems from JSON file"
    )
    parser.add_argument(
        "json_file", type=str, help="Path to the JSON file containing problems"
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=MAX_CONCURRENT_TASKS,
        help=f"Maximum number of concurrent tasks (default: {MAX_CONCURRENT_TASKS})",
    )
    args = parser.parse_args()

    file_path = Path(args.json_file)
    if not file_path.exists():
        raise FileNotFoundError(f"Error: File '{args.json_file}' not found")

    try:
        with open(args.json_file, "r") as f:
            data = json.load(f)
        problems: List[Problem] = data["problems"]

        print(f"Loaded {len(problems)} problems from '{args.json_file}'")
        print(f"Running with max {args.max_concurrent} concurrent tasks")
        print("-" * 60)

        # Create a semaphore to limit concurrent tasks
        semaphore = asyncio.Semaphore(args.max_concurrent)

        async def process_with_semaphore(
            problem: Problem, idx: int
        ) -> Tuple[str, bool, Optional[str]]:
            async with semaphore:
                return await process_problem(problem, idx, len(problems), "fira:v1.2.7")

        # Process all problems concurrently (with semaphore limiting)
        tasks = [
            process_with_semaphore(problem, i) for i, problem in enumerate(problems)
        ]

        results = await asyncio.gather(*tasks)

        # Count successes and display summary
        print("\n" + "=" * 60)
        print("EVALUATION RESULTS")
        print("=" * 60)

        successes = 0
        for problem_id, success, error in results:
            status = "✓ PASS" if success else "✗ FAIL"
            print(f"{status} | {problem_id}")
            if error and not success:
                print(f"      └─ Error: {error}")
            if success:
                successes += 1

        print("-" * 60)
        print(f"Total problems: {len(problems)}")
        print(f"Successes: {successes}")
        print(f"Failures: {len(problems) - successes}")
        print(f"Success rate: {successes / len(problems):.2%}")

    except Exception as e:
        print(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
