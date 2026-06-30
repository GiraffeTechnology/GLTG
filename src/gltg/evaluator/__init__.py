"""Provider-agnostic LLM-assisted GLTG trade lead-time risk evaluator.

GLTG uses an LLM-assisted evaluator architecture. Qwen3.5 is the default
bundled/reference evaluator backend, but the evaluator is accessed through a
provider adapter interface so that OpenAI-compatible, Claude-compatible,
Gemini-compatible, DeepSeek-compatible, local, and private enterprise models can
be used without changing GLTG business logic. Deterministic rules are retained
only as validator, guardrail, and optional fallback logic.
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
