import re
import asyncio
import argparse
import json
from typing import TypedDict
from pathlib import Path
import fleet as flt


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


async def main():
    parser = argparse.ArgumentParser(
        description="Load and display Jira problems from JSON file"
    )
    parser.add_argument(
        "json_file", type=str, help="Path to the JSON file containing problems"
    )
    args = parser.parse_args()

    file_path = Path(args.json_file)
    if not file_path.exists():
        raise FileNotFoundError(f"Error: File '{args.json_file}' not found")

    env = await flt.env.make("fira")
    print(f"New Instance: {env.urls.app}")

    try:
        with open(args.json_file, "r") as f:
            data = json.load(f)
        problems = data["problems"]

        print(f"Loaded {len(problems)} problems from '{args.json_file}'")

        for problem in problems:
            function_name = extract_function_name(problem["verifier_func"])
            response = await env.verify_raw(problem["verifier_func"], function_name)
            print(response)
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())
