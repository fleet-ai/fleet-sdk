#!/usr/bin/env python3
"""
Example script demonstrating how to enable debug logging for Fleet SDK troubleshooting.

This example shows how to configure logging to debug issues with the make() function,
including long response times and JSON decode errors.
"""

import logging
import sys
import os
from fleet import Fleet

def setup_debug_logging():
    """Configure comprehensive debug logging for Fleet SDK troubleshooting."""
    
    # Create a console handler with debug level
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    
    # Create a detailed formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)
    
    # Configure loggers for different Fleet SDK components
    loggers_to_configure = [
        'fleet',                           # Main fleet module
        'fleet.client',                    # Fleet client
        'fleet._async.client',             # Async Fleet client  
        'fleet.base',                      # Base wrapper classes
        'fleet._async.base',               # Async base wrapper
        'fleet.instance.client',           # Instance client
        'fleet._async.instance.client',    # Async instance client
        'fleet.instance.base',             # Instance base wrapper
        'fleet._async.instance.base',      # Async instance base wrapper
    ]
    
    for logger_name in loggers_to_configure:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        # Clear any existing handlers to avoid duplicates
        logger.handlers.clear()
        logger.addHandler(console_handler)
        logger.propagate = False  # Prevent duplicate logs
    
    # Also enable httpx debug logging to see low-level HTTP details
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    
    print("🔍 Enhanced Debug Logging Enabled for Fleet SDK")
    print("=" * 50)
    print("This will now show detailed information about:")
    print("  • DNS resolution timing")
    print("  • HTTP client configuration")
    print("  • Request/response headers")
    print("  • Response content previews")
    print("  • Detailed error analysis")
    print("  • Network timing breakdowns")
    print()
    print("Log levels configured:")
    for logger_name in loggers_to_configure:
        print(f"  - {logger_name}: DEBUG")
    print("  - httpx: DEBUG")
    print()
    print("🚨 Note: This generates very detailed logs - use for troubleshooting only!")
    print()

def example_with_debug_logging():
    """Example showing debug logging in action with make() function."""
    
    # Setup debug logging first
    setup_debug_logging()
    
    # Create Fleet client
    fleet = Fleet()
    
    # Example environment key - replace with your actual environment
    env_key = "fira:nexus1.4"  # Replace with actual env_key
    region = "us-west-1"  # Optional: specify region
    
    try:
        print(f"Attempting to create instance for env_key='{env_key}', region='{region}'")
        print("=" * 60)
        
        # The make() call will now produce detailed debug logs
        env = fleet.make(env_key, region=region)
        
        print("=" * 60)
        print(f"✓ Successfully created environment instance: {env.instance_id}")
        
        # Clean up
        env.close()
        print(f"✓ Cleaned up instance: {env.instance_id}")
        
    except Exception as e:
        print("=" * 60)
        print(f"✗ Failed to create environment: {type(e).__name__}: {e}")
        print("\nCheck the debug logs above for detailed information about the failure.")
        return False
    
    return True

def minimal_debug_example():
    """Minimal example for quick debugging."""
    
    # Quick debug setup - just enable DEBUG for fleet loggers
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Set Fleet SDK loggers to DEBUG
    for logger_name in ['fleet', 'fleet.client', 'fleet._async.client']:
        logging.getLogger(logger_name).setLevel(logging.DEBUG)
    
    # Your Fleet code here
    fleet = Fleet()
    
    # Replace with your actual environment key
    env_key = "fira:nexus1.4"
    
    try:
        print(f"Testing with env_key='{env_key}' and no region (should use localhost)...")
        env = fleet.make(env_key)
        print(f"Success: {env.instance_id}")
        env.close()
    except Exception as e:
        print(f"Error without region: {e}")
        
    try:
        print(f"\nTesting with env_key='{env_key}' and region='us-west-1'...")
        env = fleet.make(env_key, region="us-west-1")
        print(f"Success: {env.instance_id}")
        env.close()
    except Exception as e:
        print(f"Error with region: {e}")

def different_logging_levels_example():
    """Example showing different levels of logging detail."""
    
    print("Choose logging detail level:")
    print("1. BASIC - Just high-level operation info")
    print("2. DETAILED - Include timing and status codes")  
    print("3. COMPREHENSIVE - Full request/response details")
    print("4. ULTRA-VERBOSE - Everything including httpx internals")
    
    choice = input("Enter choice (1-4): ").strip()
    
    if choice == "1":
        # Basic logging - just INFO level
        logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
        logging.getLogger('fleet.client').setLevel(logging.INFO)
        print("📝 Basic logging enabled - shows operation progress only")
        
    elif choice == "2":
        # Detailed logging - DEBUG for main client, INFO for HTTP details
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        logging.getLogger('fleet.client').setLevel(logging.DEBUG)
        logging.getLogger('fleet.base').setLevel(logging.INFO)
        print("📊 Detailed logging enabled - shows timing and status")
        
    elif choice == "3":
        # Comprehensive - DEBUG for all Fleet components
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        for logger_name in ['fleet', 'fleet.client', 'fleet.base', 'fleet.instance.client']:
            logging.getLogger(logger_name).setLevel(logging.DEBUG)
        print("🔍 Comprehensive logging enabled - shows request/response details")
        
    elif choice == "4":
        # Ultra-verbose - everything including httpx
        setup_debug_logging()  # Use the full setup
        print("🚨 Ultra-verbose logging enabled - shows everything!")
        
    else:
        print("Invalid choice, using basic logging")
        logging.basicConfig(level=logging.INFO)
        logging.getLogger('fleet.client').setLevel(logging.INFO)
    
    print()
    
    # Now run a test request
    fleet = Fleet()
    env_key = input("Enter environment key to test (or press Enter for demo): ").strip()
    if not env_key:
        env_key = "demo-env"
    
    try:
        print(f"Testing make() with env_key='{env_key}'...")
        env = fleet.make(env_key)
        print(f"✓ Success: {env.instance_id}")
        env.close()
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    print("Fleet SDK Debug Logging Example")
    print("================================")
    print()
    
    # Check if API key is set
    if not os.getenv("FLEET_API_KEY"):
        print("⚠️  Warning: FLEET_API_KEY environment variable not set")
        print("   Set your API key: export FLEET_API_KEY='your-api-key'")
        print()
    
    print("Choose an example:")
    print("1. Full debug logging example (recommended for troubleshooting)")
    print("2. Minimal debug example (quick setup)")
    print("3. Different logging levels demo (choose your detail level)")
    print("4. Show debug setup code only")
    
    choice = input("\nEnter your choice (1-4): ").strip()
    
    if choice == "1":
        example_with_debug_logging()
    elif choice == "2":
        minimal_debug_example()
    elif choice == "3":
        different_logging_levels_example()
    elif choice == "4":
        print("\n# Add this to your script for debug logging:")
        print("import logging")
        print("logging.basicConfig(level=logging.DEBUG)")
        print("logging.getLogger('fleet').setLevel(logging.DEBUG)")
        print("logging.getLogger('fleet.client').setLevel(logging.DEBUG)")
        print("logging.getLogger('fleet.base').setLevel(logging.DEBUG)")
    else:
        print("Invalid choice. Run the script again and choose 1, 2, 3, or 4.")
