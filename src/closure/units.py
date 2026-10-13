from __future__ import annotations

import math
import pint
from .io import ClosureError
from .models import Port
from .protocol import envelope_adapter

ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)


def convert(value, source, target):
    try:
        result = ureg.Quantity(value, source).to(target).magnitude
        if not math.isfinite(result):
            raise ValueError("nonfinite quantity")
        return float(result)
    except Exception as exc:
        raise ClosureError(f"Cannot convert {source} to {target}: {exc}", "UNIT_MISMATCH") from exc


def compatible(source: Port, unit=None, qualifiers=None):
    if unit:
        if source.type != "quantity":
            raise ClosureError("Units requested for a non-quantity", "TYPE_MISMATCH")
        convert(1, source.unit, unit)
    if qualifiers and any(source.qualifiers.get(k) != v for k, v in qualifiers.items()):
        raise ClosureError(f"Semantic qualifiers do not match: {source.qualifiers} vs {qualifiers}", "QUALIFIER_MISMATCH")


def validate_value(envelope: dict, port: Port):
    try:
        envelope_adapter.validate_python(envelope)
    except ValueError as exc:
        raise ClosureError(f"Invalid output envelope: {exc}", "OUTPUT_INVALID") from exc
    if envelope.get("type", port.type) != port.type:
        raise ClosureError("Output type does not match its port", "OUTPUT_INVALID")
    if envelope.get("qualifiers", {}) != port.qualifiers:
        raise ClosureError("Output semantic qualifiers differ from declared port", "QUALIFIER_MISMATCH")
    if port.type == "artifact":
        if not isinstance(envelope.get("path"), str):
            raise ClosureError("Artifact output requires a path", "OUTPUT_INVALID")
        return {**envelope, "type": "artifact"}
    value = envelope.get("value")
    if port.type in ("scalar", "quantity"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ClosureError("Expected a finite scalar number", "OUTPUT_INVALID")
    elif port.type == "boolean" and not isinstance(value, bool):
        raise ClosureError("Expected a boolean", "OUTPUT_INVALID")
    elif port.type in ("string", "enum") and not isinstance(value, str):
        raise ClosureError("Expected a string", "OUTPUT_INVALID")
    if port.type == "enum" and value not in port.choices:
        raise ClosureError("Invalid enum value", "OUTPUT_INVALID")
    if port.type == "quantity":
        if not envelope.get("unit"):
            raise ClosureError("Quantity output requires a unit", "OUTPUT_INVALID")
        value = convert(value, envelope["unit"], port.unit)
    elif envelope.get("unit"):
        raise ClosureError("Unexpected output unit", "OUTPUT_INVALID")
    return {"type": port.type, "value": value, "unit": port.unit, "qualifiers": port.qualifiers}
