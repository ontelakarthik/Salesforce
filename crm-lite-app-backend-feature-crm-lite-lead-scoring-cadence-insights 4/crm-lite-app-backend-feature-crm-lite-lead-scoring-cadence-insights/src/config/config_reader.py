"""Single entry point for reading configuration.

Skeleton: returns a cached Settings instance. Extend here to layer in Azure
sources (App Configuration / Key Vault) before falling back to env/.env.
"""
from functools import lru_cache

from src.config.config import Settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # TODO(CLM-PLATFORM, @platform-team): if APP_ENV != "local", hydrate
    #       secrets from Azure Key Vault / App Configuration, then construct
    #       Settings.
    return Settings()


settings = get_settings()
