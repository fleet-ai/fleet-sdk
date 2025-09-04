#!/usr/bin/env python3
"""
Debug script to help diagnose Fleet instance creation issues.
"""

import os
import sys
import json

# Add the fleet-sdk to the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from fleet import Fleet
from fleet.models import InstanceRequest

def main():
    print("🔍 Fleet Instance Creation Debug Script")
    print("=" * 50)
    
    # Check API key
    api_key = os.getenv("FLEET_API_KEY")
    print(f"API Key present: {'Yes' if api_key else 'No'}")
    if api_key:
        print(f"API Key (first 10 chars): {api_key[:10]}...")
    else:
        print("❌ FLEET_API_KEY environment variable not set!")
        return
    
    # Test Fleet client initialization
    try:
        fleet = Fleet(api_key=api_key)
        print("✅ Fleet client initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize Fleet client: {e}")
        return
    
    # Test InstanceRequest creation
    try:
        env_key = "fira:v1.3.2"
        print(f"\n🧪 Testing with env_key: {env_key}")
        
        # Parse env_key like Fleet.make() does
        if ":" in env_key:
            env_key_part, version = env_key.split(":", 1)
            if not version.startswith("v"):
                version = f"v{version}"
        else:
            env_key_part = env_key
            version = None
        
        print(f"Parsed env_key_part: {env_key_part}")
        print(f"Parsed version: {version}")
        
        # Create InstanceRequest
        request = InstanceRequest(env_key=env_key_part, version=version, region=None)
        print("✅ InstanceRequest created successfully")
        
        # Test model_dump
        request_dict = request.model_dump()
        print(f"✅ model_dump() successful: {json.dumps(request_dict, indent=2)}")
        
        # Test with json parameter
        if request_dict:
            print("✅ Request dict is not None")
        else:
            print("❌ Request dict is None!")
            
    except Exception as e:
        print(f"❌ Failed to create InstanceRequest: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Test API connectivity (just to /v1/env/ endpoint first)
    try:
        print(f"\n🌐 Testing API connectivity...")
        
        # Test list environments first (simpler endpoint)
        envs = fleet.list_envs()
        print(f"✅ Successfully retrieved {len(envs)} environments")
        
        # Show available environments
        if envs:
            print("Available environments:")
            for env in envs[:5]:  # Show first 5
                print(f"  - {env.env_key}")
                
    except Exception as e:
        print(f"❌ Failed to list environments: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Now try the actual instance creation with different configurations
    test_configs = [
        {"env_key": env_key, "region": "us-east-2", "desc": "with us-east-2 region"},
        {"env_key": env_key, "region": "us-west-1", "desc": "with us-west-1 region"},
        {"env_key": env_key, "region": None, "desc": "with no region"},
    ]
    
    for config in test_configs:
        try:
            print(f"\n🚀 Attempting to create instance {config['desc']}...")
            env = fleet.make(config["env_key"], region=config["region"])
            print(f"✅ Instance created successfully: {env.instance_id}")
            
            # Clean up
            try:
                env.close()
                print("✅ Instance closed successfully")
                break  # Success, no need to try other configs
            except Exception as e:
                print(f"⚠️  Failed to close instance: {e}")
                break
        except Exception as e:
            print(f"❌ Failed to create instance {config['desc']}: {e}")
            continue
    
    # If we got here, none of the configs worked
    print(f"\n🔍 Additional Debug Info:")
    print(f"Fleet client base_url: {fleet.client.base_url}")
    print(f"Last request that would be sent:")
    print(json.dumps(request_dict, indent=2))

if __name__ == "__main__":
    main()