"""Small lifecycle-event helper backed by the active OpenTelemetry span."""

from typing import Any

from opentelemetry import trace as otel_trace


def trace(correlation_id: object, stage: str, **fields: Any) -> None:
    """Attach one low-cardinality lifecycle event to the current span."""
    attributes: dict[str, str | bool | int | float] = {
        "readforge.correlation_id": str(correlation_id)
    }
    for key, value in fields.items():
        if value is None:
            continue
        attributes[f"readforge.{key}"] = (
            value if isinstance(value, (str, bool, int, float)) else str(value)
        )
    otel_trace.get_current_span().add_event(stage, attributes=attributes)
