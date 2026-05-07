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
        jwt: Optional[str] = None,
        team_id: Optional[str] = None,
        base_url: Optional[str],
    ) -> None:
        self._uses_stored_login_auth = False
        if not api_key and not (jwt and team_id):
            from .auth import get_valid_token

            token_info = get_valid_token()
            if token_info:
                jwt, team_id = token_info
                self._uses_stored_login_auth = True

        if not api_key and not (jwt and team_id):
            raise ValueError("Provide api_key, provide jwt/team_id, or run `flt login`")
        self.api_key = api_key
        self.jwt = jwt
        self.team_id = team_id
        self.base_url = base_url or GLOBAL_BASE_URL

    def get_headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "X-Fleet-SDK-Language": "Python",
            "X-Fleet-SDK-Version": __version__,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.jwt and self.team_id:
            if getattr(self, "_uses_stored_login_auth", False):
                from .auth import get_valid_token

                token_info = get_valid_token()
                if not token_info:
                    raise self._authentication_error_cls(
                        "Stored login credentials are expired; run `flt login` again"
                    )
                self.jwt, self.team_id = token_info
            headers["X-JWT-Token"] = self.jwt
            headers["X-Team-ID"] = self.team_id
        else:
            raise self._authentication_error_cls(
                "Authentication is not configured; set FLEET_API_KEY or run `flt login`"
            )

        if request_id:
            headers["X-Request-ID"] = request_id

        headers["X-Request-Timestamp"] = str(int(time.time() * 1000))
        return headers
