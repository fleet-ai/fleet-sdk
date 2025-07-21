#!/usr/bin/env python3
"""Example demonstrating verifier functionality with Fleet SDK.

This example shows how to use the @verifier decorator to create
functions that can be executed both locally and remotely on Fleet's
infrastructure.

Key features demonstrated:
1. Basic verifier with score return
2. Remote execution with automatic bundling
3. Verifier with external package requirements
4. Bundle inspection and caching
"""

import asyncio
import os
import logging
import fleet as flt
from fleet._async.verifiers import verifier, TASK_SUCCESSFUL_SCORE
from dotenv import load_dotenv

load_dotenv()

# Set up logging to see debug messages
# logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(levelname)s - %(message)s')


@verifier(key="simple_threshold_check_v6")
def simple_threshold_check(env, value: int, threshold: int = 10) -> float:
    """Simple verifier that checks if a value exceeds a threshold.
    
    Returns 1.0 if value > threshold, otherwise 0.0.
    """
    print(f"   Checking if {value} > {threshold}")
    return 1.0 if value > threshold else 0.0


@verifier(key="calculate_score_v6")
def calculate_score(env, scores: list) -> float:
    """Calculate average score from a list of values.
    
    Returns the average as a score between 0.0 and 1.0.
    """
    if not scores:
        return 0.0
    
    avg = sum(scores) / len(scores)
    # Normalize to 0-1 range assuming scores are 0-100
    normalized = avg / 100.0
    print(f"   Average score: {avg:.2f}, normalized: {normalized:.2f}")
    return min(1.0, max(0.0, normalized))


# @verifier(key="data_quality_check_v3", extra_requirements=["numpy>=1.24.0"])
# def data_quality_check(env, data_config: dict) -> dict:
#     """Example verifier with external dependencies and detailed results.
    
#     This would typically use numpy for data analysis, but we'll mock it here.
#     """
#     import random
    
#     checks_performed = []
#     total_score = 0.0
    
#     # Simulate various data quality checks
#     for check_name, check_params in data_config.items():
#         # Mock check result
#         check_score = random.uniform(0.7, 1.0)
#         checks_performed.append({
#             "name": check_name,
#             "score": check_score,
#             "params": check_params
#         })
#         total_score += check_score
    
#     final_score = total_score / len(checks_performed) if checks_performed else 0.0
    
#     return {
#         "score": final_score,
#         "checks_performed": len(checks_performed),
#         "details": checks_performed
#     }


async def main():
    """Run verifier examples."""
    print("=== Fleet Verifier Examples ===\n")
    
    # Get environment instance
    env_id = os.getenv("FLEET_ENV_ID", "a562dba8")
    print(f"Creating environment (ID: {env_id})...")
    
    try:
        env = await flt.env.get_async(env_id)
        print(f"✓ Environment ready")
        print(f"  Instance URL: {env.urls.root if hasattr(env, 'urls') else 'N/A'}")
        print(f"  Manager URL: {env.manager_url if hasattr(env, 'manager_url') else 'N/A'}")
        print()
    except Exception as e:
        print(f"✗ Failed to create environment: {e}")
        print("  Make sure FLEET_ENV_ID is set or use a valid instance ID")
        return

    # Example 1: Simple local and remote execution
    print("1. Simple Threshold Check")
    print("-" * 40)
    
    # Local execution
    print("Local execution:")
    local_result = await simple_threshold_check(env, value=15, threshold=10)
    print(f"   Result: {local_result} ✓\n")
    
    # Remote execution
    print("Remote execution (same function):")
    try:
        remote_result = await simple_threshold_check.remote(env, value=15, threshold=10)
        print(f"   Result: {remote_result} ✓")
        print("   🎉 Remote execution successful!\n")
    except Exception as e:
        print(f"   ✗ Remote execution failed: {e}")
        # Add more detail if it's an HTTP error
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            print(f"   Server response: {e.response.text}")
        print()

    # Example 2: Verifier with list processing
    print("2. Calculate Average Score")
    print("-" * 40)
    
    test_scores = [85, 92, 78, 95, 88]
    print(f"Input scores: {test_scores}")
    
    # Local execution
    local_avg = await calculate_score(env, scores=test_scores)
    print(f"Local result: {local_avg:.3f}")
    
    # Remote execution
    try:
        remote_avg = await calculate_score.remote(env, scores=test_scores)
        print(f"Remote result: {remote_avg:.3f}")
        print(f"Match: {'✓' if abs(local_avg - remote_avg) < 0.001 else '✗'}\n")
    except Exception as e:
        print(f"Remote execution failed: {e}\n")

    # Example 3: Verifier with complex return type and external dependencies
    # print("3. Data Quality Check (with external dependencies)")
    # print("-" * 40)
    
    # quality_config = {
    #     "completeness": {"threshold": 0.95},
    #     "accuracy": {"tolerance": 0.02},
    #     "consistency": {"rules": ["no_nulls", "valid_range"]}
    # }
    
    # result = await data_quality_check(env, data_config=quality_config)
    # print(f"Local execution result:")
    # print(f"   Overall score: {result['score']:.3f}")
    # print(f"   Checks performed: {result['checks_performed']}")
    
    # # Try remote execution
    # try:
    #     remote_result = await data_quality_check.remote(env, data_config=quality_config)
    #     print(f"\nRemote execution result:")
    #     print(f"   Overall score: {remote_result['score']:.3f}")
    #     print(f"   ✓ Complex verifier with numpy requirement executed remotely!\n")
    # except Exception as e:
    #     print(f"   Remote execution failed: {e}\n")

    # # Example 4: Bundle inspection
    # print("4. Bundle Inspection")
    # print("-" * 40)
    
    # # Show bundle details for a verifier
    # bundle_data, bundle_sha = data_quality_check._get_or_create_bundle()
    # print(f"Bundle SHA: {bundle_sha[:16]}...")
    # print(f"Bundle size: {len(bundle_data)} bytes")
    
    # # Show bundle contents
    # import zipfile
    # import io
    
    # with zipfile.ZipFile(io.BytesIO(bundle_data), 'r') as zf:
    #     print("\nBundle contents:")
    #     for filename in sorted(zf.namelist()):
    #         file_info = zf.getinfo(filename)
    #         print(f"  - {filename} ({file_info.file_size} bytes)")
            
    #         if filename == "requirements.txt":
    #             content = zf.read(filename).decode('utf-8')
    #             print(f"    Contents: {content.strip()}")
    #         elif filename == "verifier.py":
    #             content = zf.read(filename).decode('utf-8')
    #             print(f"    First 200 chars: {content[:200]}...")

    # # Clean up
    # print("\nCleaning up...")
    # try:
    #     await env.close()
    # except Exception as e:
    #     print(f"Note: Cleanup failed (this is OK): {e}")
    # print("✓ Done!")


if __name__ == "__main__":
    asyncio.run(main())
