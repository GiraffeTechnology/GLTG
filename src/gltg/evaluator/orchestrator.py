"""GLTG evaluator orchestrator.

Stage 3 contract: the deterministic rule engine is the **default** evaluation
path (``GLTG_EVALUATOR_MODE=deterministic``; ``fallback`` is a deprecated
alias). LLM-assisted evaluation runs only when explicitly selected with
``GLTG_EVALUATOR_MODE=llm``:

    request -> provider adapter -> assessment packet
            -> validator / guardrails -> quantile normalizer
            -> v2 response (+ optional fallback / manual review)

GLTG never calls an LLM for calculations unless the operator opted in.
"""

from __future__ import annotations

from ..behavioral.schemas import GLTGSimulationResponseV2, GLTGWarningV2
from .config import EvaluatorSettings, load_settings
from .fallback_rules import run_fallback
from .prompts import SYSTEM_PROMPT, assessment_schema_dict, build_user_payload
from .provider_registry import get_provider
from .providers.base import GLTGLLMProvider, ProviderError
from .schemas import GLTGAssessmentInput, GLTGAssessmentPacket
from .validator import PacketParseError, parse_packet, validate_and_repair

QUALITATIVE_PROVIDER_WARNING_CODES = frozenset(
    {
        "CONFIRMED_WITHOUT_EVIDENCE_DOWNGRADED",
        "HIGH_CONFIDENCE_WITHOUT_EVIDENCE_DOWNGRADED",
        "UNKNOWN_MATERIAL_CANNOT_BE_CONFIRMED",
        "UNKNOWN_EXECUTION_CANNOT_BE_CONFIRMED",
        "UNSUPPORTED_FAST_PRECISE_QUOTE",
        "SLOW_RESPONSE_NOT_LOW_ENGAGEMENT",
        "RESPONSE_DELAY_PROBABILITIES_RENORMALIZED",
    }
)


class GLTGEvaluatorOrchestrator:
    """Provider-agnostic entry point for GLTG v2 lead-time evaluation."""

    def evaluate(self, req: GLTGAssessmentInput) -> GLTGSimulationResponseV2:
        settings = load_settings()
        canonical = run_fallback(
            req,
            settings,
            provider_unavailable=False,
            deprecated_fallback_alias=settings.is_fallback_mode,
        )

        if settings.is_deterministic_mode:
            return canonical

        try:
            provider = get_provider(settings)
            packet = self._evaluate_with_provider(provider, req, settings)
        except (ProviderError, PacketParseError, ValueError):
            return self._handle_failure(canonical, settings)

        result = validate_and_repair(packet, req)
        return self._merge_auxiliary(canonical, result.packet, settings, result.warnings)

    def _evaluate_with_provider(
        self,
        provider: GLTGLLMProvider,
        req: GLTGAssessmentInput,
        settings: EvaluatorSettings,
    ) -> GLTGAssessmentPacket:
        system_prompt = SYSTEM_PROMPT
        user_payload = build_user_payload(req)
        schema = assessment_schema_dict()

        call_kwargs = {
            "system_prompt": system_prompt,
            "user_payload": user_payload,
            "schema": schema,
            "model": settings.model,
            "timeout_seconds": settings.timeout_seconds,
            "temperature": settings.temperature,
            "json_mode": settings.json_mode,
        }

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
        canonical: GLTGSimulationResponseV2,
        settings: EvaluatorSettings,
    ) -> GLTGSimulationResponseV2:
        canonical.evaluation_mode = "deterministic_with_llm_unavailable"
        self._set_manual_review(
            canonical,
            required=True,
            reasons=["optional LLM auxiliary evaluator is unavailable"],
        )
        canonical.explanation_json["llm_auxiliary"] = {
            "status": "unavailable",
            "provider": settings.provider,
            "model": settings.model,
        }
        canonical.warnings.append(
            GLTGWarningV2(
                code="EVALUATOR_UNAVAILABLE",
                severity="high",
                message=(
                    "Optional LLM auxiliary evaluator is unavailable; canonical "
                    "deterministic numbers are unchanged and manual review is required."
                ),
            )
        )
        return canonical

    @staticmethod
    def _merge_auxiliary(
        canonical: GLTGSimulationResponseV2,
        packet: GLTGAssessmentPacket,
        settings: EvaluatorSettings,
        warnings: list[GLTGWarningV2],
    ) -> GLTGSimulationResponseV2:
        auxiliary = {
            "status": "available",
            "provider": packet.model_provider,
            "model": packet.model_name,
            "supplier_execution_mode": packet.supplier_execution_assessment.execution_mode,
            "supplier_execution_status": packet.supplier_execution_assessment.status,
            "material_availability_status": (
                packet.material_availability_assessment.material_availability_status
            ),
            "response_delay_reason": packet.response_delay_reason_assessment.most_likely_reason,
            "quote_confidence_level": packet.quote_confidence_assessment.quote_confidence_level,
            "evidence_refs": list(packet.evidence_refs),
            "missing_information": list(packet.missing_information),
            "follow_up_questions": list(packet.follow_up_questions),
            "manual_review_reasons": list(packet.manual_review.reasons),
        }
        canonical.evaluation_mode = "deterministic_with_llm_auxiliary"
        canonical.explanation_json["llm_auxiliary"] = auxiliary
        canonical.assessment_packet["llm_auxiliary"] = auxiliary
        canonical.warnings.extend(
            warning
            for warning in warnings
            if warning.code in QUALITATIVE_PROVIDER_WARNING_CODES
        )
        GLTGEvaluatorOrchestrator._set_manual_review(
            canonical,
            required=packet.manual_review.required,
            reasons=packet.manual_review.reasons,
        )
        return canonical

    @staticmethod
    def _set_manual_review(
        canonical: GLTGSimulationResponseV2,
        *,
        required: bool,
        reasons: list[str],
    ) -> None:
        review = canonical.assessment_packet.setdefault(
            "manual_review", {"required": False, "reasons": []}
        )
        final_required = bool(
            required
            or canonical.manual_review_required
            or canonical.risk.manual_review_required
            or review.get("required", False)
        )
        review["required"] = final_required
        review_reasons = review.setdefault("reasons", [])
        for reason in reasons:
            if reason not in review_reasons:
                review_reasons.append(reason)
        canonical.manual_review_required = final_required
        canonical.risk.manual_review_required = final_required


# Module-level singleton used by the API routes.
orchestrator = GLTGEvaluatorOrchestrator()


def evaluate(req: GLTGAssessmentInput) -> GLTGSimulationResponseV2:
    return orchestrator.evaluate(req)


__all__ = ["GLTGEvaluatorOrchestrator", "orchestrator", "evaluate"]
