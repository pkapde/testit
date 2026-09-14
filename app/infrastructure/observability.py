"""Opt-in, self-hosted Phoenix observability with safe operational metadata only."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import logging
from typing import Any, Iterator

from app.core.config import settings
from app.schemas.documents import ClaimTriageResult

logger = logging.getLogger(__name__)
_configured = False


def _claim_reference(claim_id: str) -> str:
    """Return a stable correlation value without exporting a customer claim ID."""
    return sha256(claim_id.encode("utf-8")).hexdigest()[:16]


def configure_phoenix(app: object | None = None) -> bool:
    """Configure an internal OTLP exporter; never stop the API if it is unavailable."""
    global _configured
    if _configured:
        return True
    if not settings.phoenix_enabled:
        logger.info("Phoenix observability is disabled")
        return False
    if settings.phoenix_capture_content:
        # This integration is intentionally metadata-only. Retain the setting so
        # a mistaken production value is visible in logs, but never honour it.
        logger.warning("PHOENIX_CAPTURE_CONTENT is ignored; ContractIQ exports metadata only")
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({
            "service.name": settings.phoenix_service_name,
            "openinference.project.name": settings.phoenix_project_name,
            "deployment.environment": settings.app_env,
        }))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.phoenix_endpoint)))
        trace.set_tracer_provider(provider)
        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app, excluded_urls="health,docs,openapi.json")
        _configured = True
        logger.info("Phoenix observability enabled for internal endpoint")
        return True
    except Exception as exc:  # Observability must never block claim handling.
        logger.warning("Phoenix observability could not be configured: %s", type(exc).__name__)
        return False


def shutdown_phoenix() -> None:
    if not _configured:
        return
    try:
        from opentelemetry import trace
        shutdown = getattr(trace.get_tracer_provider(), "shutdown", None)
        if shutdown:
            shutdown()
    except Exception as exc:
        logger.warning("Phoenix observability shutdown failed: %s", type(exc).__name__)


def trace_triage(result: ClaimTriageResult) -> str | None:
    """Trace a completed claim workflow without PII, documents, or model content."""
    if not _configured:
        return None
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("contractiq.workflow")
        with tracer.start_as_current_span("claim.triage.completed") as span:
            span.set_attribute("claim.reference", _claim_reference(result.validation.claim_id))
            span.set_attribute("claim.document_count", result.validation.documents_received)
            span.set_attribute("claim.overall_status", result.validation.overall_status)
            span.set_attribute("claim.routing_queue", result.routing_queue.value)
            span.set_attribute("claim.issue_count", len(result.cross_document_issues))
            return format(span.get_span_context().trace_id, "032x")
    except Exception as exc:
        logger.warning("Phoenix triage trace failed: %s", type(exc).__name__)
        return None


@contextmanager
def llm_operation(operation: str) -> Iterator[Any | None]:
    """Create an OpenInference LLM span without exporting claim content."""
    if not _configured:
        yield None
        return

    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("contractiq.llm")
        span_context = tracer.start_as_current_span("azure_openai.operation")
    except Exception as exc:
        # Observability is optional; a tracing setup error must not block a claim.
        logger.warning("Phoenix LLM span could not be started: %s", type(exc).__name__)
        yield None
        return

    # Do not catch exceptions raised by the model call inside this context. They
    # must retain their normal error behaviour instead of becoming tracing errors.
    with span_context as span:
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("llm.operation", operation)
        span.set_attribute("llm.system", "openai")
        span.set_attribute("llm.provider", "azure")
        span.set_attribute("llm.model_name", settings.azure_openai_deployment or "unconfigured")
        yield span


def record_llm_response(span: Any | None, response: Any) -> None:
    """Attach safe model and token metadata from a completed Azure response."""
    if span is None:
        return

    try:
        model_name = getattr(response, "model", None) or settings.azure_openai_deployment
        if model_name:
            span.set_attribute("llm.model_name", str(model_name))

        usage = getattr(response, "usage", None)
        if usage is None:
            return

        token_attributes = {
            "llm.token_count.prompt": getattr(usage, "prompt_tokens", None),
            "llm.token_count.completion": getattr(usage, "completion_tokens", None),
            "llm.token_count.total": getattr(usage, "total_tokens", None),
        }
        for name, value in token_attributes.items():
            if value is not None:
                span.set_attribute(name, int(value))
    except Exception as exc:
        # Never let incomplete SDK metadata prevent an otherwise successful call.
        logger.warning("Phoenix LLM response metadata could not be recorded: %s", type(exc).__name__)
