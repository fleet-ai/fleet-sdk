"""
Mock data constants for unit tests.
Contains sample data that mimics real Fleet SDK responses.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

# Mock API Keys
MOCK_API_KEY = "sk_test_1234567890abcdef"
MOCK_INVALID_API_KEY = "invalid_key"

# Mock Environment Keys
MOCK_ENV_KEYS = [
    "dropbox:Forge1.1.0",
    "hubspot:Forge1.1.0", 
    "ramp:Forge1.1.0",
    "confluence:v1.4.1",
    "jira:v1.3.1"
]

# Mock Environment Data
MOCK_ENVIRONMENTS = [
    {
        "key": "dropbox:Forge1.1.0",
        "name": "Dropbox",
        "default_version": "Forge1.1.0",
        "region": "us-west-1",
        "status": "available",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z"
    },
    {
        "key": "hubspot:Forge1.1.0", 
        "name": "HubSpot",
        "default_version": "Forge1.1.0",
        "region": "us-west-1",
        "status": "available",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z"
    },
    {
        "key": "ramp:Forge1.1.0",
        "name": "Ramp", 
        "default_version": "Forge1.1.0",
        "region": "us-west-1",
        "status": "available",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z"
    }
]

# Mock Regions
MOCK_REGIONS = [
    {
        "id": "us-west-1",
        "name": "US West (N. California)",
        "status": "available"
    },
    {
        "id": "us-east-1", 
        "name": "US East (N. Virginia)",
        "status": "available"
    },
    {
        "id": "eu-west-1",
        "name": "Europe (Ireland)", 
        "status": "available"
    }
]

# Mock Instance Data
MOCK_INSTANCE = {
    "id": "inst_1234567890abcdef",
    "env_key": "dropbox:Forge1.1.0",
    "status": "running",
    "region": "us-west-1",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z",
    "terminated_at": None,
    "resources": {
        "database": {
            "url": "sqlite:///tmp/fleet_db.sqlite",
            "type": "sqlite"
        },
        "browser": {
            "cdp_url": "ws://localhost:9222/devtools/browser",
            "devtools_url": "http://localhost:9222"
        }
    }
}

# Mock Account Data
MOCK_ACCOUNT = {
    "id": "acc_1234567890abcdef",
    "name": "Test Account",
    "team_id": "team_1234567890abcdef",
    "team_name": "Test Team",
    "plan": "pro",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
}

# Mock Database Schema
MOCK_DATABASE_SCHEMA = {
    "tables": [
        {
            "name": "users",
            "columns": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "name", "type": "TEXT", "nullable": False},
                {"name": "email", "type": "TEXT", "nullable": False},
                {"name": "created_at", "type": "DATETIME", "nullable": False}
            ]
        },
        {
            "name": "orders",
            "columns": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "user_id", "type": "INTEGER", "foreign_key": "users.id"},
                {"name": "amount", "type": "DECIMAL", "nullable": False},
                {"name": "status", "type": "TEXT", "nullable": False},
                {"name": "created_at", "type": "DATETIME", "nullable": False}
            ]
        }
    ]
}

# Mock Database Query Results
MOCK_QUERY_RESULTS = {
    "users": [
        {"id": 1, "name": "John Doe", "email": "john@example.com", "created_at": "2024-01-01T00:00:00Z"},
        {"id": 2, "name": "Jane Smith", "email": "jane@example.com", "created_at": "2024-01-02T00:00:00Z"},
        {"id": 3, "name": "Bob Johnson", "email": "bob@example.com", "created_at": "2024-01-03T00:00:00Z"}
    ],
    "orders": [
        {"id": 1, "user_id": 1, "amount": 99.99, "status": "completed", "created_at": "2024-01-01T10:00:00Z"},
        {"id": 2, "user_id": 2, "amount": 149.99, "status": "pending", "created_at": "2024-01-02T10:00:00Z"},
        {"id": 3, "user_id": 1, "amount": 79.99, "status": "completed", "created_at": "2024-01-03T10:00:00Z"}
    ]
}

# Mock Browser Data
MOCK_BROWSER_DATA = {
    "cdp_url": "ws://localhost:9222/devtools/browser",
    "devtools_url": "http://localhost:9222",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "viewport": {"width": 1920, "height": 1080},
    "cookies": [],
    "local_storage": {},
    "session_storage": {}
}

# Mock Verifier Data
MOCK_VERIFIER_RESULT = {
    "success": True,
    "message": "Verification passed",
    "execution_time": 0.123,
    "timestamp": "2024-01-01T00:00:00Z",
    "details": {
        "checks_performed": 5,
        "assertions_passed": 5,
        "assertions_failed": 0
    }
}

MOCK_VERIFIER_FAILURE = {
    "success": False,
    "message": "Verification failed: Expected 3 users, got 2",
    "execution_time": 0.089,
    "timestamp": "2024-01-01T00:00:00Z",
    "details": {
        "checks_performed": 3,
        "assertions_passed": 2,
        "assertions_failed": 1,
        "error": "AssertionError: Expected 3 users, got 2"
    }
}

# Mock Task Data
MOCK_TASK = {
    "id": "task_1234567890abcdef",
    "name": "Test Task",
    "description": "A test task for unit testing",
    "env_id": "dropbox:Forge1.1.0",
    "version": "Forge1.1.0",
    "status": "pending",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z",
    "metadata": {
        "priority": "high",
        "category": "testing",
        "tags": ["unit-test", "mock"]
    }
}

# Mock MCP Data
MOCK_MCP_DATA = {
    "url": "http://localhost:3000/mcp",
    "version": "1.0.0",
    "capabilities": ["openai", "anthropic"],
    "status": "connected"
}

# Mock Error Responses
MOCK_ERRORS = {
    "invalid_api_key": {
        "error": "Invalid API key",
        "code": "INVALID_API_KEY",
        "status": 401
    },
    "environment_not_found": {
        "error": "Environment not found",
        "code": "ENVIRONMENT_NOT_FOUND", 
        "status": 404
    },
    "rate_limit_exceeded": {
        "error": "Rate limit exceeded",
        "code": "RATE_LIMIT_EXCEEDED",
        "status": 429
    },
    "internal_server_error": {
        "error": "Internal server error",
        "code": "INTERNAL_SERVER_ERROR",
        "status": 500
    }
}

# Mock Performance Data
MOCK_PERFORMANCE_DATA = {
    "environment_creation": {
        "min_time": 0.5,
        "max_time": 2.0,
        "avg_time": 1.2,
        "p95_time": 1.8
    },
    "database_query": {
        "min_time": 0.01,
        "max_time": 0.1,
        "avg_time": 0.05,
        "p95_time": 0.08
    },
    "browser_operation": {
        "min_time": 0.1,
        "max_time": 1.0,
        "avg_time": 0.3,
        "p95_time": 0.7
    }
}

# Mock Configuration Data
MOCK_CONFIG = {
    "api_base_url": "https://api.fleet.dev",
    "timeout": 30,
    "max_retries": 3,
    "retry_delay": 1.0,
    "user_agent": "Fleet-SDK-Python/1.0.0"
}

# Mock HTTP Responses
MOCK_HTTP_RESPONSES = {
    "success": {
        "status_code": 200,
        "headers": {"Content-Type": "application/json"},
        "json": {"success": True}
    },
    "created": {
        "status_code": 201,
        "headers": {"Content-Type": "application/json"},
        "json": {"id": "new_resource_id", "status": "created"}
    },
    "no_content": {
        "status_code": 204,
        "headers": {},
        "text": ""
    },
    "bad_request": {
        "status_code": 400,
        "headers": {"Content-Type": "application/json"},
        "json": {"error": "Bad Request", "code": "BAD_REQUEST"}
    },
    "unauthorized": {
        "status_code": 401,
        "headers": {"Content-Type": "application/json"},
        "json": {"error": "Unauthorized", "code": "UNAUTHORIZED"}
    },
    "not_found": {
        "status_code": 404,
        "headers": {"Content-Type": "application/json"},
        "json": {"error": "Not Found", "code": "NOT_FOUND"}
    },
    "rate_limit": {
        "status_code": 429,
        "headers": {"Content-Type": "application/json", "Retry-After": "60"},
        "json": {"error": "Rate Limited", "code": "RATE_LIMITED"}
    },
    "server_error": {
        "status_code": 500,
        "headers": {"Content-Type": "application/json"},
        "json": {"error": "Internal Server Error", "code": "INTERNAL_ERROR"}
    }
}
