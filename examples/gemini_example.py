import os
import json
import argparse
from typing import List, Dict, Any, Optional, Tuple, TypedDict
from pathlib import Path
from google import genai
from google.genai import types
import fleet as flt
from dotenv import load_dotenv
import base64
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

# Initialize Gemini client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = "gemini-2.5-pro"


class Problem(TypedDict):
    id: str
    problem: str
    category: str
    difficulty: str
    verifier_func: str


class GeminiAgent:
    def __init__(
        self,
        browser: flt.FleetPlaywrightWrapper,
        model: str = MODEL,
        print_steps: bool = True,
        debug: bool = False,
    ):
        self.browser = browser
        self.model = model
        self.print_steps = print_steps
        self.debug = debug
        self.conversation_history = []

    def debug_print(self, *args):
        if self.debug:
            print("[DEBUG]", *args)

    def take_screenshot(self) -> str:
        return self.browser.screenshot()

    def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        action_type = action.get("type")
        params = action.get("parameters", {})

        if self.print_steps:
            print(f"Action: {action_type}({params})")

        try:
            if action_type == "click":
                self.browser.click(
                    x=params.get("x", params.get("coordinate", [0, 0])[0]),
                    y=params.get("y", params.get("coordinate", [0, 0])[1]),
                )
            elif action_type == "type":
                self.browser.type(text=params.get("text", ""))
            elif action_type == "key":
                self.browser.key(key=params.get("key", ""))
            elif action_type == "scroll":
                self.browser.scroll(
                    x=params.get("x", params.get("coordinate", [0, 0])[0]),
                    y=params.get("y", params.get("coordinate", [0, 0])[1]),
                    direction=params.get("direction", "down"),
                    amount=params.get("amount", 5),
                )
            elif action_type == "wait":
                time.sleep(params.get("seconds", 1))
            elif action_type == "navigate":
                # For navigation, we might need to handle this differently
                url = params.get("url", "")
                if url:
                    self.browser.page.goto(url)
            else:
                return {
                    "success": False,
                    "error": f"Unknown action type: {action_type}",
                }

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_prompt_with_screenshot(
        self, task: str, screenshot_b64: str
    ) -> List[Any]:
        prompt_text = (
            "You are an AI agent that can interact with web browsers. "
            f"Your task is to: {task}\n\n"
            "You can see the current state of the browser in the screenshot provided.\n\n"
            "You can perform the following actions:\n"
            '- click: Click at specific coordinates {"type": "click", "parameters": {"x": x, "y": y}}\n'
            '- type: Type text {"type": "type", "parameters": {"text": "text to type"}}\n'
            '- key: Press a key {"type": "key", "parameters": {"key": "Enter"}}\n'
            '- scroll: Scroll the page {"type": "scroll", "parameters": {"x": x, "y": y, "direction": "down", "amount": 5}}\n'
            '- wait: Wait for a number of seconds {"type": "wait", "parameters": {"seconds": 1}}\n\n'
            "Analyze the screenshot and decide what action to take next. Respond with a JSON object containing:\n"
            '- "reasoning": Your analysis of the current state and what needs to be done\n'
            '- "action": The action to perform (as described above)\n'
            '- "completed": true if the task is complete, false otherwise\n\n'
            "Example response:\n"
            "{\n"
            '  "reasoning": "I can see a login form. I need to click on the username field and enter credentials.",\n'
            '  "action": {"type": "click", "parameters": {"x": 300, "y": 200}},\n'
            '  "completed": false\n'
            "}"
        )

        return [
            prompt_text,
            types.Part.from_bytes(
                data=base64.b64decode(screenshot_b64), mime_type="image/png"
            ),
        ]

    def solve_task(self, task: str, max_steps: int = 20) -> Tuple[bool, str]:
        steps = 0

        try:
            while steps < max_steps:
                steps += 1

                # Take screenshot
                screenshot = self.take_screenshot()

                # Create prompt with current state
                prompt_parts = self.create_prompt_with_screenshot(task, screenshot)

                # Get Gemini's response
                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt_parts,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.7,
                    ),
                )

                # Parse response
                try:
                    result = json.loads(response.text)
                    self.debug_print(f"Step {steps}: {result}")

                    if self.print_steps:
                        print(
                            f"Step {steps}: {result.get('reasoning', 'No reasoning provided')}"
                        )

                    # Check if task is completed
                    if result.get("completed", False):
                        return True, "Task completed successfully"

                    # Execute the action
                    if "action" in result:
                        action_result = self.execute_action(result["action"])
                        if not action_result["success"]:
                            self.debug_print(
                                f"Action failed: {action_result.get('error')}"
                            )

                    # Small delay to let the page update
                    time.sleep(0.5)

                except json.JSONDecodeError as e:
                    self.debug_print(f"Failed to parse Gemini response: {e}")
                    self.debug_print(f"Response text: {response.text}")
                    continue

            return False, f"Max steps ({max_steps}) reached without completing the task"

        except Exception as e:
            return False, f"Error during task execution: {str(e)}"


def extract_function_name(function_str: str) -> str:
    match = re.search(r"(?:async\s+)?def\s+(\w+)\s*\(", function_str)
    if match:
        return match.group(1)
    raise ValueError(f"No function name found in {function_str}")


def evaluate_problem(
    problem: Problem,
    problem_idx: int,
    total_problems: int,
    env_key: str,
    max_steps: int = 20,
) -> Tuple[str, bool, Optional[str]]:
    env = None
    browser = None

    try:
        # Create environment
        env = flt.env.make(env_key)
        print(
            f"[Problem {problem_idx + 1}/{total_problems}] Created environment for {problem['id']}: {env.urls.app}"
        )

        # Create browser wrapper
        browser = flt.FleetPlaywrightWrapper(env)
        browser.start()

        # Create agent
        agent = GeminiAgent(browser, print_steps=True, debug=False)

        # Solve the problem
        print(
            f"[Problem {problem_idx + 1}/{total_problems}] Solving {problem['id']}..."
        )
        success, message = agent.solve_task(problem["problem"], max_steps=max_steps)

        if not success:
            print(
                f"[Problem {problem_idx + 1}/{total_problems}] Failed to solve: {message}"
            )
            return problem["id"], False, message

        # Verify the solution
        function_name = extract_function_name(problem["verifier_func"])
        print(
            f"[Problem {problem_idx + 1}/{total_problems}] Verifying {function_name} ({problem['id']})..."
        )
        response = env.verify_raw(problem["verifier_func"], function_name)

        print(
            f"[Problem {problem_idx + 1}/{total_problems}] Result for {problem['id']}: {'✓' if response.success else '✗'}"
        )

        return problem["id"], response.success, None

    except Exception as e:
        print(
            f"[Problem {problem_idx + 1}/{total_problems}] Fatal error processing {problem['id']}: {e}"
        )
        return problem["id"], False, str(e)
    finally:
        # Clean up
        if browser:
            browser.close()
        if env:
            env.close()


def interactive_mode():
    # Create a Fleet environment instance
    instance = flt.env.make("hubspot")

    # Create the browser wrapper
    browser = flt.FleetPlaywrightWrapper(instance)
    browser.start()

    try:
        agent = GeminiAgent(browser, print_steps=True, debug=False)

        print("Gemini Agent Interactive Mode")
        print("Type your task or 'quit' to exit")
        print("-" * 60)

        while True:
            try:
                user_input = input("\n> ")
                if user_input.lower() in ["quit", "exit", "q"]:
                    break

                success, message = agent.solve_task(user_input)
                print(f"\nResult: {'Success' if success else 'Failed'} - {message}")

            except KeyboardInterrupt:
                print("\nShutting down...")
                break
            except Exception as e:
                print(f"Error: {e}")

    finally:
        browser.close()
        instance.close()


def evaluate_from_json(json_file: str, max_concurrent: int = 3, max_steps: int = 20):
    file_path = Path(json_file)
    if not file_path.exists():
        raise FileNotFoundError(f"Error: File '{json_file}' not found")

    with open(json_file, "r") as f:
        data = json.load(f)
    problems: List[Problem] = data["problems"]

    print(f"Loaded {len(problems)} problems from '{json_file}'")
    print(f"Running with max {max_concurrent} concurrent tasks")
    print("-" * 60)

    # Process problems with thread pool for concurrency
    results = []
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        # Submit all tasks
        future_to_problem = {
            executor.submit(
                evaluate_problem, problem, idx, len(problems), "fira:v1.3.1", max_steps
            ): (problem, idx)
            for idx, problem in enumerate(problems)
        }

        # Collect results as they complete
        for future in as_completed(future_to_problem):
            result = future.result()
            results.append(result)

    # Display results
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


def main():
    parser = argparse.ArgumentParser(description="Gemini Agent for Fleet SDK")
    parser.add_argument(
        "--eval", type=str, help="Path to JSON file with problems to evaluate"
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=3,
        help="Maximum number of concurrent evaluations (default: 3)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Maximum steps per problem (default: 20)",
    )
    parser.add_argument(
        "--interactive", action="store_true", help="Run in interactive mode"
    )

    args = parser.parse_args()

    if args.eval:
        evaluate_from_json(args.eval, args.max_concurrent, args.max_steps)
    elif args.interactive:
        interactive_mode()
    else:
        raise ValueError("No arguments provided")


if __name__ == "__main__":
    main()
