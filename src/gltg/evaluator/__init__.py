"""Provider-agnostic LLM-assisted GLTG trade lead-time risk evaluator.

The deterministic rule engine is GLTG's default evaluation path; this
LLM-assisted evaluator is explicit opt-in (``GLTG_EVALUATOR_MODE=llm``).
When enabled, a locally served ``qwen3.5-9b-int4`` is the default reference
model — a default, not a designated model, with no Qwen-ecosystem
dependency. The evaluator is accessed through a provider adapter interface
so OpenAI-compatible, Claude-compatible, Gemini-compatible,
DeepSeek-compatible, local, and private enterprise models can be used
without changing GLTG business logic.
"""

from .config import EvaluatorSettings, load_settings
from .orchestrator import GLTGEvaluatorOrchestrator, evaluate, orchestrator
from .schemas import ASSESSMENT_SCHEMA_VERSION, GLTGAssessmentPacket

__all__ = [
    "ASSESSMENT_SCHEMA_VERSION",
    "EvaluatorSettings",
    "GLTGAssessmentPacket",
    "GLTGEvaluatorOrchestrator",
    "evaluate",
    "load_settings",
    "orchestrator",
]
