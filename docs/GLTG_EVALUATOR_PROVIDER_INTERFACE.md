# GLTG Evaluator Provider Interface

GLTG is LLM-provider agnostic. The core model boundary is **not**
`qwen_client.evaluate(...)`. It is a provider-neutral interface that every
adapter implements:

```python
class GLTGLLMProvider(Protocol):
    provider_name: str

    def evaluate_gltg_assessment(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        schema: dict,
        model: str,
        timeout_seconds: int,
        temperature: float = 0.0,
        json_mode: bool = True,
        repair: bool = False,
        previous_error: str | None = None,
    ) -> dict:  # normalized assessment-packet dict
        ...
```

Defined in `src/gltg/evaluator/providers/base.py`.

## Contract

- Adapters return **normalized content** — a parsed `dict` representing the GLTG
  assessment packet JSON — never a provider-native response envelope.
- Adapters hide differences in: message format, JSON mode, tool/function
  calling, response parsing, authentication, timeout/retry, and error classes.
- Adapters raise the shared error taxonomy:
  - `ProviderUnavailable` — not configured / unreachable (e.g. missing key).
  - `ProviderTimeout` — exceeded `timeout_seconds`.
  - `ProviderInvalidOutput` — non-JSON / unparseable content.
  - `ProviderError` — any other provider-side failure.

## Supported providers

| `GLTG_LLM_PROVIDER` | Adapter | Transport |
| --- | --- | --- |
| `qwen` *(default)* | `QwenProvider` | OpenAI-compatible (DashScope compatible mode) |
| `openai_compatible` | `OpenAICompatibleProvider` | OpenAI `/chat/completions` |
| `anthropic` | `AnthropicProvider` | Anthropic Messages API |
| `gemini` | `GeminiProvider` | Google `generateContent` |
| `deepseek` | `DeepSeekProvider` | OpenAI-compatible |
| `local` | `LocalProvider` | OpenAI-compatible (vLLM/Ollama/TGI/private gateway) |
| `mock` | `MockGLTGProvider` | none — deterministic, for CI |

`qwen`, `deepseek`, and `local` reuse the OpenAI-compatible transport with
different default base URLs. Pointing `GLTG_LLM_BASE_URL` at a private
OpenAI-compatible endpoint is the recommended path for enterprise models.

## Registry

`src/gltg/evaluator/provider_registry.py` maps the provider name to a builder.
Unknown names fail with a clear error listing supported providers. In
`GLTG_EVALUATOR_MODE=mock` the mock provider is always used regardless of the
configured provider, so CI never reaches a network backend.

## Adding a provider

1. Implement a class with `provider_name` and `evaluate_gltg_assessment(...)`
   returning a normalized dict, raising the shared error taxonomy.
2. Register a builder in `_REGISTRY` in `provider_registry.py`.
3. No GLTG business logic changes — validation, guardrails, normalization, and
   the assessment packet schema are provider-independent.
