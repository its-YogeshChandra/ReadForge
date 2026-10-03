"""Small JSON-line lifecycle traces for local terminals."""

import json
from datetime import UTC, datetime
from typing import Any


def trace(correlation_id: object, stage: str, **fields: Any) -> None:
    """Print one machine-readable lifecycle event without request content."""
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "correlation_id": str(correlation_id),
                "stage": stage,
                **fields,
            },
            default=str,
            separators=(",", ":"),
        ),
        flush=True,
    )
