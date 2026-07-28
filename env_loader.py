"""Environment variable loader with .env support.

This module:
1. Loads environment variables from .env file if present
2. Validates required configuration on startup
3. Provides helpful error messages for missing config
"""
import os
from pathlib import Path
from typing import Optional


def load_env_file():
    """Load environment variables from .env file if it exists."""
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                # Parse KEY=VALUE
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Only set if not already in environment
                    if key not in os.environ:
                        os.environ[key] = value


def get_api_key() -> Optional[str]:
    """Get the configured LLM API key (Anthropic preferred)."""
    return (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )


def get_provider_preference() -> Optional[str]:
    """Get the explicit LLM provider preference, if set."""
    return os.environ.get("MERIDIAN_LLM_PROVIDER", "").strip().lower() or None


def get_model_override() -> Optional[str]:
    """Get the model override, if set."""
    return os.environ.get("MERIDIAN_LLM_MODEL", "").strip() or None


def startup_check() -> dict:
    """Run startup validation and return diagnostics.

    Returns:
        dict with keys: api_key_present, provider_available, model_info, errors
    """
    load_env_file()

    diagnostics = {
        "api_key_present": bool(get_api_key()),
        "provider_preference": get_provider_preference(),
        "model_override": get_model_override(),
        "errors": [],
    }

    # Try to detect LLM availability
    try:
        import llm_layer
        diagnostics["llm_available"] = llm_layer.is_llm_available()
        diagnostics["provider"] = llm_layer.provider()
        diagnostics["model"] = llm_layer.model_name()
        diagnostics["provider_label"] = llm_layer.provider_label()
    except Exception as e:
        diagnostics["llm_available"] = False
        diagnostics["provider"] = None
        diagnostics["errors"].append(f"Failed to check LLM: {e}")

    return diagnostics


if __name__ == "__main__":
    # Test the loader
    startup_check()
    load_env_file()
    diagnostics = startup_check()
    print(f"API Key Present: {diagnostics['api_key_present']}")
    print(f"LLM Available: {diagnostics['llm_available']}")
    print(f"Provider: {diagnostics.get('provider_label', 'none')}")
    if diagnostics["errors"]:
        print(f"Errors: {diagnostics['errors']}")
