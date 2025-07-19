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


class FleetInstanceLimitError(FleetAPIError):
    """Exception raised when team instance limit is exceeded."""

    def __init__(
        self,
        message: str = "Instance limit exceeded",
        running_instances: Optional[int] = None,
        instance_limit: Optional[int] = None,
    ):
        super().__init__(message, status_code=403)
        self.running_instances = running_instances
        self.instance_limit = instance_limit


class FleetBadRequestError(FleetAPIError):
    """Exception raised for bad request errors (400)."""

    def __init__(self, message: str, error_type: Optional[str] = None):
        super().__init__(message, status_code=400)
        self.error_type = error_type


class FleetPermissionError(FleetAPIError):
    """Exception raised when permission is denied (403)."""

    def __init__(
        self,
        message: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
    ):
        super().__init__(message, status_code=403)
        self.resource_type = resource_type
        self.resource_id = resource_id


class FleetRegionError(FleetBadRequestError):
    """Exception raised when an unsupported region is specified."""

    def __init__(
        self,
        message: str,
        region: Optional[str] = None,
        supported_regions: Optional[list] = None,
    ):
        super().__init__(message, error_type="unsupported_region")
        self.region = region
        self.supported_regions = supported_regions or []


class FleetEnvironmentNotFoundError(FleetBadRequestError):
    """Exception raised when environment is not found."""

    def __init__(self, message: str, env_key: Optional[str] = None):
        super().__init__(message, error_type="environment_not_found")
        self.env_key = env_key


class FleetVersionNotFoundError(FleetBadRequestError):
    """Exception raised when version is not found."""

    def __init__(
        self, message: str, env_key: Optional[str] = None, version: Optional[str] = None
    ):
        super().__init__(message, error_type="version_not_found")
        self.env_key = env_key
        self.version = version


class FleetEnvironmentAccessError(FleetPermissionError):
    """Exception raised when team doesn't have access to an environment."""

    def __init__(
        self, message: str, env_key: Optional[str] = None, version: Optional[str] = None
    ):
        super().__init__(message, resource_type="environment", resource_id=env_key)
        self.env_key = env_key
        self.version = version


class FleetTeamNotFoundError(FleetPermissionError):
    """Exception raised when team is not found."""

    def __init__(self, message: str, team_id: Optional[str] = None):
        super().__init__(message, resource_type="team", resource_id=team_id)
        self.team_id = team_id


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
