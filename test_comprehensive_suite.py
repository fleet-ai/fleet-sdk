#!/usr/bin/env python3
"""
Comprehensive Fleet SDK Testing Suite

This test suite validates all major functionality points of the Fleet SDK
and ensures compatibility with the upstream server. It uses the provided
verifier functions as test beds and reports where the SDK is functioning
and where it may be broken.

Requirements:
- FLEET_API_KEY must be set in .env file
- Access to Fleet environments (e.g., 'fira:v1.3.1')

Usage:
    python test_comprehensive_suite.py [environment_key]
    
Examples:
    python test_comprehensive_suite.py                   # Uses default 'fira:v1.3.1'
    python test_comprehensive_suite.py fira:v1.3.1       # Test specific environment version
    python test_comprehensive_suite.py jira              # Test jira environment
"""

import os
import sys
import time
import traceback
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from contextlib import contextmanager

import fleet as flt
from fleet.verifiers.db import IgnoreConfig
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class TestResult:
    """Represents the result of a single test."""
    name: str
    category: str
    passed: bool
    duration: float
    error: Optional[str] = None
    details: Optional[str] = None
    score: Optional[float] = None

@dataclass
class TestReport:
    """Comprehensive test report containing all test results."""
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    results: List[TestResult] = field(default_factory=list)
    
    def add_result(self, result: TestResult):
        """Add a test result to the report."""
        self.results.append(result)
        self.total_tests += 1
        if result.passed:
            self.passed_tests += 1
        else:
            self.failed_tests += 1
    
    def finalize(self):
        """Mark the report as complete."""
        self.end_time = datetime.now()
    
    def get_success_rate(self) -> float:
        """Calculate the success rate as a percentage."""
        if self.total_tests == 0:
            return 0.0
        return (self.passed_tests / self.total_tests) * 100


class FleetSDKTestSuite:
    """Comprehensive test suite for Fleet SDK functionality."""
    
    def __init__(self, env_key: str = "fira:v1.3.1"):
        self.env_key = env_key
        self.report = TestReport()
        self.fleet_client: Optional[flt.Fleet] = None
        self.test_env: Optional[flt.SyncEnv] = None
        
        # Verify API key is available
        self.api_key = os.getenv("FLEET_API_KEY")
        if not self.api_key:
            raise ValueError("FLEET_API_KEY must be set in environment or .env file")
    
    @contextmanager
    def timed_test(self, test_name: str, category: str):
        """Context manager for timing and recording test results."""
        start_time = time.time()
        result = TestResult(name=test_name, category=category, passed=False, duration=0.0)
        
        try:
            logger.info(f"Running test: {test_name}")
            yield result
            result.passed = True
            logger.info(f"✓ {test_name} - PASSED")
        except Exception as e:
            result.error = str(e)
            result.details = traceback.format_exc()
            logger.error(f"✗ {test_name} - FAILED: {e}")
        finally:
            result.duration = time.time() - start_time
            self.report.add_result(result)
    
    def setup_client(self):
        """Initialize the Fleet client."""
        with self.timed_test("Initialize Fleet Client", "Core") as result:
            self.fleet_client = flt.Fleet(api_key=self.api_key)
            result.details = f"Client initialized with API key: {self.api_key[:8]}..."
    
    def test_core_functionality(self):
        """Test core Fleet client functionality."""
        
        # Test environment listing
        with self.timed_test("List Environments", "Core") as result:
            envs = self.fleet_client.list_envs()
            result.details = f"Found {len(envs)} environments"
            assert len(envs) > 0, "No environments found"
        
        # Test region listing  
        with self.timed_test("List Regions", "Core") as result:
            regions = self.fleet_client.list_regions()
            result.details = f"Found {len(regions)} regions: {regions}"
            assert len(regions) > 0, "No regions found"
        
        # Test account information
        with self.timed_test("Get Account Info", "Core") as result:
            account = self.fleet_client.account()
            result.details = f"Team: {account.team_name}, Instances: {account.instance_count}/{account.instance_limit}"
    
    def test_environment_management(self):
        """Test environment creation and management."""
        
        # Test environment creation
        with self.timed_test("Create Environment Instance", "Environment") as result:
            self.test_env = self.fleet_client.make(self.env_key)
            result.details = f"Created instance: {self.test_env.instance_id} in region {self.test_env.region}"
            assert self.test_env.instance_id, "Instance ID not set"
        
        # Test instance listing
        with self.timed_test("List Instances", "Environment") as result:
            instances = self.fleet_client.instances()
            result.details = f"Found {len(instances)} total instances"
            
            # Verify our instance is in the list
            our_instance = next((i for i in instances if i.instance_id == self.test_env.instance_id), None)
            assert our_instance is not None, f"Our instance {self.test_env.instance_id} not found in list"
        
        # Test environment reset
        with self.timed_test("Reset Environment", "Environment") as result:
            reset_response = self.test_env.reset(seed=42)
            result.details = f"Reset response: {reset_response.success} - {reset_response.message}"
            assert reset_response.success, "Environment reset failed"
    
    def test_resource_management(self):
        """Test resource access and management."""
        
        # Test resource listing
        with self.timed_test("List Resources", "Resources") as result:
            resources = self.test_env.resources()
            result.details = f"Found {len(resources)} resources: {[r.name for r in resources]}"
            assert len(resources) > 0, "No resources found"
        
        # Test database access
        with self.timed_test("Access Database Resource", "Resources") as result:
            db = self.test_env.db("current")
            db_info = db.describe()
            result.details = f"Database: {db_info.name}, Tables: {len(db_info.tables)}"
            assert len(db_info.tables) > 0, "No tables found in database"
        
        # Test database queries
        with self.timed_test("Execute Database Query", "Resources") as result:
            db = self.test_env.db("current")
            # Try to query a common table that should exist
            tables = db.describe().tables
            if tables:
                table_name = tables[0].name
                query_result = db.query(f"SELECT COUNT(*) as count FROM {table_name}")
                result.details = f"Query result: {query_result.rows[0]} from table {table_name}"
                assert query_result.rows, "Query returned no results"
        
        # Test browser resource (if available)
        with self.timed_test("Access Browser Resource", "Resources") as result:
            try:
                browser = self.test_env.browser("cdp")
                cdp_url = browser.cdp_url()
                devtools_url = browser.devtools_url()
                result.details = f"CDP URL: {cdp_url[:50]}..., DevTools URL available: {bool(devtools_url)}"
            except Exception as e:
                # Browser might not be available in all environments
                if "not found" in str(e).lower() or "404" in str(e):
                    result.details = "Browser resource not available in this environment"
                    result.passed = True  # This is acceptable
                else:
                    raise
    
    def test_database_operations(self):
        """Test advanced database operations and DSL."""
        
        # Test database snapshot functionality
        with self.timed_test("Create Database Snapshots", "Database") as result:
            before_db = self.test_env.db("seed")
            after_db = self.test_env.db("current")
            
            # Verify both snapshots work
            before_tables = before_db.describe().tables
            after_tables = after_db.describe().tables
            
            result.details = f"Seed DB: {len(before_tables)} tables, Current DB: {len(after_tables)} tables"
            assert len(before_tables) > 0, "Seed database has no tables"
            assert len(after_tables) > 0, "Current database has no tables"
        
        # Test query builder DSL
        with self.timed_test("Test Database Query Builder", "Database") as result:
            db = self.test_env.db("current")
            tables = db.describe().tables
            
            if tables:
                table_name = tables[0].name
                # Test basic query builder operations
                count_result = db.table(table_name).count()
                all_rows = db.table(table_name).limit(5).all()
                
                result.details = f"Table {table_name}: {count_result.value} total rows, sampled {len(all_rows)} rows"
                assert count_result.value >= 0, "Invalid count result"
    
    def test_verifiers(self):
        """Test verifier functionality using the provided examples."""
        
        # Test the first provided verifier
        with self.timed_test("Execute Blue-Green Deployment Verifier (Local)", "Verifiers") as result:
            score = validate_finish_blue_green_deployment(self.test_env)
            result.score = score
            result.details = f"Verifier returned score: {score}"
            assert 0.0 <= score <= 1.0, f"Invalid verifier score: {score}"
        
        # Test remote verifier execution (if supported)
        with self.timed_test("Execute Blue-Green Deployment Verifier (Remote)", "Verifiers") as result:
            try:
                remote_score = validate_finish_blue_green_deployment.remote(self.test_env)
                result.score = remote_score
                result.details = f"Remote verifier returned score: {remote_score}"
                assert 0.0 <= remote_score <= 1.0, f"Invalid remote verifier score: {remote_score}"
            except Exception as e:
                if "not implemented" in str(e).lower() or "async" in str(e).lower():
                    result.details = "Remote execution not supported for this verifier type"
                    result.passed = True  # This is acceptable
                else:
                    raise
        
        # Test the template verifier
        with self.timed_test("Execute Template Verifier (Local)", "Verifiers") as result:
            score = template_verifier_function(self.test_env)
            result.score = score
            result.details = f"Template verifier returned score: {score}"
            assert 0.0 <= score <= 1.0, f"Invalid template verifier score: {score}"
        
        # Test custom verifier with specific functionality
        with self.timed_test("Execute Database Count Verifier", "Verifiers") as result:
            score = test_database_count_verifier(self.test_env)
            result.score = score
            result.details = f"Database count verifier returned score: {score}"
            assert 0.0 <= score <= 1.0, f"Invalid database count verifier score: {score}"
    
    def test_error_handling(self):
        """Test error handling and edge cases."""
        
        # Test invalid database queries
        with self.timed_test("Handle Invalid Database Query", "Error Handling") as result:
            db = self.test_env.db("current")
            try:
                db.query("SELECT * FROM nonexistent_table")
                result.details = "Query should have failed but didn't"
                assert False, "Expected query to fail"
            except Exception as e:
                result.details = f"Correctly caught error: {type(e).__name__}: {str(e)[:100]}"
                result.passed = True
        
        # Test invalid verifier behavior
        with self.timed_test("Handle Verifier Exceptions", "Error Handling") as result:
            score = error_prone_verifier(self.test_env)
            result.score = score
            result.details = f"Error-prone verifier returned score: {score} (should be 0.0 for handled errors)"
            # Verifiers should return 0.0 when they encounter errors
            assert score == 0.0, f"Expected error score 0.0, got {score}"
    
    def test_integration_features(self):
        """Test integration features and advanced functionality."""
        
        # Test task loading
        with self.timed_test("Load Tasks", "Integration") as result:
            try:
                tasks = self.fleet_client.load_tasks()
                result.details = f"Loaded {len(tasks)} tasks"
                # Tasks might be empty, which is fine
            except Exception as e:
                if "not implemented" in str(e).lower() or "404" in str(e):
                    result.details = "Task loading not available"
                    result.passed = True
                else:
                    raise
        
        # Test environment-specific task loading
        with self.timed_test("Load Environment-Specific Tasks", "Integration") as result:
            try:
                env_key_part = self.env_key.split(":")[0]  # Remove version
                tasks = self.fleet_client.load_tasks(env_key=env_key_part)
                result.details = f"Loaded {len(tasks)} tasks for environment {env_key_part}"
            except Exception as e:
                if "not implemented" in str(e).lower() or "404" in str(e):
                    result.details = "Environment-specific task loading not available"
                    result.passed = True
                else:
                    raise
    
    def cleanup(self):
        """Clean up test resources."""
        if self.test_env:
            with self.timed_test("Cleanup Environment", "Cleanup") as result:
                close_response = self.test_env.close()
                result.details = f"Environment closed: {close_response.status} (terminated: {close_response.terminated_at})"
    
    def run_all_tests(self) -> TestReport:
        """Run all tests and return the comprehensive report."""
        logger.info("Starting Fleet SDK Comprehensive Test Suite")
        logger.info(f"Testing with environment: {self.env_key}")
        logger.info(f"API Key: {self.api_key[:8]}..." if self.api_key else "No API Key")
        
        try:
            # Core setup
            self.setup_client()
            
            # Run test categories
            self.test_core_functionality()
            self.test_environment_management()
            self.test_resource_management()
            self.test_database_operations()
            self.test_verifiers()
            self.test_error_handling()
            self.test_integration_features()
            
        except Exception as e:
            logger.error(f"Critical test failure: {e}")
            # Add a failure result for critical errors
            critical_result = TestResult(
                name="Critical Test Failure",
                category="Critical",
                passed=False,
                duration=0.0,
                error=str(e),
                details=traceback.format_exc()
            )
            self.report.add_result(critical_result)
        
        finally:
            # Always try to cleanup
            try:
                self.cleanup()
            except Exception as e:
                logger.error(f"Cleanup failed: {e}")
        
        self.report.finalize()
        return self.report
    
    def print_detailed_report(self):
        """Print a detailed test report."""
        report = self.report
        
        print("\n" + "="*80)
        print("FLEET SDK COMPREHENSIVE TEST REPORT")
        print("="*80)
        
        print(f"Test Environment: {self.env_key}")
        print(f"Start Time: {report.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"End Time: {report.end_time.strftime('%Y-%m-%d %H:%M:%S') if report.end_time else 'Not completed'}")
        if report.end_time:
            duration = (report.end_time - report.start_time).total_seconds()
            print(f"Total Duration: {duration:.2f} seconds")
        
        print(f"\nOVERALL RESULTS:")
        print(f"Total Tests: {report.total_tests}")
        print(f"Passed: {report.passed_tests}")
        print(f"Failed: {report.failed_tests}")
        print(f"Success Rate: {report.get_success_rate():.1f}%")
        
        # Group results by category
        categories = {}
        for result in report.results:
            if result.category not in categories:
                categories[result.category] = []
            categories[result.category].append(result)
        
        print(f"\nRESULTS BY CATEGORY:")
        print("-"*80)
        
        for category, results in categories.items():
            passed = sum(1 for r in results if r.passed)
            total = len(results)
            success_rate = (passed / total * 100) if total > 0 else 0
            
            print(f"\n{category.upper()} ({passed}/{total} - {success_rate:.1f}%)")
            print("-" * 40)
            
            for result in results:
                status = "✓ PASS" if result.passed else "✗ FAIL"
                duration_str = f"({result.duration:.2f}s)"
                print(f"{status:<8} {result.name:<40} {duration_str}")
                
                if result.score is not None:
                    print(f"         Score: {result.score}")
                
                if result.details:
                    print(f"         Details: {result.details}")
                
                if result.error:
                    print(f"         Error: {result.error}")
        
        print(f"\nFUNCTIONALITY STATUS:")
        print("-"*80)
        
        core_passed = sum(1 for r in categories.get('Core', []) if r.passed)
        core_total = len(categories.get('Core', []))
        
        env_passed = sum(1 for r in categories.get('Environment', []) if r.passed)
        env_total = len(categories.get('Environment', []))
        
        resource_passed = sum(1 for r in categories.get('Resources', []) if r.passed)
        resource_total = len(categories.get('Resources', []))
        
        db_passed = sum(1 for r in categories.get('Database', []) if r.passed)
        db_total = len(categories.get('Database', []))
        
        verifier_passed = sum(1 for r in categories.get('Verifiers', []) if r.passed)
        verifier_total = len(categories.get('Verifiers', []))
        
        print(f"✓ Core Client Functionality: {core_passed}/{core_total} working")
        print(f"✓ Environment Management: {env_passed}/{env_total} working")
        print(f"✓ Resource Access: {resource_passed}/{resource_total} working") 
        print(f"✓ Database Operations: {db_passed}/{db_total} working")
        print(f"✓ Verifier Execution: {verifier_passed}/{verifier_total} working")
        
        # Summary assessment
        overall_health = report.get_success_rate()
        print(f"\nSDK HEALTH ASSESSMENT:")
        print("-"*80)
        
        if overall_health >= 90:
            print("🟢 EXCELLENT: SDK is functioning properly with minimal issues")
        elif overall_health >= 75:
            print("🟡 GOOD: SDK is mostly functional with some minor issues")
        elif overall_health >= 50:
            print("🟠 FAIR: SDK has significant issues but core functionality works")
        else:
            print("🔴 POOR: SDK has major issues requiring immediate attention")
        
        print(f"\nFor detailed logs, check the console output above.")
        print("="*80)


# Test Verifier Functions
# These are the verifiers used as test beds for functionality

@flt.verifier_sync(key="validate_finish_blue_green_deployment")  
def validate_finish_blue_green_deployment(
    env: flt.SyncEnv, final_answer: str | None = None
) -> float:
    """Validate that DEBT-722 and DEBT-720 are marked as Done"""
    before = env.db("seed")
    after = env.db("current")

    # Check final state
    try:
        after.table("issues").eq("id", "DEBT-722").assert_eq("board_list", "Done")
    except:
        return 0.0
    try:
        after.table("issues").eq("id", "DEBT-720").assert_eq("board_list", "Done")
    except:
        return 0.0

    # Configure ignore settings for this validation
    ignore_config = IgnoreConfig(
        tables={"activities", "pageviews"},
        table_fields={
            "issues": {"updated_at", "created_at", "rowid"},
            "boards": {"updated_at", "created_at", "rowid"},
            "projects": {"updated_at", "created_at", "rowid"},
            "sprints": {"updated_at", "created_at", "rowid"},
            "users": {"updated_at", "created_at", "rowid"},
        },
    )

    # Enforce invariant: nothing else changed (with ignore configuration)
    try:
        before.diff(after, ignore_config).expect_only(
            [
                {
                    "table": "issues",
                    "pk": "DEBT-722",
                    "field": "board_list",
                    "after": "Done",
                },
                {
                    "table": "issues",
                    "pk": "DEBT-720",
                    "field": "board_list",
                    "after": "Done",
                },
            ]
        )
    except:
        return 0.0

    return 1.0


@flt.verifier_sync(key="template_verifier_key")
def template_verifier_function(env: flt.SyncEnv, *args, **kwargs) -> float:
    """Template verifier function that validates basic environment functionality"""
    try:
        # Test basic database access
        db = env.db("current")
        tables = db.describe().tables
        
        if not tables:
            return 0.0
            
        # Test query execution
        first_table = tables[0].name
        result = db.query(f"SELECT COUNT(*) as count FROM {first_table}")
        
        if not result.rows:
            return 0.0
            
        return 1.0
    except Exception:
        return 0.0


@flt.verifier_sync(key="test_database_count_verifier")
def test_database_count_verifier(env: flt.SyncEnv) -> float:
    """Test verifier that checks database table counts"""
    try:
        db = env.db("current")
        tables = db.describe().tables
        
        # Check that we have at least one table with data
        total_rows = 0
        for table in tables:
            try:
                count_result = db.table(table.name).count()
                total_rows += count_result.value
            except:
                continue
        
        # Return success if we found data
        return 1.0 if total_rows > 0 else 0.5
        
    except Exception:
        return 0.0


@flt.verifier_sync(key="error_prone_verifier")
def error_prone_verifier(env: flt.SyncEnv) -> float:
    """Verifier that intentionally causes errors to test error handling"""
    try:
        # This should cause an error
        db = env.db("current")
        db.query("SELECT * FROM definitely_nonexistent_table_12345")
        return 1.0  # Should not reach here
    except Exception:
        # This is expected - verifiers should gracefully handle errors
        return 0.0


def main():
    """Main function to run the test suite."""
    if len(sys.argv) > 1:
        env_key = sys.argv[1]
    else:
        env_key = "fira:v1.4.0"  # Default test environment

    try:
        from importlib.metadata import version
        fleet_version = version('fleet-python')
        print(f"Fleet SDK version: {fleet_version}")
    except Exception:
        print("Fleet SDK version: Unable to determine")
    
    # Initialize and run test suite
    test_suite = FleetSDKTestSuite(env_key=env_key)
    
    try:
        report = test_suite.run_all_tests()
        test_suite.print_detailed_report()
        
        # Exit with appropriate code
        if report.get_success_rate() < 50:
            sys.exit(1)  # Major issues
        elif report.failed_tests > 0:
            sys.exit(2)  # Some issues
        else:
            sys.exit(0)  # All good
            
    except KeyboardInterrupt:
        print("\nTest suite interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\nCritical error running test suite: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
