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
    ) -> None:
        if not api_key:
            raise ValueError("Provide api_key")
        self.api_key = api_key
        self.base_url = base_url or GLOBAL_BASE_URL

    def get_headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "X-Fleet-SDK-Language": "Python",
            "X-Fleet-SDK-Version": __version__,
        }
        if not self.api_key:
            raise self._authentication_error_cls(
                "API-key auth was selected at init but api_key is no longer set"
            )
        headers["Authorization"] = f"Bearer {self.api_key}"

        if request_id:
            headers["X-Request-ID"] = request_id

        headers["X-Request-Timestamp"] = str(int(time.time() * 1000))
        return headers
