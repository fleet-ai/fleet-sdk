"""
Tests for environment management functionality.
Based on examples/quickstart.py, examples/example.py, examples/example_client.py, examples/example_sync.py
"""

import pytest
from .base_test import BaseEnvironmentTest, BaseFleetTest


class TestEnvironmentManagement(BaseEnvironmentTest):
    """Test environment management functionality."""
    
    def test_list_environments(self, fleet_client):
        """Test listing available environments."""
        environments = fleet_client.list_envs()
        self.assert_environment_list(environments)
        print(f"✅ Found {len(environments)} environments")
    
    def test_list_regions(self, fleet_client):
        """Test listing available regions."""
        regions = fleet_client.list_regions()
        assert isinstance(regions, list)
        assert len(regions) > 0
        assert "us-west-1" in regions  # Based on user's specified regions
        print(f"✅ Found {len(regions)} regions: {regions}")
    
    def test_list_instances(self, fleet_client):
        """Test listing instances."""
        instances = fleet_client.instances()
        assert isinstance(instances, list)
        print(f"✅ Found {len(instances)} instances")
    
    def test_list_running_instances(self, fleet_client):
        """Test listing running instances."""
        instances = fleet_client.instances(status="running")
        assert isinstance(instances, list)
        print(f"✅ Found {len(instances)} running instances")
    
    def test_environment_creation_with_version(self, fleet_client):
        """Test environment creation with specific version."""
        env = fleet_client.make("dropbox:Forge1.1.0")
        self.assert_instance_valid(env)
        assert env.env_key == "dropbox"
        assert "Forge1.1.0" in env.version
        print(f"✅ Created environment with version: {env.instance_id}")
    
    def test_environment_creation_with_region(self, fleet_client):
        """Test environment creation with specific region."""
        env = fleet_client.make("hubspot:Forge1.1.0", region="us-west-1")
        self.assert_instance_valid(env)
        assert env.env_key == "hubspot"
        assert env.region == "us-west-1"
        print(f"✅ Created environment with region: {env.instance_id}")
    
    def test_connect_to_existing_instance(self, fleet_client):
        """Test connecting to existing instance."""
        # First create an instance
        env = fleet_client.make("ramp:Forge1.1.0")
        instance_id = env.instance_id
        
        # Then connect to it
        reconnected_env = fleet_client.instance(instance_id)
        self.assert_instance_valid(reconnected_env)
        assert reconnected_env.instance_id == instance_id
        print(f"✅ Connected to existing instance: {instance_id}")
    
    def test_environment_urls(self, env):
        """Test environment URL access."""
        assert hasattr(env, 'urls')
        assert hasattr(env.urls, 'app')
        assert hasattr(env.urls, 'manager')
        assert env.urls.app is not None
        print(f"✅ Environment URLs accessible: {env.urls.app}")


class TestFleetEnvFunctions(BaseFleetTest):
    """Test fleet.env public API functions."""
    
    def test_fleet_env_list_envs(self):
        """Test fleet.env.list_envs() function."""
        import fleet
        environments = fleet.env.list_envs()
        self.assert_environment_list(environments)
        print(f"✅ fleet.env.list_envs() works: {len(environments)} environments")
    
    def test_fleet_env_list_regions(self):
        """Test fleet.env.list_regions() function."""
        import fleet
        regions = fleet.env.list_regions()
        assert isinstance(regions, list)
        assert len(regions) > 0
        print(f"✅ fleet.env.list_regions() works: {regions}")
    
    def test_fleet_env_list_instances(self):
        """Test fleet.env.list_instances() function."""
        import fleet
        instances = fleet.env.list_instances()
        assert isinstance(instances, list)
        print(f"✅ fleet.env.list_instances() works: {len(instances)} instances")
    
    def test_fleet_env_make(self):
        """Test fleet.env.make() function."""
        import fleet
        env = fleet.env.make("dropbox:Forge1.1.0")
        self.assert_instance_valid(env)
        assert env.env_key == "dropbox"
        print(f"✅ fleet.env.make() works: {env.instance_id}")
    
    def test_fleet_env_account(self):
        """Test fleet.env.account() function."""
        import fleet
        account = fleet.env.account()
        assert hasattr(account, 'team_id')
        assert hasattr(account, 'team_name')
        assert hasattr(account, 'instance_limit')
        assert hasattr(account, 'instance_count')
        print(f"✅ fleet.env.account() works: Team {account.team_name}")


class TestAsyncEnvironmentManagement(BaseEnvironmentTest):
    """Test async environment management functionality."""
    
    @pytest.mark.asyncio
    async def test_async_list_environments(self, async_fleet_client):
        """Test async listing of environments."""
        environments = await async_fleet_client.list_envs()
        self.assert_environment_list(environments)
        print(f"✅ Async list environments: {len(environments)} found")
    
    @pytest.mark.asyncio
    async def test_async_list_regions(self, async_fleet_client):
        """Test async listing of regions."""
        regions = await async_fleet_client.list_regions()
        assert isinstance(regions, list)
        assert len(regions) > 0
        print(f"✅ Async list regions: {regions}")
    
    @pytest.mark.asyncio
    async def test_async_list_instances(self, async_fleet_client):
        """Test async listing of instances."""
        instances = await async_fleet_client.instances()
        assert isinstance(instances, list)
        print(f"✅ Async list instances: {len(instances)} found")
    
    @pytest.mark.asyncio
    async def test_async_environment_creation(self, async_fleet_client):
        """Test async environment creation."""
        env = await async_fleet_client.make("hubspot:Forge1.1.0")
        self.assert_instance_valid(env)
        assert env.env_key == "hubspot"
        print(f"✅ Async environment creation: {env.instance_id}")
    
    @pytest.mark.asyncio
    async def test_async_connect_to_instance(self, async_fleet_client):
        """Test async connection to existing instance."""
        # Create instance
        env = await async_fleet_client.make("ramp:Forge1.1.0")
        instance_id = env.instance_id
        
        # Connect to it
        reconnected_env = await async_fleet_client.instance(instance_id)
        self.assert_instance_valid(reconnected_env)
        assert reconnected_env.instance_id == instance_id
        print(f"✅ Async connect to instance: {instance_id}")


class TestFleetEnvAsyncFunctions(BaseFleetTest):
    """Test fleet.env async public API functions."""
    
    @pytest.mark.asyncio
    async def test_fleet_env_list_envs_async(self):
        """Test fleet.env.list_envs_async() function."""
        import fleet
        environments = await fleet.env.list_envs_async()
        self.assert_environment_list(environments)
        print(f"✅ fleet.env.list_envs_async() works: {len(environments)} environments")
    
    @pytest.mark.asyncio
    async def test_fleet_env_list_regions_async(self):
        """Test fleet.env.list_regions_async() function."""
        import fleet
        regions = await fleet.env.list_regions_async()
        assert isinstance(regions, list)
        assert len(regions) > 0
        print(f"✅ fleet.env.list_regions_async() works: {regions}")
    
    @pytest.mark.asyncio
    async def test_fleet_env_make_async(self):
        """Test fleet.env.make_async() function."""
        import fleet
        env = await fleet.env.make_async("dropbox:Forge1.1.0")
        self.assert_instance_valid(env)
        assert env.env_key == "dropbox"
        print(f"✅ fleet.env.make_async() works: {env.instance_id}")
