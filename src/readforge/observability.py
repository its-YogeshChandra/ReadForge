"""OpenTelemetry setup shared by the API and background worker."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


@dataclass
class _Telemetry:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider
    log_handler: LoggingHandler


class _PersistedLogFilter(logging.Filter):
    """Persist only failures and explicit security/audit events."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("opentelemetry"):
            return False
        return record.levelno >= logging.ERROR or record.name.startswith(
            "readforge.audit"
        )


_telemetry: _Telemetry | None = None


def configure_observability(
    service_name: str,
    *,
    sqlalchemy_engine: Any | None = None,
) -> bool:
    """Configure OTLP exporters when an OTLP endpoint is supplied."""
    global _telemetry

    if _telemetry is not None:
        return True
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "0.1.0",
            "deployment.environment.name": os.getenv(
                "OTEL_ENVIRONMENT", "development"
            ),
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter())
    )
    set_logger_provider(logger_provider)
    log_handler = LoggingHandler(logger_provider=logger_provider)
    log_handler.addFilter(_PersistedLogFilter())
    logging.getLogger().addHandler(log_handler)

    RequestsInstrumentor().instrument()
    RedisInstrumentor().instrument()
    if sqlalchemy_engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=sqlalchemy_engine)

    _telemetry = _Telemetry(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        log_handler=log_handler,
    )
    return True


def shutdown_observability() -> None:
    """Flush telemetry before the process exits."""
    global _telemetry

    if _telemetry is None:
        return

    logging.getLogger().removeHandler(_telemetry.log_handler)
    _telemetry.logger_provider.shutdown()
    _telemetry.meter_provider.shutdown()
    _telemetry.tracer_provider.shutdown()
    _telemetry = None
