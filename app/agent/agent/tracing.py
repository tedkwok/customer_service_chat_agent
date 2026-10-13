import os

from langfuse import get_client
from langfuse.langchain import CallbackHandler

# The langfuse SDK reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY /
# LANGFUSE_BASE_URL directly from the environment (set via .env / env_file in
# docker-compose.yaml). setdefault keeps already-configured environments intact
# and guarantees the keys exist so the SDK never sees them undefined.
os.environ.setdefault("LANGFUSE_SECRET_KEY", "")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "")
os.environ.setdefault("LANGFUSE_BASE_URL", "")


langfuse_callback_handler = CallbackHandler()
