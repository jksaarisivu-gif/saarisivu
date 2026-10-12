"""Observability & Secrets: JSON Logs, Intent/Outcome Audit, OpenTelemetry Tracing, PII Scrubbing, & Secret Manager."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import json
import logging
import os
import re
from typing import Any, Callable, Dict, Iterator, List, Optional, TypeVar
import uuid

try:
    from opentelemetry import trace  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace.export import InMemorySpanExporter, SimpleSpanProcessor  # type: ignore[import-not-found]

    _PROVIDER = TracerProvider()
    _PROVIDER.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    trace.set_tracer_provider(_PROVIDER)
    _TRACER = trace.get_tracer("luxury_purse_agent")
except ImportError:
    _TRACER = None  # type: ignore[assignment]

F = TypeVar("F", bound=Callable[..., Any])

# Active PII redaction regexes protecting VIP client privacy (email, phone, credit cards, secrets)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
_SECRET_RE = re.compile(
    r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{8,})['\"]?"
)

AUDIT_EVENTS: List[Dict[str, Any]] = []


def get_secret_or_env(secret_id: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieves secrets from Google Cloud Secret Manager with safe env fallback (no hardcoded keys)."""
    env_val = os.environ.get(secret_id.upper().replace("-", "_"))
    if env_val:
        return env_val

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project_id and project_id != "your-gcp-project-id":
        try:
            from google.cloud import secretmanager  # type: ignore[import-untyped]

            client = secretmanager.SecretManagerServiceClient()
            path = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
            return client.access_secret_version(request={"name": path}).payload.data.decode("utf-8").strip()
        except Exception:
            pass
    return default


def redact_pii(text: str) -> str:
    """Scrubs client emails, phone numbers, credit card numbers, & API keys (plus optional Cloud DLP)."""
    if not text:
        return text
    cleaned = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    cleaned = _PHONE_RE.sub("[REDACTED_PHONE]", cleaned)
    cleaned = _CARD_RE.sub("[REDACTED_CARD]", cleaned)
    cleaned = _SECRET_RE.sub("secret=[REDACTED_SECRET]", cleaned)

    if os.environ.get("USE_CLOUD_DLP") == "TRUE" and os.environ.get("GOOGLE_CLOUD_PROJECT"):
        try:
            from google.cloud import dlp_v2  # type: ignore[import-untyped]

            dlp = dlp_v2.DlpServiceClient()
            res = dlp.deidentify_content(
                request={
                    "parent": f"projects/{os.environ['GOOGLE_CLOUD_PROJECT']}/locations/global",
                    "item": {"value": cleaned},
                }
            )
            cleaned = res.item.value
        except Exception:
            pass
    return cleaned


def scrub_data(obj: Any) -> Any:
    """Recursively scrubs PII from dictionaries, lists, and strings."""
    if isinstance(obj, str):
        return redact_pii(obj)
    if isinstance(obj, dict):
        return {k: scrub_data(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_data(v) for v in obj]
    return obj


class JsonLogFormatter(logging.Formatter):
    """Emits structured machine-parseable JSON log lines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": redact_pii(record.getMessage()),
        }
        extra = getattr(record, "structured_data", None)
        if isinstance(extra, dict):
            payload.update(scrub_data(extra))
        return json.dumps(payload, default=str)


LOGGER = logging.getLogger("luxury_purse_agent")
if not LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(JsonLogFormatter())
    LOGGER.addHandler(_handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


@contextmanager
def traced_span(name: str, attrs: Optional[Dict[str, Any]] = None) -> Iterator[str]:
    """Starts an OpenTelemetry trace span linking request steps end-to-end."""
    span_id = uuid.uuid4().hex[:16]
    if _TRACER is not None:
        with _TRACER.start_as_current_span(name) as span:
            for k, v in scrub_data(attrs or {}).items():
                span.set_attribute(k, str(v))
            yield span_id
    else:
        yield span_id


def trace_tool(span_name: str) -> Callable[[F], F]:
    """Decorator tracing tool executions via OpenTelemetry."""

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with traced_span(span_name, kwargs):
                return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def log_intent_and_outcome(
    phase: str,
    tool_name: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    """Records explicit pre-execution `agent_intent` and post-execution `agent_outcome` logs."""
    entry = {
        "event_type": f"agent_{phase}",
        "trace_id": uuid.uuid4().hex,
        "tool_name": tool_name,
        "details": scrub_data(details),
    }
    AUDIT_EVENTS.append(entry)
    LOGGER.info(f"{phase.upper()} [{tool_name}]", extra={"structured_data": entry})
    return entry
