import os
import json
import argparse
from typing import List, Dict, Any, Optional, Tuple, TypedDict
from pathlib import Path
from google import genai
from google.genai import types
import fleet
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
        browser: fleet.FleetPlaywrightWrapper,
        model: str = MODEL,
        print_steps: bool = True,
        debug: bool = False,
    ):
        self.browser = browser
        self.model = model
        self.print_steps = print_steps
        self.debug = debug
        self.conversation_history = []
        self.last_action = None  # Track the last action performed

    @property
    def page(self):
        """Access the underlying Playwright page object."""
        return self.browser._page if hasattr(self.browser, "_page") else None

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
                # Small delay to ensure click is registered and element is focused
                time.sleep(0.2)
                self.last_action = {"type": "click", "target": params}
            elif action_type == "type":
                self.browser.type(text=params.get("text", ""))
                self.last_action = {"type": "type", "text": params.get("text", "")}
            elif action_type == "key":
                # FleetPlaywrightWrapper expects keypress with a list of keys
                key = params.get("key", "")
                self.browser.keypress([key])
                self.last_action = {"type": "key", "key": key}
            elif action_type == "scroll":
                # FleetPlaywrightWrapper expects scroll(x, y, scroll_x, scroll_y)
                x = params.get("x", params.get("coordinate", [0, 0])[0])
                y = params.get("y", params.get("coordinate", [0, 0])[1])
                direction = params.get("direction", "down")
                amount = params.get("amount", 5)

                # Convert direction and amount to scroll_x and scroll_y
                scroll_x = 0
                scroll_y = 0
                if direction == "down":
                    scroll_y = amount * 100
                elif direction == "up":
                    scroll_y = -amount * 100
                elif direction == "right":
                    scroll_x = amount * 100
                elif direction == "left":
                    scroll_x = -amount * 100

                self.browser.scroll(x=x, y=y, scroll_x=scroll_x, scroll_y=scroll_y)
                self.last_action = {"type": "scroll"}
            elif action_type == "wait":
                time.sleep(params.get("seconds", 1))
                self.last_action = {"type": "wait"}
            elif action_type == "navigate":
                # Use the browser's goto method
                url = params.get("url", "")
                if url:
                    self.browser.goto(url)
                self.last_action = {"type": "navigate", "url": url}
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
        # Add context about last action
        last_action_context = ""
        if self.last_action:
            if self.last_action["type"] == "click":
                last_action_context = f"\n\nIMPORTANT: You just clicked at coordinates {self.last_action['target']}. If you clicked on a text input field, search bar, or any editable element, you MUST now use the 'type' action to enter text. Do not click the same element again."
            elif self.last_action["type"] == "type":
                last_action_context = f"\n\nYou just typed: '{self.last_action['text']}'. You may now need to press Enter or click a button to submit."

        prompt_text = (
            "You are an AI agent that can interact with web browsers. "
            f"Your task is to: {task}\n\n"
            "You can see the current state of the browser in the screenshot provided."
            f"{last_action_context}\n\n"
            "You can perform the following actions:\n"
            '- click: Click at specific coordinates {"type": "click", "parameters": {"x": x, "y": y}}\n'
            '- type: Type text into the currently focused element {"type": "type", "parameters": {"text": "text to type"}}\n'
            '- key: Press a special key {"type": "key", "parameters": {"key": "Enter"}} (e.g., "Enter", "Tab", "Escape")\n'
            '- scroll: Scroll the page {"type": "scroll", "parameters": {"x": x, "y": y, "direction": "down", "amount": 5}} (direction: up/down/left/right)\n'
            '- wait: Wait for a number of seconds {"type": "wait", "parameters": {"seconds": 1}}\n\n'
            "CRITICAL RULES:\n"
            "1. After clicking on ANY text input, search bar, or form field, you MUST type in the next step\n"
            "2. Never click the same element twice in a row\n"
            "3. If you mention searching for something in your reasoning, you must actually type the search query\n"
            "4. Common workflow: click search bar → type query → press Enter\n\n"
            "Analyze the screenshot and decide what action to take next. Respond with a JSON object containing:\n"
            '- "reasoning": Your analysis of the current state and what needs to be done\n'
            '- "action": The action to perform (as described above)\n'
            '- "completed": true if the task is complete, false otherwise\n\n'
            "Example responses:\n"
            "{\n"
            '  "reasoning": "I can see a search bar at the top. I need to click on it first to focus it.",\n'
            '  "action": {"type": "click", "parameters": {"x": 450, "y": 30}},\n'
            '  "completed": false\n'
            "}\n\n"
            "{\n"
            '  "reasoning": "I just clicked on the search bar and it should now be focused. I need to type my search query for PHI encryption ticket.",\n'
            '  "action": {"type": "type", "parameters": {"text": "PHI encryption"}},\n'
            '  "completed": false\n'
            "}\n\n"
            "{\n"
            '  "reasoning": "I typed the search query. Now I need to press Enter to execute the search.",\n'
            '  "action": {"type": "key", "parameters": {"key": "Enter"}},\n'
            '  "completed": false\n'
            "}"
        )

        return [
            prompt_text,
            types.Part.from_bytes(
                data=base64.b64decode(screenshot_b64), mime_type="image/png"
            ),
        ]

    def solve_task(self, task: str, max_steps: int = 30) -> Tuple[bool, str]:
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
                        temperature=0.1,  # Lower temperature for more deterministic behavior
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

                    # Debug: Print the full action if in debug mode
                    if self.debug and "action" in result:
                        print(f"[DEBUG] Full action: {result['action']}")

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
                    else:
                        print(f"[WARNING] No action in response: {result}")

                    # Small delay to let the page update
                    time.sleep(0.5)

                except json.JSONDecodeError as e:
                    self.debug_print(f"Failed to parse Gemini response: {e}")
                    self.debug_print(f"Response text: {response.text}")
                    # Try to extract any useful information from the response
                    print(
                        f"[ERROR] Invalid JSON response from Gemini: {response.text[:200]}..."
                    )
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
    max_steps: int = 30,
) -> Tuple[str, bool, Optional[str]]:
    env = None
    browser = None

    try:
        # Create environment
        env = fleet.env.make(env_key)
        print(
            f"[Problem {problem_idx + 1}/{total_problems}] Created environment for {problem['id']}: {env.urls.app}"
        )

        # Create browser wrapper
        browser = fleet.FleetPlaywrightWrapper(env)
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
            # return problem["id"], False, message

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
    instance = fleet.env.make("hubspot")

    # Create the browser wrapper
    browser = fleet.FleetPlaywrightWrapper(instance)
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


def evaluate_from_json(json_file: str, max_concurrent: int = 3, max_steps: int = 30):
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
        default=30,
        help="Maximum steps per problem (default: 30)",
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
