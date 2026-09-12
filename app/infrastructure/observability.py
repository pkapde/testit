"""Opt-in, self-hosted Phoenix observability with safe operational metadata only."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import logging
from typing import Iterator

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
def llm_operation(operation: str) -> Iterator[None]:
    """Record timing/outcome for an LLM call, never its prompts, responses, or files."""
    if not _configured:
        yield
        return
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("contractiq.llm")
        with tracer.start_as_current_span("azure_openai.operation") as span:
            span.set_attribute("llm.operation", operation)
            span.set_attribute("llm.system", "azure_openai")
            span.set_attribute("llm.model_deployment", settings.azure_openai_deployment or "unconfigured")
            yield
    except Exception:
        # Do not change the provider behaviour if tracing itself has an issue.
        yield
