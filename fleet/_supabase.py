# Placeholder values are replaced at build time by the publish workflow.
# For local development, set SUPABASE_URL and SUPABASE_ANON_KEY env vars.
import os

SUPABASE_URL = os.environ.get("SUPABASE_URL", "%%SUPABASE_URL%%")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "%%SUPABASE_ANON_KEY%%")
