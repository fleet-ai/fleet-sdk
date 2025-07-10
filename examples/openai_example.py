import asyncio
from openai import AsyncOpenAI
import fleet as flt


async def main():
    # Create a Fleet environment instance
    instance = await flt.env.make("hubspot")
    
    # Create the Playwright wrapper
    browser = flt.FleetPlaywrightWrapper(instance)
    await browser.start()
    
    try:
        # Initialize OpenAI client
        client = AsyncOpenAI()
        
        # Take initial screenshot
        screenshot_base64 = await browser.screenshot()
        
        # Make a single API call
        response = await client.responses.create(
            model="computer-use-preview",
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Please click on the login button on this HubSpot page"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{screenshot_base64}"
                            }
                        }
                    ]
                }
            ],
            tools=[browser.openai_cua_tool],
            truncation="auto"
        )
        
        print("Response:", response)
        
        # Execute the computer action using the SDK method
        if response.output and response.output[0].type == "computer_call":
            result = await browser.execute_computer_action(response.output[0].action)
            print("Action result:", result)
    
    finally:
        # Clean up
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
