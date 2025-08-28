from openai import OpenAI
import fleet
from dotenv import load_dotenv

load_dotenv()

client = OpenAI()


def main():
    instance = fleet.env.make("hubspot")

    browser = fleet.FleetPlaywrightWrapper(instance)
    browser.start()

    try:
        width, height = browser.get_dimensions()
        tools = [
            {
                "type": "computer-preview",
                "display_width": width,
                "display_height": height,
                "environment": browser.get_environment(),
            }
        ]

        response = client.responses.create(
            model="computer-use-preview",
            input=[
                {
                    "role": "developer",
                    "content": "Create a HubSpot deal",
                }
            ],
            tools=tools,
            truncation="auto",
        )

        if len(response.output) != 0:
            if response.output[0].type == "message":
                print(response.output[0].content[0].text)

            if response.output[0].type == "computer_call":
                action = response.output[0].action
                if action.type == "screenshot":
                    screenshot_base64 = browser.screenshot()
                    result = {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{screenshot_base64}",
                        "current_url": browser.get_current_url(),
                    }
                else:
                    result = browser.execute_computer_action(action)

                print("Computer action result:")
                print(result)
    finally:
        browser.close()
        instance.close()


if __name__ == "__main__":
    main()
