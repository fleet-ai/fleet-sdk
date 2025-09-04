"""
Test to verify the correct async pattern from examples.
"""

import pytest
from .base_test import BaseFleetTest


class TestAsyncPattern(BaseFleetTest):
    """Test the correct async pattern from examples."""
    
    @pytest.mark.asyncio
    async def test_correct_async_database_pattern(self, async_env):
        """Test correct async database pattern from examples."""
        # Correct pattern: first get resource, then await method
        db = async_env.db()  # Get resource (no await)
        result = await db.query("SELECT 1 as test")  # Await method
        
        assert result is not None
        print("✅ Correct async database pattern works")
    
    @pytest.mark.asyncio
    async def test_correct_async_browser_pattern(self, async_env):
        """Test correct async browser pattern from examples."""
        # Correct pattern: first get resource, then await method
        browser = async_env.browser()  # Get resource (no await)
        cdp_url = await browser.cdp_url()  # Await method
        devtools_url = await browser.devtools_url()  # Await method
        
        assert cdp_url is not None
        assert devtools_url is not None
        print("✅ Correct async browser pattern works")
    
    @pytest.mark.asyncio
    async def test_correct_async_database_describe_pattern(self, async_env):
        """Test correct async database describe pattern from examples."""
        # Correct pattern: first get resource, then await method
        db = async_env.db()  # Get resource (no await)
        schema = await db.describe()  # Await method
        
        assert schema is not None
        print("✅ Correct async database describe pattern works")
    
    @pytest.mark.asyncio
    async def test_correct_async_database_exec_pattern(self, async_env):
        """Test correct async database exec pattern from examples."""
        # Correct pattern: first get resource, then await method
        db = async_env.db()  # Get resource (no await)
        result = await db.exec("SELECT 1 as test")  # Await method
        
        assert result is not None
        print("✅ Correct async database exec pattern works")
    
    @pytest.mark.asyncio
    async def test_correct_async_database_with_args_pattern(self, async_env):
        """Test correct async database with args pattern from examples."""
        # Correct pattern: first get resource, then await method
        db = async_env.db()  # Get resource (no await)
        result = await db.query("SELECT ? as test_value", args=["test_data"])  # Await method
        
        assert result is not None
        print("✅ Correct async database with args pattern works")
    
    @pytest.mark.asyncio
    async def test_correct_async_state_pattern(self, async_env):
        """Test correct async state pattern from examples."""
        # Correct pattern: first get resource, then await method
        db = async_env.state("sqlite://current")  # Get resource (no await)
        schema = await db.describe()  # Await method
        
        assert schema is not None
        print("✅ Correct async state pattern works")
    
    @pytest.mark.asyncio
    async def test_correct_async_specific_db_pattern(self, async_env):
        """Test correct async specific db pattern from examples."""
        # Correct pattern: first get resource, then await method
        db = async_env.db("action_log")  # Get resource (no await)
        result = await db.query("SELECT 1 as test")  # Await method
        
        assert result is not None
        print("✅ Correct async specific db pattern works")
