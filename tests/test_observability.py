"""Small guard for the persisted-log policy."""

import logging

from readforge.observability import _PersistedLogFilter


def test_only_errors_and_audit_logs_are_persisted() -> None:
    log_filter = _PersistedLogFilter()

    normal = logging.LogRecord("readforge.worker", logging.INFO, "", 0, "ok", (), None)
    error = logging.LogRecord("readforge.worker", logging.ERROR, "", 0, "bad", (), None)
    audit = logging.LogRecord("readforge.audit", logging.WARNING, "", 0, "audit", (), None)

    assert not log_filter.filter(normal)
    assert log_filter.filter(error)
    assert log_filter.filter(audit)
