"""
Performance test to identify what's taking so long.
"""

import pytest
import time
from .base_test import BaseFleetTest


class TestPerformance(BaseFleetTest):
    """Test performance of different operations."""
    
    def test_environment_creation_time(self, fleet_client):
        """Test how long environment creation takes."""
        start_time = time.time()
        
        env = fleet_client.make("dropbox:Forge1.1.0")
        
        end_time = time.time()
        creation_time = end_time - start_time
        
        print(f"⏱️  Environment creation took: {creation_time:.2f} seconds")
        assert creation_time < 60, f"Environment creation took too long: {creation_time:.2f}s"
        
        # Clean up
        env.close()
    
    def test_database_operation_time(self, env):
        """Test how long database operations take."""
        start_time = time.time()
        
        db = env.db()
        result = db.query("SELECT 1 as test")
        
        end_time = time.time()
        operation_time = end_time - start_time
        
        print(f"⏱️  Database operation took: {operation_time:.2f} seconds")
        assert operation_time < 10, f"Database operation took too long: {operation_time:.2f}s"
    
    def test_browser_operation_time(self, env):
        """Test how long browser operations take."""
        start_time = time.time()
        
        browser = env.browser()
        cdp_url = browser.cdp_url()
        devtools_url = browser.devtools_url()
        
        end_time = time.time()
        operation_time = end_time - start_time
        
        print(f"⏱️  Browser operation took: {operation_time:.2f} seconds")
        assert operation_time < 10, f"Browser operation took too long: {operation_time:.2f}s"
    
    def test_environment_reset_time(self, env):
        """Test how long environment reset takes."""
        start_time = time.time()
        
        reset_response = env.reset(seed=42)
        
        end_time = time.time()
        reset_time = end_time - start_time
        
        print(f"⏱️  Environment reset took: {reset_time:.2f} seconds")
        assert reset_time < 30, f"Environment reset took too long: {reset_time:.2f}s"
    
    def test_environment_step_time(self, env):
        """Test how long environment step takes."""
        start_time = time.time()
        
        action = {"type": "test", "data": {"message": "Hello Fleet!"}}
        state, reward, done = env.instance.step(action)
        
        end_time = time.time()
        step_time = end_time - start_time
        
        print(f"⏱️  Environment step took: {step_time:.2f} seconds")
        assert step_time < 10, f"Environment step took too long: {step_time:.2f}s"
    
    @pytest.mark.asyncio
    async def test_async_environment_creation_time(self, async_fleet_client):
        """Test how long async environment creation takes."""
        start_time = time.time()
        
        env = await async_fleet_client.make("hubspot:Forge1.1.0")
        
        end_time = time.time()
        creation_time = end_time - start_time
        
        print(f"⏱️  Async environment creation took: {creation_time:.2f} seconds")
        assert creation_time < 60, f"Async environment creation took too long: {creation_time:.2f}s"
        
        # Clean up
        await env.close()
    
    @pytest.mark.asyncio
    async def test_async_database_operation_time(self):
        """Test how long async database operations take."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            start_time = time.time()
            
            db = async_env.db()
            result = await db.query("SELECT 1 as test")
            
            end_time = time.time()
            operation_time = end_time - start_time
            
            print(f"⏱️  Async database operation took: {operation_time:.2f} seconds")
            assert operation_time < 10, f"Async database operation took too long: {operation_time:.2f}s"
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_browser_operation_time(self):
        """Test how long async browser operations take."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            start_time = time.time()
            
            browser = async_env.browser()
            cdp_url = await browser.cdp_url()
            devtools_url = await browser.devtools_url()
            
            end_time = time.time()
            operation_time = end_time - start_time
            
            print(f"⏱️  Async browser operation took: {operation_time:.2f} seconds")
            assert operation_time < 10, f"Async browser operation took too long: {operation_time:.2f}s"
        finally:
            await async_env.close()


class TestFastOperations(BaseFleetTest):
    """Test fast operations that should be quick."""
    
    def test_fast_list_environments(self, fleet_client):
        """Test how long listing environments takes."""
        start_time = time.time()
        
        environments = fleet_client.list_envs()
        
        end_time = time.time()
        list_time = end_time - start_time
        
        print(f"⏱️  List environments took: {list_time:.2f} seconds")
        assert list_time < 5, f"List environments took too long: {list_time:.2f}s"
    
    def test_fast_list_regions(self, fleet_client):
        """Test how long listing regions takes."""
        start_time = time.time()
        
        regions = fleet_client.list_regions()
        
        end_time = time.time()
        list_time = end_time - start_time
        
        print(f"⏱️  List regions took: {list_time:.2f} seconds")
        assert list_time < 5, f"List regions took too long: {list_time:.2f}s"
    
    def test_fast_list_instances(self, fleet_client):
        """Test how long listing instances takes."""
        start_time = time.time()
        
        instances = fleet_client.instances()
        
        end_time = time.time()
        list_time = end_time - start_time
        
        print(f"⏱️  List instances took: {list_time:.2f} seconds")
        assert list_time < 20, f"List instances took too long: {list_time:.2f}s"
    
    def test_fast_account_info(self, fleet_client):
        """Test how long getting account info takes."""
        start_time = time.time()
        
        import fleet
        account = fleet.env.account()
        
        end_time = time.time()
        account_time = end_time - start_time
        
        print(f"⏱️  Account info took: {account_time:.2f} seconds")
        assert account_time < 5, f"Account info took too long: {account_time:.2f}s"
