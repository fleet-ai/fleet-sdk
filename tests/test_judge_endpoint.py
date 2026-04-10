"""Tests for JudgeEndpointConfig and judge_endpoint integration."""

import json
import os
from unittest.mock import patch, Mock, MagicMock

import pytest

from fleet.models import JudgeEndpointConfig, JobCreateRequest


class TestJudgeEndpointConfig:
    """Test JudgeEndpointConfig model creation and validation."""

    def test_minimal_config(self):
        config = JudgeEndpointConfig(url="https://my-llm.internal/v1")
        assert config.url == "https://my-llm.internal/v1"
        assert config.api_key is None
        assert config.model is None
        assert config.api_format == "openai"

    def test_full_config(self):
        config = JudgeEndpointConfig(
            url="https://my-llm.internal/v1",
            api_key="sk-test-123",
            model="gpt-4o",
            api_format="openai",
        )
        assert config.url == "https://my-llm.internal/v1"
        assert config.api_key == "sk-test-123"
        assert config.model == "gpt-4o"
        assert config.api_format == "openai"

    def test_anthropic_format(self):
        config = JudgeEndpointConfig(
            url="https://my-llm.internal/v1",
            api_format="anthropic",
        )
        assert config.api_format == "anthropic"

    def test_invalid_api_format(self):
        with pytest.raises(Exception):
            JudgeEndpointConfig(
                url="https://my-llm.internal/v1",
                api_format="invalid",
            )

    def test_url_required(self):
        with pytest.raises(Exception):
            JudgeEndpointConfig()

    def test_serialization(self):
        config = JudgeEndpointConfig(
            url="https://my-llm.internal/v1",
            api_key="sk-test",
            model="gpt-4o",
            api_format="anthropic",
        )
        data = config.model_dump()
        assert data == {
            "url": "https://my-llm.internal/v1",
            "api_key": "sk-test",
            "model": "gpt-4o",
            "api_format": "anthropic",
        }


class TestJobCreateRequestWithJudgeEndpoint:
    """Test JudgeEndpointConfig in JobCreateRequest."""

    def test_job_request_without_judge(self):
        req = JobCreateRequest(models=["anthropic/claude-sonnet-4"])
        assert req.judge_endpoint is None
        dumped = req.model_dump(exclude_none=True)
        assert "judge_endpoint" not in dumped

    def test_job_request_with_judge(self):
        judge = JudgeEndpointConfig(
            url="https://my-llm.internal/v1",
            api_key="sk-test",
            model="gpt-4o",
        )
        req = JobCreateRequest(
            models=["anthropic/claude-sonnet-4"],
            judge_endpoint=judge,
        )
        assert req.judge_endpoint is not None
        dumped = req.model_dump(exclude_none=True)
        assert "judge_endpoint" in dumped
        assert dumped["judge_endpoint"]["url"] == "https://my-llm.internal/v1"

    def test_backward_compat_no_judge(self):
        """Existing code that doesn't pass judge_endpoint should work identically."""
        req = JobCreateRequest(
            models=["google/gemini-2.5-pro"],
            name="test-job",
            pass_k=1,
            project_key="my-project",
        )
        dumped = req.model_dump(exclude_none=True)
        assert "judge_endpoint" not in dumped
        assert dumped["models"] == ["google/gemini-2.5-pro"]


class TestFleetCreateJobJudgeEndpoint:
    """Test Fleet.create_job() passes judge_endpoint through correctly."""

    @pytest.fixture
    def fleet_client(self):
        """Create a Fleet client with mocked HTTP client."""
        with patch("fleet.client.default_httpx_client") as mock_factory:
            mock_factory.return_value = Mock()
            from fleet.client import Fleet

            client = Fleet(api_key="test-key", base_url="https://test.com")
            # Mock the wrapper's request method
            mock_response = Mock()
            mock_response.json.return_value = {
                "job_id": "test-123",
                "status": "pending",
            }
            mock_response.status_code = 200
            client.client.request = Mock(return_value=mock_response)
            return client

    def test_create_job_with_judge_endpoint(self, fleet_client):
        judge = JudgeEndpointConfig(url="https://judge.internal/v1", model="gpt-4o")
        result = fleet_client.create_job(
            models=["anthropic/claude-sonnet-4"],
            project_key="test-project",
            judge_endpoint=judge,
        )

        fleet_client.client.request.assert_called_once()
        call_kwargs = fleet_client.client.request.call_args
        body = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs["json"]
        assert "judge_endpoint" in body
        assert body["judge_endpoint"]["url"] == "https://judge.internal/v1"
        assert body["judge_endpoint"]["model"] == "gpt-4o"

    def test_create_job_without_judge_endpoint(self, fleet_client):
        result = fleet_client.create_job(
            models=["anthropic/claude-sonnet-4"],
            project_key="test-project",
        )

        fleet_client.client.request.assert_called_once()
        call_kwargs = fleet_client.client.request.call_args
        body = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs["json"]
        assert "judge_endpoint" not in body

    def test_create_job_falls_back_to_instance_judge(self):
        """When create_job is called without judge_endpoint, falls back to self.judge_endpoint."""
        with patch("fleet.client.default_httpx_client") as mock_factory:
            mock_factory.return_value = Mock()
            from fleet.client import Fleet

            judge = JudgeEndpointConfig(url="https://judge.internal/v1")
            client = Fleet(
                api_key="test-key",
                base_url="https://test.com",
                judge_endpoint=judge,
            )
            mock_response = Mock()
            mock_response.json.return_value = {
                "job_id": "test-123",
                "status": "pending",
            }
            mock_response.status_code = 200
            client.client.request = Mock(return_value=mock_response)

            result = client.create_job(
                models=["anthropic/claude-sonnet-4"],
                project_key="test-project",
            )

            client.client.request.assert_called_once()
            call_kwargs = client.client.request.call_args
            body = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs["json"]
            assert "judge_endpoint" in body
            assert body["judge_endpoint"]["url"] == "https://judge.internal/v1"


class TestConfigureJudgeEndpoint:
    """Test fleet.configure(judge_endpoint=...) stores config."""

    @patch("fleet._async.client.default_httpx_client")
    def test_configure_stores_judge_endpoint(self, mock_async_httpx):
        mock_async_httpx.return_value = MagicMock()
        import fleet
        from fleet._async import global_client as _agc

        judge = JudgeEndpointConfig(url="https://judge.internal/v1")
        # Configure sync only (async has a pre-existing jwt bug unrelated to this change)
        from fleet import global_client as _gc

        _gc.configure(api_key="test-key", judge_endpoint=judge)
        client = _gc.get_client()
        assert client.judge_endpoint is not None
        assert client.judge_endpoint.url == "https://judge.internal/v1"
        _gc.reset_client()

    @patch("fleet._async.client.default_httpx_client")
    def test_configure_without_judge_endpoint(self, mock_async_httpx):
        mock_async_httpx.return_value = MagicMock()
        from fleet import global_client as _gc

        _gc.configure(api_key="test-key")
        client = _gc.get_client()
        assert client.judge_endpoint is None
        _gc.reset_client()


class TestEnvVarFallback:
    """Test env var fallback (FLEET_JUDGE_ENDPOINT etc.)."""

    @patch.dict(
        os.environ,
        {
            "FLEET_JUDGE_ENDPOINT": "https://env-judge.internal/v1",
            "FLEET_JUDGE_API_KEY": "env-key-123",
            "FLEET_JUDGE_MODEL": "gpt-4o",
            "FLEET_JUDGE_API_FORMAT": "anthropic",
        },
    )
    @patch("fleet.client.default_httpx_client")
    def test_env_vars_construct_config(self, mock_httpx_factory):
        mock_httpx_factory.return_value = Mock()
        from fleet.client import Fleet

        client = Fleet(api_key="test-key", base_url="https://test.com")
        assert client.judge_endpoint is not None
        assert client.judge_endpoint.url == "https://env-judge.internal/v1"
        assert client.judge_endpoint.api_key == "env-key-123"
        assert client.judge_endpoint.model == "gpt-4o"
        assert client.judge_endpoint.api_format == "anthropic"

    @patch("fleet.client.default_httpx_client")
    def test_env_var_minimal(self, mock_httpx_factory):
        """Only FLEET_JUDGE_ENDPOINT is required."""
        mock_httpx_factory.return_value = Mock()
        env_clean = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("FLEET_JUDGE_")
        }
        with patch.dict(os.environ, env_clean, clear=True):
            os.environ["FLEET_JUDGE_ENDPOINT"] = "https://env-judge.internal/v1"
            from fleet.client import Fleet

            client = Fleet(api_key="test-key", base_url="https://test.com")
            assert client.judge_endpoint is not None
            assert client.judge_endpoint.url == "https://env-judge.internal/v1"
            assert client.judge_endpoint.api_key is None
            assert client.judge_endpoint.model is None
            assert client.judge_endpoint.api_format == "openai"

    @patch("fleet.client.default_httpx_client")
    def test_explicit_overrides_env_var(self, mock_httpx_factory):
        """Explicit judge_endpoint takes precedence over env vars."""
        mock_httpx_factory.return_value = Mock()

        with patch.dict(
            os.environ,
            {"FLEET_JUDGE_ENDPOINT": "https://env-judge.internal/v1"},
        ):
            from fleet.client import Fleet

            explicit = JudgeEndpointConfig(url="https://explicit.internal/v1")
            client = Fleet(
                api_key="test-key",
                base_url="https://test.com",
                judge_endpoint=explicit,
            )
            assert client.judge_endpoint.url == "https://explicit.internal/v1"

    @patch("fleet.client.default_httpx_client")
    def test_no_env_var_no_config(self, mock_httpx_factory):
        """Without env vars or explicit config, judge_endpoint is None."""
        mock_httpx_factory.return_value = Mock()
        env_clean = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("FLEET_JUDGE_")
        }
        with patch.dict(os.environ, env_clean, clear=True):
            from fleet.client import Fleet

            client = Fleet(api_key="test-key", base_url="https://test.com")
            assert client.judge_endpoint is None


class TestAsyncFleetJudgeEndpoint:
    """Test AsyncFleet judge_endpoint attribute."""

    @patch("fleet._async.base.AsyncWrapper.__init__", return_value=None)
    @patch("fleet._async.client.default_httpx_client")
    def test_async_fleet_stores_judge_endpoint(self, mock_httpx_factory, mock_wrapper_init):
        mock_httpx_factory.return_value = MagicMock()

        from fleet._async.client import AsyncFleet

        judge = JudgeEndpointConfig(url="https://judge.internal/v1")
        client = AsyncFleet(
            api_key="test-key",
            base_url="https://test.com",
            judge_endpoint=judge,
        )
        assert client.judge_endpoint is not None
        assert client.judge_endpoint.url == "https://judge.internal/v1"

    @patch.dict(
        os.environ,
        {
            "FLEET_JUDGE_ENDPOINT": "https://env-judge.internal/v1",
            "FLEET_JUDGE_API_KEY": "env-key-123",
        },
    )
    @patch("fleet._async.base.AsyncWrapper.__init__", return_value=None)
    @patch("fleet._async.client.default_httpx_client")
    def test_async_fleet_env_var_fallback(self, mock_httpx_factory, mock_wrapper_init):
        mock_httpx_factory.return_value = MagicMock()

        from fleet._async.client import AsyncFleet

        client = AsyncFleet(api_key="test-key", base_url="https://test.com")
        assert client.judge_endpoint is not None
        assert client.judge_endpoint.url == "https://env-judge.internal/v1"
        assert client.judge_endpoint.api_key == "env-key-123"
