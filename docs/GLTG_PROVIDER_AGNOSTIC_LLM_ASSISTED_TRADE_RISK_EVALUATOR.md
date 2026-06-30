# GLTG Provider-Agnostic LLM-Assisted Trade Risk Evaluator

GLTG uses an LLM-assisted evaluator architecture.

Qwen3.5 is the default bundled/reference evaluator model for the first
implementation, but GLTG remains model-provider agnostic. The evaluator is
accessed through a provider adapter interface so that OpenAI-compatible models,
Claude-compatible providers, Gemini-compatible providers, DeepSeek-compatible
providers, local models, and private enterprise models can be used without
changing GLTG business logic.

## Why LLM-assisted, not hard-coded formulas

Trade and processing lead-time risk is too context-dependent for immature fixed
weights. Instead of asking *"what does the fixed formula say?"*, GLTG asks
*"what does the trade evidence say, as evaluated by a provider-agnostic LLM
evaluator, constrained by GLTG schema, evidence rules, quantile validation, and
audit requirements?"*

The LLM evaluates trade context. GLTG validates, normalizes, constrains,
audits, and packages. giraffe-db stores facts, evidence, observations,
features, outcomes, and lineage. AIVAN / abcdYi / giraffe-agent call GLTG
through HTTP and must not copy GLTG model logic.

## Pipeline

```
AIVAN / abcdYi / giraffe-agent
        ↓
GLTG HTTP API  (POST /v2/lead-time/simulate)
        ↓
GLTG Evaluator Orchestrator        src/gltg/evaluator/orchestrator.py
        ↓
LLM Provider Adapter Interface     src/gltg/evaluator/providers/base.py
        ├── qwen (default: qwen3.5)
        ├── openai_compatible
        ├── anthropic / claude-compatible
        ├── gemini-compatible
        ├── deepseek-compatible
        ├── local / private enterprise
        └── mock (CI / deterministic tests)
        ↓
Structured GLTG Assessment Packet  src/gltg/evaluator/schemas.py
        ↓
Validator / Guardrail / Evidence   src/gltg/evaluator/validator.py
                                    src/gltg/evaluator/guardrails.py
        ↓
Quantile Normalizer + Risk Action Builder
        ↓
GLTG v2 response (+ optional giraffe-db persistence)
```

## Modules

| Module | Responsibility |
| --- | --- |
| `evaluator/orchestrator.py` | Selects provider, builds prompt + payload, validates, normalizes, packages. |
| `evaluator/provider_registry.py` | Resolves a provider name to a configured adapter; clear error on unknown. |
| `evaluator/providers/` | Provider-neutral interface + adapters (qwen, openai_compatible, anthropic, gemini, deepseek, local, mock). |
| `evaluator/schemas.py` | `gltg-assessment-v1` packet schema and status enums. |
| `evaluator/prompts.py` | System prompt protocol + structured user payload. |
| `evaluator/validator.py` | Schema/evidence/numeric validation and repair. |
| `evaluator/guardrails.py` | Business invariants + quantile normalizer. |
| `evaluator/assessment_packet.py` | Packet → v2 response projection; manual-review packet. |
| `evaluator/fallback_rules.py` | Demoted deterministic rules (guardrail/fallback only). |
| `evaluator/config.py` | Environment-driven `EvaluatorSettings`. |

## Configuration

See [`.env.example`](../.env.example). Defaults:

```text
GLTG_EVALUATOR_MODE=llm
GLTG_LLM_PROVIDER=qwen
GLTG_LLM_MODEL=qwen3.5
GLTG_LLM_TEMPERATURE=0
GLTG_ALLOW_RULE_FALLBACK=false
```

If LLM evaluation fails and `GLTG_ALLOW_RULE_FALLBACK=false`, GLTG returns a
controlled manual-review assessment. It does not silently fall back to
hard-coded formulas.

## Related docs

- [Provider interface](GLTG_EVALUATOR_PROVIDER_INTERFACE.md)
- [Assessment packet schema](GLTG_ASSESSMENT_PACKET_SCHEMA.md)
- [Prompt protocol](GLTG_PROMPT_PROTOCOL.md)
- [Fallback and guardrails](GLTG_FALLBACK_AND_GUARDRAILS.md)
