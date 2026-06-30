"""GLTG evaluator orchestrator.

Drives the provider-agnostic LLM-assisted evaluation:

    request -> provider adapter -> assessment packet
            -> validator / guardrails -> quantile normalizer
            -> v2 response (+ optional fallback / manual review)

Deterministic rules are never the primary path here -- they are only reached via
explicit fallback mode or an allowed provider-failure fallback.
"""

from __future__ import annotations

from ..behavioral.schemas import GLTGSimulationResponseV2, GLTGWarningV2
from .assessment_packet import manual_review_packet, project_to_response
from .config import EvaluatorSettings, load_settings
from .fallback_rules import run_fallback
from .prompts import SYSTEM_PROMPT, assessment_schema_dict, build_user_payload
from .provider_registry import get_provider
from .providers.base import GLTGLLMProvider, ProviderError
from .schemas import GLTGAssessmentInput, GLTGAssessmentPacket
from .validator import PacketParseError, parse_packet, validate_and_repair


class GLTGEvaluatorOrchestrator:
    """Provider-agnostic entry point for GLTG v2 lead-time evaluation."""

    def evaluate(self, req: GLTGAssessmentInput) -> GLTGSimulationResponseV2:
        settings = load_settings()

        if settings.is_fallback_mode:
            return run_fallback(req, settings, provider_unavailable=False)

        # `get_provider` raises on an unknown provider name (clear config error).
        provider = get_provider(settings)

        try:
            packet = self._evaluate_with_provider(provider, req, settings)
        except (ProviderError, PacketParseError) as exc:
            return self._handle_failure(req, settings, exc)

        result = validate_and_repair(packet, req)
        return project_to_response(req, result.packet, settings, result.warnings)

    def _evaluate_with_provider(
        self,
        provider: GLTGLLMProvider,
        req: GLTGAssessmentInput,
        settings: EvaluatorSettings,
    ) -> GLTGAssessmentPacket:
        system_prompt = SYSTEM_PROMPT
        user_payload = build_user_payload(req)
        schema = assessment_schema_dict()

        call_kwargs = dict(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=schema,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            temperature=settings.temperature,
            json_mode=settings.json_mode,
        )

        try:
            raw = provider.evaluate_gltg_assessment(**call_kwargs)
            packet = parse_packet(raw)
        except (PacketParseError, ProviderError) as exc:
            # One repair pass for invalid/unparseable output (not for timeouts
            # or unavailability, which cannot be repaired by re-prompting).
            from .providers.base import ProviderInvalidOutput

            if not isinstance(exc, (PacketParseError, ProviderInvalidOutput)):
                raise
            raw = provider.evaluate_gltg_assessment(
                repair=True, previous_error=str(exc)[:500], **call_kwargs
            )
            packet = parse_packet(raw)

        # Stamp provider metadata onto the packet / audit trail.
        packet.model_provider = provider.provider_name
        packet.model_name = settings.model
        packet.evaluation_mode = "llm"
        packet.audit.model_provider = provider.provider_name
        packet.audit.model_name = settings.model
        packet.audit.evaluation_mode = "llm"
        return packet

    def _handle_failure(
        self,
        req: GLTGAssessmentInput,
        settings: EvaluatorSettings,
        exc: Exception,
    ) -> GLTGSimulationResponseV2:
        # If rule fallback is explicitly allowed, use the deterministic engine
        # (clearly marked). Otherwise return a manual-review assessment -- never
        # silently invent a model result.
        if settings.allow_rule_fallback:
            return run_fallback(req, settings, provider_unavailable=True)

        packet = manual_review_packet(
            req, settings, reason=f"evaluator unavailable: {type(exc).__name__}"
        )
        result = validate_and_repair(packet, req)
        warnings = [
            GLTGWarningV2(
                code="EVALUATOR_UNAVAILABLE",
                severity="high",
                message=(
                    "LLM evaluator unavailable and rule fallback is disabled; "
                    "returning manual-review assessment."
                ),
            ),
            *result.warnings,
        ]
        return project_to_response(req, result.packet, settings, warnings)


# Module-level singleton used by the API routes.
orchestrator = GLTGEvaluatorOrchestrator()


def evaluate(req: GLTGAssessmentInput) -> GLTGSimulationResponseV2:
    return orchestrator.evaluate(req)


__all__ = ["GLTGEvaluatorOrchestrator", "orchestrator", "evaluate"]
