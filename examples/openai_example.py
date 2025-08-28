from openai import OpenAI
import fleet
import json
from typing import Callable
from dotenv import load_dotenv

load_dotenv()


client = OpenAI()


def sanitize_message(msg: dict) -> dict:
    """Return a copy of the message with image_url omitted for computer_call_output messages."""
    if msg.get("type") == "computer_call_output":
        output = msg.get("output", {})
        if isinstance(output, dict):
            sanitized = msg.copy()
            sanitized["output"] = {**output, "image_url": "[omitted]"}
            return sanitized
    return msg


class Agent:
    def __init__(
        self,
        browser,
        model="computer-use-preview",
        tools: list[dict] = [],
        acknowledge_safety_check_callback: Callable = lambda: False,
    ):
        self.model = model
        self.computer = browser
        self.tools = tools
        self.print_steps = True
        self.debug = False
        self.show_images = False
        self.acknowledge_safety_check_callback = acknowledge_safety_check_callback

        if browser:
            dimensions = browser.get_dimensions()
            self.tools += [
                {
                    "type": "computer-preview",
                    "display_width": dimensions[0],
                    "display_height": dimensions[1],
                    "environment": browser.get_environment(),
                },
            ]

    def debug_print(self, *args):
        if self.debug:
            print(*args)

    def handle_item(self, item):
        """Handle each item; may cause a computer action + screenshot."""
        if self.debug:
            print(f"Handling item of type: {item.get('type')}")

        if item["type"] == "message":
            if self.print_steps:
                print(item["content"][0]["text"])

        if item["type"] == "function_call":
            name, args = item["name"], json.loads(item["arguments"])
            if self.print_steps:
                print(f"{name}({args})")

            if hasattr(self.computer, name):  # if function exists on computer, call it
                method = getattr(self.computer, name)
                method(**args)
            return [
                {
                    "type": "function_call_output",
                    "call_id": item["call_id"],
                    "output": "success",  # hard-coded output for demo
                }
            ]

        if item["type"] == "computer_call":
            action = item["action"]
            action_type = action["type"]
            action_args = {k: v for k, v in action.items() if k != "type"}
            if self.print_steps:
                print(f"{action_type}({action_args})")

            method = getattr(self.computer, action_type)
            method(**action_args)

            screenshot_base64 = self.computer.screenshot()

            # if user doesn't ack all safety checks exit with error
            pending_checks = item.get("pending_safety_checks", [])
            for check in pending_checks:
                message = check["message"]
                if not self.acknowledge_safety_check_callback(message):
                    raise ValueError(
                        f"Safety check failed: {message}. Cannot continue with unacknowledged safety checks."
                    )

            call_output = {
                "type": "computer_call_output",
                "call_id": item["call_id"],
                "acknowledged_safety_checks": pending_checks,
                "output": {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{screenshot_base64}",
                },
            }

            # additional URL safety checks for browser environments
            if self.computer.get_environment() == "browser":
                current_url = self.computer.get_current_url()
                call_output["output"]["current_url"] = current_url

            return [call_output]
        return []

    def run_full_turn(
        self, input_items, print_steps=True, debug=False, show_images=False
    ):
        self.print_steps = print_steps
        self.debug = debug
        self.show_images = show_images
        new_items = []

        # keep looping until we get a final response
        while new_items[-1].get("role") != "assistant" if new_items else True:
            self.debug_print([sanitize_message(msg) for msg in input_items + new_items])

            # The Responses API rejects unknown keys (e.g. `status`, `encrypted_content`).
            # Strip them from every item before sending.
            def _clean_item(msg: dict) -> dict:
                unwanted_keys = {"status", "encrypted_content"}
                return {k: v for k, v in msg.items() if k not in unwanted_keys}

            clean_input = [_clean_item(m) for m in (input_items + new_items)]

            response = client.responses.create(
                model=self.model,
                input=clean_input,
                tools=self.tools,
                truncation="auto",
            )

            # The OpenAI SDK returns a Pydantic model object, not a plain dict.
            # Convert it to a standard Python dict so the rest of the code can
            # remain unchanged from the previous implementation.
            response_dict = (
                response.model_dump()  # pydantic v2
                if hasattr(response, "model_dump")
                else (
                    response.to_dict_recursive()
                    if hasattr(response, "to_dict_recursive")
                    else dict(response)
                )
            )
            self.debug_print(response_dict)

            # Guard against missing/empty output in the response
            if not response_dict.get("output"):
                if self.debug:
                    print("Full response:", response_dict)
                if response_dict.get("error") is not None:
                    error_msg = response_dict["error"].get("message", "Unknown error")
                    raise ValueError(f"API Error: {error_msg}")
                else:
                    raise ValueError("No output from model")

            # Append each item from the model output to conversation history
            # in the exact order we received them, **without filtering** so that
            # required pairs such as reasoning → computer_call are preserved.
            for item in response_dict["output"]:
                # First, record the original item itself.
                new_items.append(item)

                # Next, perform any local side-effects (browser actions, etc.).
                handled_items = self.handle_item(item)

                # If the handler generated additional items (e.g. computer_call_output)
                # we append those *immediately* so the order remains:
                #   reasoning → computer_call → computer_call_output
                if handled_items:
                    new_items += handled_items

        return new_items


tools = []


def main():
    # Create a Fleet environment instance
    instance = fleet.env.make("hubspot")

    # Create the Playwright wrapper
    browser = fleet.FleetPlaywrightWrapper(instance)
    browser.start()

    try:
        agent = Agent(browser, model="computer-use-preview", tools=[])
        items = [
            {
                "role": "developer",
                "content": "You have access to a clone of Hubspot. You can use the computer to navigate the browser and perform actions.",
            }
        ]

        while True:
            try:
                user_input = input("> ")
                items.append({"role": "user", "content": user_input})
                output_items = agent.run_full_turn(
                    items, show_images=False, debug=False
                )
                items += output_items
            except (EOFError, KeyboardInterrupt):
                print("\nShutting down...")
                break
            except Exception as e:
                print(f"Error during interaction: {e}")
                # Continue the loop for other errors
    finally:
        browser.close()
        instance.close()


if __name__ == "__main__":
    main()
