"""Provider registry tests (§18.2)."""

from __future__ import annotations

import pytest

from gltg.evaluator.config import load_settings
from gltg.evaluator.provider_registry import SUPPORTED_PROVIDERS, get_provider
from gltg.evaluator.providers.base import ProviderError


def test_default_config_selects_local_reference_model(monkeypatch):
    for var in ("GLTG_EVALUATOR_MODE", "GLTG_LLM_PROVIDER", "GLTG_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    settings = load_settings()
    # qwen3.5-9b-int4 is the default *reference* model (not a designated
    # model), served through the local OpenAI-compatible provider so the
    # default carries no Qwen-ecosystem or external-service dependency.
    assert settings.provider == "local"
    assert settings.model == "qwen3.5-9b-int4"
    # Stage 3: the default mode is deterministic; LLM evaluation is strictly
    # explicit opt-in.
    assert settings.evaluator_mode == "deterministic"
    assert settings.is_deterministic_mode
    provider = get_provider(settings)
    assert provider.provider_name == "local"


def test_openai_compatible_selected(monkeypatch):
    monkeypatch.setenv("GLTG_LLM_PROVIDER", "openai_compatible")
    provider = get_provider(load_settings())
    assert provider.provider_name == "openai_compatible"


def test_mock_selected(monkeypatch):
    monkeypatch.setenv("GLTG_LLM_PROVIDER", "mock")
    provider = get_provider(load_settings())
    assert provider.provider_name == "mock"


@pytest.mark.parametrize("name", ["anthropic", "gemini", "deepseek", "local"])
def test_other_adapters_resolve(monkeypatch, name):
    monkeypatch.setenv("GLTG_LLM_PROVIDER", name)
    provider = get_provider(load_settings())
    assert provider.provider_name == name


def test_mock_mode_overrides_provider(monkeypatch):
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "mock")
    monkeypatch.setenv("GLTG_LLM_PROVIDER", "qwen")
    provider = get_provider(load_settings())
    assert provider.provider_name == "mock"


def test_unknown_provider_fails_with_clear_error(monkeypatch):
    monkeypatch.setenv("GLTG_LLM_PROVIDER", "totally_unknown")
    with pytest.raises(ProviderError) as exc:
        get_provider(load_settings())
    message = str(exc.value)
    assert "totally_unknown" in message
    for name in SUPPORTED_PROVIDERS:
        assert name in message
