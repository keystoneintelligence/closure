"""Concise source formatting with equality checked against the compiled model."""
from __future__ import annotations

from copy import deepcopy
import io
import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .io import ClosureError, load_source, primitive
from .models import Manifest, Module, Study


def source_model(document):
    for key, model in (("module", Module), ("project", Manifest), ("study", Study)):
        if key in document:
            return model
    raise ClosureError("Expected a Closure project, module or study", "FORMAT_SOURCE")


def _has_comment(value):
    if isinstance(value, dict):
        return any(_has_comment(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_comment(v) for v in value)
    return "#" in getattr(value, "value", "")


def _comments(node):
    comment = getattr(node, "ca", None)
    return bool(comment and _has_comment([comment.comment, comment.items, comment.end]))


def _simplify(node, model):
    if isinstance(node, dict):
        for key in list(node):
            if isinstance(model, BaseModel):
                fields = type(model).model_fields
                field_name = next((name for name, field in fields.items() if (field.alias or name) == key), key)
                value = getattr(model, field_name, None)
            else:
                value = model.get(key) if isinstance(model, dict) else None
            _simplify(node[key], value)
            # Only known model fields may disappear. Empty settings, qualifiers,
            # strings and scopes can carry meaning and must survive unchanged.
            removable = node[key] is None or node[key] == "" or node[key] == {} or node[key] == [] or key == "type"
            attached = getattr(getattr(node, "ca", None), "items", {}).get(key)
            if isinstance(model, BaseModel) and removable and not _has_comment(attached) and not _comments(node[key]):
                candidate = {k: v for k, v in node.items() if k != key}
                try:
                    equivalent = type(model).model_validate(candidate).model_dump() == model.model_dump()
                except (ValidationError, ValueError):
                    equivalent = False
                if equivalent:
                    del node[key]
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _simplify(value, model[index] if isinstance(model, list) else None)


def _style(node):
    if isinstance(node, dict):
        if not isinstance(node, CommentedMap):
            node = CommentedMap(node)
        for key, child in list(node.items()):
            node[key] = _style(child)
        if isinstance(node, CommentedMap):
            compact = (set(node) <= {"value", "unit", "type", "ref", "path", "qualifiers", "choices", "origin", "description", "rationale"}
                       and not _comments(node) and len(json.dumps(primitive(node), ensure_ascii=False)) <= 86)
            (node.fa.set_flow_style if compact else node.fa.set_block_style)()
    elif isinstance(node, list):
        if not isinstance(node, CommentedSeq):
            node = CommentedSeq(node)
        for index, child in enumerate(node):
            node[index] = _style(child)
        if isinstance(node, CommentedSeq):
            compact = (all(not isinstance(x, (dict, list)) for x in node) and not _comments(node)
                       and len(json.dumps(primitive(node), ensure_ascii=False)) <= 86)
            (node.fa.set_flow_style if compact else node.fa.set_block_style)()
    return node


def render_source(document, *, json_source=False):
    model_type = source_model(document)
    before = model_type.model_validate(document)
    compact = deepcopy(document)
    _simplify(compact, before)
    if json_source:
        text = json.dumps(primitive(compact), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        after = json.loads(text)
    else:
        compact = _style(compact)
        writer = YAML(typ="rt")
        writer.width = 100
        writer.indent(mapping=2, sequence=4, offset=2)
        stream = io.StringIO()
        writer.dump(compact, stream)
        text = stream.getvalue()
        text = re.sub(r"(?m)([^\n])\n(?=(?:parameters|analyses|requirements|exports|policy|scenarios|configurations|grid|points):)", r"\1\n\n", text)
        after = YAML(typ="safe").load(text)
    if model_type.model_validate(after).model_dump() != before.model_dump():
        raise ClosureError("Formatting would change the compiled contract", "FORMAT_CHANGED_MODEL")
    return text


def format_project(path, check=False):
    from .editing import project_lock
    from .project import Project

    project = Project(path)
    # Conventional study directory only; never traverse evidence, reports or
    # arbitrary simulator YAML. Each selected study must validate as Closure.
    sources = list(project.source_files)
    studies = project.root / "studies"
    if studies.is_dir():
        sources += sorted(p for p in studies.rglob("*") if p.suffix.lower() in (".yaml", ".yml", ".json"))

    def prepare():
        originals, rendered = {}, {}
        for source in sources:
            if source.is_symlink() or not source.resolve().is_relative_to(project.root):
                raise ClosureError("Cannot format a source outside the project", "PATH_ESCAPE", str(source))
            document = load_source(source)
            text = render_source(document, json_source=source.suffix.lower() == ".json")
            original = source.read_bytes()
            if original != text.encode("utf-8"):
                originals[source], rendered[source] = original, text
        return originals, rendered

    if check:
        _, rendered = prepare()
    else:
        with project_lock(project.root):
            if Project(path).source_hash != project.source_hash:
                raise ClosureError("Source changed before formatting", "SOURCE_CONFLICT")
            originals, rendered = prepare()
            try:
                for source, text in rendered.items():
                    temporary = source.with_suffix(source.suffix + ".closure-tmp")
                    temporary.write_bytes(text.encode("utf-8"))
                    os.replace(temporary, source)
                revised = Project(path)
                if (revised.manifest != project.manifest or revised.modules != project.modules):
                    raise ClosureError("Formatting changed the linked model", "FORMAT_CHANGED_MODEL")
            except Exception:
                for source, original in originals.items():
                    source.write_bytes(original)
                raise
    return {"formatted": not check, "clean": not rendered, "files": [str(p.relative_to(project.root)) for p in rendered],
            "model_unchanged": True}
