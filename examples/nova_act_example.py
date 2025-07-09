"""
Nova Act + Fleet SDK Integration Example

This example demonstrates how to use Amazon Nova Act (an AI-powered browser automation SDK)
with Fleet's browser instances. Nova Act can navigate websites, fill forms, and extract data
using natural language commands.

Requirements:
1. Fleet SDK: pip install fleet-python
2. Nova Act SDK: pip install nova-act
3. Playwright Chrome: playwright install chrome
4. Environment variables:
   - FLEET_API_KEY: Your Fleet API key
   - NOVA_ACT_API_KEY: Your Nova Act API key (get from https://nova.amazon.com/act)

Note: Nova Act is currently only available in the US as a research preview.

Usage:
    export FLEET_API_KEY=your_fleet_key
    export NOVA_ACT_API_KEY=your_nova_act_key
    python examples/nova_act_example.py

Important: Nova Act typically creates its own browser instance. Integration with
Fleet's CDP endpoint may not be fully supported in the current version.
"""

import asyncio
import fleet as flt
import nova_act
import os
from concurrent.futures import ThreadPoolExecutor


def test_nova_act_sync():
    """Test Nova Act in a synchronous context (outside asyncio loop)."""
    print("\n🧪 Testing Nova Act independently...")
    try:
        with nova_act.NovaAct(
            headless=False,
            starting_page="https://example.com"
        ) as nova:
            print("✅ Nova Act initialized successfully!")
            result = nova.act("What is the main heading on this page?")
            print(f"Test result: {result}")
            return True
    except Exception as e:
        print(f"❌ Nova Act test failed: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def run_nova_act_with_fleet_data(fleet_app_url):
    """Run Nova Act examples using Fleet's app URL."""
    print("\n🤖 Starting Nova Act with Fleet app URL...")
    
    try:
        with nova_act.NovaAct(
            headless=False,
            starting_page=fleet_app_url,
            cdp_endpoint_url="wss://05bd8217.fleetai.com/cdp/devtools/browser/288477c8-2a6d-4e66-b8de-29bc3033c7a2"
        ) as nova:
            print("✅ Nova Act started successfully!")
            run_nova_examples(nova)
            
    except Exception as e:
        print(f"❌ Error during Nova Act operations: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()


def run_nova_examples(nova):
    """Run Nova Act examples in a separate function."""
    # Example 1: Navigate and interact with a website
    print("\n📝 Example 1: Basic navigation and interaction")
    nova.act("Navigate to https://example.com")

    # Extract page title
    result = nova.act(
        "What is the title of this page?",
        schema={"type": "object", "properties": {"title": {"type": "string"}}},
    )
    if result.matches_schema:
        print(f"Page title: {result.parsed_response.get('title')}")

    # Example 2: More complex interaction
    print("\n📝 Example 2: Search on a website")
    nova.act("Navigate to https://www.python.org")
    nova.act("Search for 'asyncio' in the search box")

    # Example 3: Extract structured data
    print("\n📝 Example 3: Extract structured information")
    result = nova.act(
        "Find the first 3 search results and return their titles",
        schema={
            "type": "object",
            "properties": {
                "results": {"type": "array", "items": {"type": "string"}}
            },
        },
    )
    if result.matches_schema:
        results = result.parsed_response.get("results", [])
        print("Search results:")
        for i, title in enumerate(results, 1):
            print(f"  {i}. {title}")

    # Example 4: Fill out a form
    print("\n📝 Example 4: Form interaction")
    nova.act("Navigate to https://httpbin.org/forms/post")
    nova.act("Fill the customer name field with 'John Doe'")
    nova.act("Select 'Medium' for the size")
    nova.act("Check the 'Bacon' topping")

    # You can also use nova_act's ability to take screenshots
    print("\n📸 Taking screenshot...")
    nova.act("Take a screenshot of the current page")


async def main():
    """Main async function for Fleet operations."""
    
    # Check for Nova Act API key
    nova_api_key = os.getenv("NOVA_ACT_API_KEY")
    if not nova_api_key:
        print("❌ NOVA_ACT_API_KEY environment variable not set!")
        print("Please set it with: export NOVA_ACT_API_KEY=your_api_key")
        return
    else:
        print(f"✅ Nova Act API key found: {nova_api_key[:8]}...{nova_api_key[-4:]}")

    # Test Nova Act outside of asyncio loop
    # with ThreadPoolExecutor() as executor:
    #     nova_test_future = executor.submit(test_nova_act_sync)
    #     nova_works = nova_test_future.result()
        
    # if not nova_works:
    #     print("\nNova Act is not working properly. Please check:")
    #     print("1. You have a valid NOVA_ACT_API_KEY")
    #     print("2. You have installed nova-act: pip install nova-act")
    #     print("3. You have playwright installed: playwright install chrome")
    #     return

    # Initialize Fleet client
    fleet = flt.AsyncFleet()
    print("\n🚀 Initializing Fleet client...")

    instance = await fleet.instance("05bd8217")

    try:
        # Reset the environment to ensure clean state
        # print("🔄 Resetting environment...")
        # await instance.env.reset()

        # Get browser resource from Fleet
        browser = await instance.env.browser("cdp").describe()
        print(f"🌐 CDP URL: {browser.url}")
        print(f"🔧 DevTools URL: {browser.devtools_url}")

        # Run Nova Act in a separate thread to avoid asyncio conflicts
        with ThreadPoolExecutor() as executor:
            nova_future = executor.submit(run_nova_act_with_fleet_data, instance.urls.app)
            nova_future.result()  # Wait for Nova Act to complete

    except Exception as e:
        print(f"❌ Error in main flow: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Script interrupted by user")
        print("Nova Act browser may still be running in the background.")
    except Exception as e:
        print(f"\n❌ Unexpected error: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
