# Supabase refresh is a temporary compatibility path for browser-login
# credentials. Values must come from the runtime environment; do not bake them
# into published distributions.
import os

_PLACEHOLDER_URL = "%%SUPABASE_URL%%"
_PLACEHOLDER_ANON_KEY = "%%SUPABASE_ANON_KEY%%"

SUPABASE_URL = os.environ.get("SUPABASE_URL", _PLACEHOLDER_URL)
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", _PLACEHOLDER_ANON_KEY)


def is_configured() -> bool:
    """True if Supabase credentials are present and not the build-time
    placeholders. Callers should check this before issuing requests so
    we surface a clear "not configured" error instead of trying to POST
    to a literal `%%SUPABASE_URL%%/...` and getting a cryptic DNS or
    connection error from httpx."""
    return (
        bool(SUPABASE_URL)
        and SUPABASE_URL != _PLACEHOLDER_URL
        and bool(SUPABASE_ANON_KEY)
        and SUPABASE_ANON_KEY != _PLACEHOLDER_ANON_KEY
    )
