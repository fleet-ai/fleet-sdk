"""Fleet SDK Configuration Management."""

import os
import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from .exceptions import FleetAuthenticationError, FleetConfigurationError


logger = logging.getLogger(__name__)


class FleetConfig(BaseModel):
    """Fleet SDK Configuration."""
    
    api_key: Optional[str] = Field(None, description="Fleet API key")
    base_url: str = Field(default="https://fleet.new", description="Fleet API base URL (hardcoded)")
    
    @validator('api_key')
    def validate_api_key(cls, v):
        """Validate API key format."""
        if v is not None and not _is_valid_api_key(v):
            raise FleetAuthenticationError(
                "Invalid API key format. Fleet API keys should start with 'sk_' followed by alphanumeric characters."
            )
        return v
    
    @validator('base_url')
    def validate_base_url(cls, v):
        """Validate base URL format."""
        if not v.startswith(('http://', 'https://')):
            raise FleetConfigurationError("Base URL must start with 'http://' or 'https://'")
        return v.rstrip('/')
    
    def mask_sensitive_data(self) -> Dict[str, Any]:
        """Return config dict with sensitive data masked."""
        data = self.dict()
        if data.get('api_key'):
            data['api_key'] = _mask_api_key(data['api_key'])
        return data
    
    class Config:
        """Pydantic configuration."""
        extra = 'allow'


def get_config(**kwargs: Any) -> FleetConfig:
    """Get Fleet configuration from environment variables.
    
    Loads FLEET_API_KEY from environment variables. The base URL is hardcoded to https://fleet.new.
    
    Args:
        **kwargs: Override specific configuration values
        
    Returns:
        FleetConfig instance
        
    Raises:
        FleetAuthenticationError: If API key is invalid
        FleetConfigurationError: If configuration is invalid
    """
    # Load from environment variables
    config_data = _load_env_config()
    
    # Apply any overrides
    config_data.update(kwargs)
    
    # Create and validate configuration
    try:
        config = FleetConfig(**config_data)
        return config
        
    except Exception as e:
        if isinstance(e, (FleetAuthenticationError, FleetConfigurationError)):
            raise
        raise FleetConfigurationError(f"Invalid configuration: {e}")


def _load_env_config() -> Dict[str, Any]:
    """Load configuration from environment variables."""
    env_mapping = {
        'FLEET_API_KEY': 'api_key',
        # base_url is hardcoded, not configurable via env var
    }
    
    config = {}
    for env_var, config_key in env_mapping.items():
        value = os.getenv(env_var)
        if value is not None:
            config[config_key] = value
    
    return config


def _is_valid_api_key(api_key: str) -> bool:
    """Validate API key format."""
    if not api_key:
        return False
    
    # Fleet API keys start with 'sk_' followed by alphanumeric characters
    # This is a basic format check - actual validation happens on the server
    if not api_key.startswith('sk_'):
        return False
    
    # Check if the rest contains only alphanumeric characters and underscores
    key_part = api_key[3:]  # Remove 'sk_' prefix
    if not key_part or not key_part.replace('_', '').isalnum():
        return False
    
    # Minimum length check
    if len(api_key) < 20:
        return False
    
    return True


def _mask_api_key(api_key: str) -> str:
    """Mask API key for logging."""
    if not api_key:
        return api_key
    
    if len(api_key) < 8:
        return '*' * len(api_key)
    
    return api_key[:4] + '*' * (len(api_key) - 8) + api_key[-4:] 