import time
from typing import Dict, Optional, Type

from .config import GLOBAL_BASE_URL

try:
    from . import __version__
except ImportError:
    __version__ = "0.2.124"


class AuthenticatedWrapperMixin:
    _authentication_error_cls: Type[Exception] = RuntimeError

    def _init_auth(
        self,
        *,
        api_key: Optional[str],
        base_url: Optional[str],
        jwt: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        # Pin the auth mode at construction time so a half-configured JWT
        # client fails with the real configuration error instead of
        # falling back to `Authorization: Bearer None`.
        if jwt and team_id:
            self._auth_mode = "jwt"
        elif api_key:
            self._auth_mode = "api_key"
        else:
            raise ValueError("Provide api_key or both jwt and team_id")
        self.api_key = api_key
        self.jwt = jwt
        self.team_id = team_id
        self.base_url = base_url or GLOBAL_BASE_URL

    def get_headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "X-Fleet-SDK-Language": "Python",
            "X-Fleet-SDK-Version": __version__,
        }
        if self._auth_mode == "jwt":
            if not self.jwt or not self.team_id:
                raise self._authentication_error_cls(
                    "JWT auth was selected at init but jwt/team_id are no longer set"
                )
            headers["X-JWT-Token"] = self.jwt
            headers["X-Team-ID"] = self.team_id
        else:
            if not self.api_key:
                raise self._authentication_error_cls(
                    "API-key auth was selected at init but api_key is no longer set"
                )
            headers["Authorization"] = f"Bearer {self.api_key}"

        if request_id:
            headers["X-Request-ID"] = request_id

        headers["X-Request-Timestamp"] = str(int(time.time() * 1000))
        return headers
