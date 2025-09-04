#!/usr/bin/env python3
"""
Simple test script to try creating instances with different parameters.
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from fleet import Fleet

def main():
    api_key = os.getenv("FLEET_API_KEY")
    if not api_key:
        print("❌ FLEET_API_KEY not set")
        return
    
    fleet = Fleet(api_key=api_key)
    
    # Try different variations
    test_cases = [
        # Basic cases
        {"env_key": "fira", "desc": "fira without version"},
        {"env_key": "fira:v1.3.2", "desc": "fira with v1.3.2"},
        {"env_key": "fira:1.3.2", "desc": "fira with 1.3.2"},
        
        # With regions
        {"env_key": "fira", "region": "us-east-2", "desc": "fira with us-east-2"},
        {"env_key": "fira", "region": "us-west-1", "desc": "fira with us-west-1"},
        
        # Other environments
        {"env_key": "hubspot", "desc": "hubspot without version"},
        {"env_key": "confluence", "desc": "confluence without version"},
    ]
    
    for case in test_cases:
        try:
            print(f"\n🧪 Testing: {case['desc']}")
            kwargs = {k: v for k, v in case.items() if k not in ['desc']}
            env = fleet.make(**kwargs)
            print(f"✅ SUCCESS: {env.instance_id}")
            
            # Immediately clean up
            env.close()
            print("✅ Cleaned up")
            break  # Stop on first success
            
        except Exception as e:
            print(f"❌ FAILED: {e}")
            continue
    
    print("\n🏁 Done testing")

if __name__ == "__main__":
    main()