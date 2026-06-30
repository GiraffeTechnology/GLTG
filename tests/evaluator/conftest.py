"""Shared helpers for evaluator tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gltg.evaluator.schemas import GLTGAssessmentInput

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_request(**overrides) -> GLTGAssessmentInput:
    data = json.loads((FIXTURES / "gltg_v2_simulation_request.json").read_text())
    for key, value in overrides.items():
        data[key] = value
    return GLTGAssessmentInput(**data)


@pytest.fixture
def make_request():
    return load_request


@pytest.fixture(autouse=True)
def _mock_llm_env(monkeypatch):
    """Default every evaluator test to the deterministic mock provider."""
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "llm")
    monkeypatch.setenv("GLTG_LLM_PROVIDER", "mock")
    monkeypatch.setenv("GLTG_LLM_MODEL", "qwen3.5")
    monkeypatch.delenv("GLTG_ALLOW_RULE_FALLBACK", raising=False)
    monkeypatch.delenv("GLTG_MOCK_SCENARIO", raising=False)
