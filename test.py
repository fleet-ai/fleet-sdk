"""
Sample verifier function for Fleet.

This file should be uploaded to S3 at:
s3://fleet-verifier-functions/verifier-funcs/{team_id}/{stub}.py

Example usage:
- Upload this file as s3://fleet-verifier-functions/verifier-funcs/team123/my-test-function.py
- Call the API: POST /v1/verify with {"stub": "my-test-function"}
"""

import json
import time


def verify() -> float:
    """
    Basic verification function that returns a score between 0.0 and 1.0.
    
    Returns:
        float: Score between 0.0 and 1.0 indicating success
    """
    print("Starting verification...")
    
    # Simulate some work
    time.sleep(0.1)
    
    # Test basic functionality
    test_data = {"message": "Hello from Modal sandbox!"}
    print(f"Test data: {json.dumps(test_data)}")
    
    # Return a score between 0 and 1
    return 0.95


def fleet_integration_test() -> float:
    """
    Test Fleet SDK integration.
    
    Returns:
        float: Score based on Fleet SDK availability
    """
    print("Testing Fleet SDK integration...")
    
    try:
        import fleet
        print("✅ Fleet SDK is available!")
        
        # Test basic Fleet functionality
        # Note: This would normally connect to a Fleet environment
        # For this example, we'll just verify the import works
        
        return 1.0
        
    except ImportError:
        print("❌ Fleet SDK not available")
        return 0.0


def database_connectivity_test() -> float:
    """
    Test database connectivity and basic operations.
    
    Returns:
        float: Score based on database operations
    """
    print("Testing database connectivity...")
    
    try:
        import sqlite3
        
        # Create in-memory database
        conn = sqlite3.connect(':memory:')
        cursor = conn.cursor()
        
        # Create test table
        cursor.execute('''
            CREATE TABLE test_table (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                value REAL
            )
        ''')
        
        # Insert test data
        cursor.execute("INSERT INTO test_table (name, value) VALUES (?, ?)", ("test", 42.5))
        
        # Query data
        cursor.execute("SELECT * FROM test_table")
        result = cursor.fetchone()
        
        conn.close()
        
        if result and result[1] == "test" and result[2] == 42.5:
            print("✅ Database operations successful")
            return 1.0
        else:
            print("❌ Database operations failed")
            return 0.0
            
    except Exception as e:
        print(f"❌ Database error: {e}")
        return 0.0


def api_request_test() -> float:
    """
    Test external API requests.
    
    Returns:
        float: Score based on API request success
    """
    print("Testing API requests...")
    
    try:
        import requests
        
        # Test HTTP request
        response = requests.get("https://httpbin.org/json", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ API request successful: {data}")
            return 1.0
        else:
            print(f"❌ API request failed with status {response.status_code}")
            return 0.0
            
    except Exception as e:
        print(f"❌ API request error: {e}")
        return 0.0


def comprehensive_test() -> float:
    """
    Comprehensive test that combines multiple verification steps.
    
    Returns:
        float: Average score across all tests
    """
    print("Running comprehensive verification tests...")
    
    tests = [
        ("Basic functionality", verify),
        ("Fleet SDK integration", fleet_integration_test),
        ("Database connectivity", database_connectivity_test),
        ("API requests", api_request_test),
    ]
    
    total_score = 0.0
    test_count = len(tests)
    
    for test_name, test_func in tests:
        try:
            print(f"\n--- {test_name} ---")
            score = test_func()
            print(f"Score: {score:.2f}")
            total_score += score
        except Exception as e:
            print(f"❌ {test_name} failed: {e}")
            # Score of 0.0 is already added by default
    
    average_score = total_score / test_count
    print(f"\n🎯 Overall verification score: {average_score:.2f}")
    
    return average_score