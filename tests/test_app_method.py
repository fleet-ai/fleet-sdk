"""Unit tests for SyncEnv.app() method URL handling."""

import pytest
from unittest.mock import Mock, patch
from fleet.client import Fleet


class TestAppMethod:
    """Test SyncEnv.app() method with different URL formats."""

    @pytest.fixture
    def fleet_client(self):
        """Create a Fleet client with mocked HTTP client."""
        with patch("fleet.client.default_httpx_client") as mock_client:
            mock_client.return_value = Mock()
            client = Fleet(api_key="test_key")
            client.client.request = Mock()
            return client

    def test_app_with_existing_app_path(self, fleet_client):
        """Test app() with URL that already has an app path like /sentry."""
        # Create instance with a URL that has an existing app path
        env = fleet_client.instance("https://example.com/sentry/api/v1/env")

        # Access jira app
        jira_client = env.app("jira")

        # Check the constructed URL
        assert jira_client.base_url == "https://example.com/jira/api/v1/env", \
            f"Expected https://example.com/jira/api/v1/env, got {jira_client.base_url}"

    def test_app_without_app_path(self, fleet_client):
        """Test app() with URL that has no app path (just /api/v1/env)."""
        # Create instance with a URL without an app path
        env = fleet_client.instance("https://example.com/api/v1/env")

        # Access jira app
        jira_client = env.app("jira")

        # Check the constructed URL
        assert jira_client.base_url == "https://example.com/jira/api/v1/env", \
            f"Expected https://example.com/jira/api/v1/env, got {jira_client.base_url}"

    def test_app_with_different_app_names(self, fleet_client):
        """Test app() with multiple different app names."""
        env = fleet_client.instance("https://example.com/api/v1/env")

        jira = env.app("jira")
        sentry = env.app("sentry")
        github = env.app("github")

        assert jira.base_url == "https://example.com/jira/api/v1/env"
        assert sentry.base_url == "https://example.com/sentry/api/v1/env"
        assert github.base_url == "https://example.com/github/api/v1/env"

    def test_app_caching(self, fleet_client):
        """Test that app() caches InstanceClient instances."""
        env = fleet_client.instance("https://example.com/api/v1/env")

        # Call app("jira") twice
        jira1 = env.app("jira")
        jira2 = env.app("jira")

        # Should return the same cached instance
        assert jira1 is jira2

    def test_app_with_localhost(self, fleet_client):
        """Test app() with localhost URLs."""
        env = fleet_client.instance("http://localhost:8080/api/v1/env")

        jira = env.app("jira")

        assert jira.base_url == "http://localhost:8080/jira/api/v1/env"

    def test_app_with_port(self, fleet_client):
        """Test app() with URLs that include port numbers."""
        env = fleet_client.instance("https://example.com:9000/api/v1/env")

        jira = env.app("jira")

        assert jira.base_url == "https://example.com:9000/jira/api/v1/env"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
