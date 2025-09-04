#!/usr/bin/env python3
"""
Test CDP Logging Example

This script demonstrates the new automatic CDP logging functionality.
All CDP commands and events are now logged automatically at the proxy level.
"""

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
    env = None
    
    try:
        # Create environment
        print("🚀 Creating new environment...")
        env_key = "fira:v1.3.2"  # Replace with your actual environment key
        
        env = fleet.make(env_key)
        print(f"✅ Environment created: {env.instance_id}")
        print(f"📝 Session ID: {env.session_id}")
        
        # Start browser
        print("\n🌐 Starting browser with automatic CDP logging...")
        browser = env.browser()
        browser.start(width=1920, height=1080)
        
        # Show connection information
        conn_info = browser.get_connection_info()
        print("\n📊 Connection Information:")
        print(f"  Session ID: {conn_info['session_id']}")
        print(f"  CDP Page URL: {conn_info['cdp_page_url']}")
        print(f"  CDP Browser URL: {conn_info['cdp_browser_url']}")
        print(f"  Logging Enabled: {conn_info['logging_enabled']}")
        
        if conn_info['logging_enabled']:
            print(f"\n✅ All CDP actions will be automatically logged!")
            print(f"   - Connect any CDP client to: {conn_info['cdp_page_url']}")
            print(f"   - All commands and events will be logged to session: {env.session_id}")
            print(f"   - Use DevTools at: {conn_info['devtools_url']}")
        else:
            print(f"\n⚠️  Logging not enabled - no session ID available")
        
        print("\n" + "="*60)
        print("🎯 LOGGING TEST COMPLETE")
        print("="*60)
        print("The browser is ready with automatic CDP logging enabled.")
        print("Connect any CDP client or Playwright to the URLs above.")
        print("All actions will be automatically captured in the tool_log table.")
        print("\nPress Enter to close the environment...")
        print("="*60 + "\n")
        
        input()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        if env is not None:
            try:
                print("\n🧹 Cleaning up environment...")
                env.close()
                print("✅ Environment closed")
            except Exception as e:
                print(f"⚠️  Failed to close environment: {e}")

if __name__ == "__main__":
    main()