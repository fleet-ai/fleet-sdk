#!/usr/bin/env python3
"""
Interactive Browser Snapshot/Resume Example

This script:
1. Creates an environment and browser
2. Lets you interact with it manually
3. Takes a snapshot when you type 'close'
4. Resumes from the snapshot with a new environment
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fleet import Fleet

def main():
    # Initialize Fleet client
    api_key = os.getenv("FLEET_API_KEY")
    if not api_key:
        print("Error: FLEET_API_KEY environment variable not set")
        sys.exit(1)
    
    fleet = Fleet(api_key=api_key)
    
    # Initialize environment variables
    env = None
    new_env = None
    
    try:
        # Step 1: Create environment and browser
        print("🚀 Creating new environment...")
        env_key = "fira:v1.3.2"  
        
        env = fleet.make(env_key)
        print(f"✅ Environment created: {env.instance_id}")
        print(f"📝 Session ID: {env.session_id}")
        
        # Start browser
        print("\n🌐 Starting browser...")
        browser = env.browser()
        browser.start(width=1920, height=1080)
        
        # Get browser URLs with session ID for automatic logging
        cdp_page_url = browser.cdp_page_url()
        cdp_browser_url = browser.cdp_browser_url()
        devtools_url = browser.devtools_url()
        
        print(f"✅ Browser started!")
        print(f"🔗 CDP Page URL: {cdp_page_url}")
        print(f"🔗 CDP Browser URL: {cdp_browser_url}")
        print(f"🔗 DevTools URL: {devtools_url}")
        
        # Show connection info for debugging
        conn_info = browser.get_connection_info()
        print(f"📊 Logging enabled: {conn_info['logging_enabled']}")
        if conn_info['logging_enabled']:
            print(f"📝 All CDP actions will be automatically logged to session: {env.session_id}")
        
        # Step 2: Wait for user interaction
        print("\n" + "="*60)
        print("🎮 INTERACTIVE MODE")
        print("="*60)
        print("You can now interact with the browser manually.")
        print("Open the DevTools URL in Chrome to see and control the browser.")
        print("\nType 'close' and press Enter when you're done to save a snapshot.")
        print("="*60 + "\n")
        
        while True:
            user_input = input(">>> ").strip().lower()
            
            if user_input == "close":
                break
            elif user_input == "status":
                print(f"Environment: {env.instance_id}")
                print(f"Session: {env.session_id}")
            else:
                print("Type 'close' to save snapshot and exit, or 'status' to see current info")
        
        # Step 3: Take snapshot
        print("\n📸 Taking snapshot...")
        snapshot = env.get_snapshot(browser)
        
        # Save snapshot to file
        snapshot_file = f"snapshot_{env.session_id}_{int(datetime.now().timestamp())}.json"
        with open(snapshot_file, "w") as f:
            json.dump(snapshot.model_dump(), f, indent=2)
        
        print(f"✅ Snapshot saved to: {snapshot_file}")
        print(f"   - Tool logs: {len(snapshot.tool_logs)} entries")
        print(f"   - Action logs: {len(snapshot.action_logs)} entries")
        print(f"   - Page URL: {snapshot.page_url}")
        print(f"   - Viewport: {snapshot.viewport_size}")
        
        # Close original environment
        print("\n🏁 Closing original environment...")
        env.close()
        env = None  # Mark as closed
        
        # Step 4: Resume from snapshot
        print("\n" + "="*60)
        print("🔄 RESUMING FROM SNAPSHOT")
        print("="*60)
        
        input("\nPress Enter to resume from snapshot...")
        
        print("\n🚀 Creating new environment from snapshot...")
        new_env, validation = fleet.resume(
            snapshot,
            validate=True,
            playback_speed=2.0  # Replay at 2x speed
        )
        
        print(f"✅ Environment resumed: {new_env.instance_id}")
        print(f"📝 New session ID: {new_env.session_id}")
        
        # Show validation results
        print(f"\n📊 Validation Results:")
        print(f"   - Success: {validation.success}")
        print(f"   - Page match: {validation.page_match}")
        print(f"   - Action log match: {validation.action_log_match}")
        
        if validation.discrepancies:
            print(f"   - Discrepancies ({len(validation.discrepancies)}):")
            for disc in validation.discrepancies[:5]:  # Show first 5
                print(f"     • {disc}")
            if len(validation.discrepancies) > 5:
                print(f"     • ... and {len(validation.discrepancies) - 5} more")
        
        # Get new browser reference
        new_browser = new_env.browser()
        print(f"\n🌐 New browser ready!")
        print(f"🔗 CDP Page URL: {new_browser.cdp_page_url()}")
        print(f"🔗 DevTools URL: {new_browser.devtools_url()}")
        print(f"📝 Resume session logging to: {new_env.session_id}")
        
        # Step 5: Keep new environment open for inspection
        print("\n" + "="*60)
        print("🎮 RESUMED ENVIRONMENT READY")
        print("="*60)
        print("The resumed environment is now ready. You can inspect it to verify")
        print("it matches your original state.")
        print("\nType 'done' when finished to close the resumed environment.")
        print("="*60 + "\n")
        
        while True:
            user_input = input(">>> ").strip().lower()
            
            if user_input == "done":
                break
            elif user_input == "status":
                print(f"Environment: {new_env.instance_id}")
                print(f"Session: {new_env.session_id}")
            else:
                print("Type 'done' to close the environment, or 'status' to see current info")
        
        # Clean up
        print("\n🏁 Closing resumed environment...")
        new_env.close()
        new_env = None  # Mark as closed
        print("✅ All done!")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        # Always clean up environments
        if env is not None:
            try:
                print("\n🧹 Cleaning up original environment...")
                env.close()
                print("✅ Original environment closed")
            except Exception as e:
                print(f"⚠️  Failed to close original environment: {e}")
        
        if new_env is not None:
            try:
                print("\n🧹 Cleaning up resumed environment...")
                new_env.close()
                print("✅ Resumed environment closed")
            except Exception as e:
                print(f"⚠️  Failed to close resumed environment: {e}")


if __name__ == "__main__":
    main()