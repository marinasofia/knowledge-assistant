import pytest

from app.config import Settings


def test_production_rejects_demo_identity():
    with pytest.raises(ValueError):
        Settings(env="production", dev_auth=True)


def test_live_mode_requires_credentials():
    with pytest.raises(ValueError):
        Settings(generation_mode="anthropic", anthropic_api_key="")
