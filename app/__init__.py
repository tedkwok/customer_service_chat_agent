# Load a local .env file (if present) so the service can run outside docker.
# Inside docker the variables are injected via `env_file` in docker-compose.yaml
# and load_dotenv() is a no-op — real environment variables always win.
# This lives in the package __init__ because many modules (connection pools,
# llm_provider, vector_search, ...) read configuration from the environment at
# import time, so the .env file must be loaded before any of them is imported.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv not installed: rely on the real environment
    pass
