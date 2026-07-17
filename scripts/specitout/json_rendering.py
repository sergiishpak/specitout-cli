from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from specitout.contracts import CommandEnvelope


def render_json_envelope(envelope: CommandEnvelope) -> str:
    return json.dumps(envelope, default=_json_default, indent=2, sort_keys=True) + "\n"


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime, Decimal, UUID)):
        return str(value)
    return str(value)
