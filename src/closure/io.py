"""Bounded, non-executable source loading and canonical content identities."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any
from ruamel.yaml import YAML
from ruamel.yaml.tokens import AnchorToken, AliasToken, TagToken
from ruamel.yaml.events import MappingStartEvent, SequenceStartEvent, MappingEndEvent, SequenceEndEvent


class ClosureError(Exception):
    def __init__(self, message: str, code: str = "INVALID", location: str = ""):
        super().__init__(message)
        self.code, self.location = code, location

    def as_dict(self):
        return {"code": self.code, "message": str(self), "location": self.location}


def primitive(value: Any, depth=0):
    if depth > 48:
        raise ClosureError("Source nesting exceeds 48 levels", "SOURCE_LIMIT")
    if isinstance(value, dict):
        if any(not isinstance(k, str) or k == "<<" for k in value):
            raise ClosureError("Mapping keys must be strings; merge keys are forbidden", "SOURCE_KEY")
        return {str(k): primitive(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [primitive(v, depth + 1) for v in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ClosureError(f"Unsupported or non-finite value: {type(value).__name__}", "SOURCE_TYPE")


def load_source(path: Path):
    try:
        if path.stat().st_size > 2_000_000:
            raise ClosureError("Source exceeds 2 MB", "SOURCE_LIMIT", str(path))
        text = path.read_text(encoding="utf-8-sig")
        parser = YAML(typ="rt")
        parser.version = (1, 2)
        parser.allow_duplicate_keys = False
        for token in parser.scan(text):
            if isinstance(token, (AnchorToken, AliasToken, TagToken)):
                raise ClosureError("YAML tags, anchors, and aliases are forbidden", "UNSAFE_YAML", f"{path}:{token.start_mark.line + 1}")
        depth = 0
        for event in parser.parse(text):
            if isinstance(event, (MappingStartEvent, SequenceStartEvent)):
                depth += 1
                if depth > 48:
                    raise ClosureError("Source nesting exceeds 48 levels", "SOURCE_LIMIT", str(path))
            elif isinstance(event, (MappingEndEvent, SequenceEndEvent)):
                depth -= 1
        document = parser.load(text)
        primitive(document)
        if not isinstance(document, dict):
            raise ClosureError("Source document must be a mapping", "SOURCE_TYPE", str(path))
        return document
    except ClosureError:
        raise
    except Exception as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f"{path}:{mark.line + 1}" if mark else str(path)
        raise ClosureError(str(exc), "SOURCE_PARSE", location) from exc


def canonical(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def within(root: Path, relative: str):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ClosureError(f"Path escapes project: {relative}", "PATH_ESCAPE")
    return path


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value) + b"\n")
    os.replace(temporary, path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
