"""Fleet SDK Exception Classes."""

from typing import Any, Dict, Optional


class FleetError(Exception):
    """Base exception for all Fleet SDK errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class FleetAPIError(FleetError):
    """Exception raised when Fleet API returns an error."""
    
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details)
        self.status_code = status_code
        self.response_data = response_data or {}


class FleetTimeoutError(FleetError):
    """Exception raised when a Fleet operation times out."""
    
    def __init__(self, message: str, timeout_duration: Optional[float] = None):
        super().__init__(message)
        self.timeout_duration = timeout_duration


class FleetAuthenticationError(FleetAPIError):
    """Exception raised when authentication fails."""
    
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=401)


class FleetRateLimitError(FleetAPIError):
    """Exception raised when rate limit is exceeded."""
    
    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, status_code=429)


class FleetEnvironmentError(FleetError):
    """Exception raised when environment operations fail."""
    
    def __init__(self, message: str, environment_id: Optional[str] = None):
        super().__init__(message)
        self.environment_id = environment_id


class FleetFacetError(FleetError):
    """Exception raised when facet operations fail."""
    
    def __init__(self, message: str, facet_type: Optional[str] = None):
        super().__init__(message)
        self.facet_type = facet_type


class FleetConfigurationError(FleetError):
    """Exception raised when configuration is invalid."""
    
    def __init__(self, message: str, config_key: Optional[str] = None):
        super().__init__(message)
        self.config_key = config_key 