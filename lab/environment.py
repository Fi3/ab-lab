"""Common subscription-only environment for providers and verification commands."""
import os

BLOCKED = {"OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE",
           "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "CODEX_CHATGPT_BASE_URL"}

def clean_env(environment=None):
    return {k: v for k, v in (os.environ if environment is None else environment).items()
            if k not in BLOCKED}
