from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from .io import ClosureError, load_source
from .formatting import render_source
from .models import Datum
from .project import Project


@contextmanager
def project_lock(root: Path):
    directory = root / ".closure"
    directory.mkdir(exist_ok=True)
    lock = directory / "write.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ClosureError("Another writer holds .closure/write.lock; reconcile that operation before retrying", "WRITE_CONFLICT") from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def patch_parameters(path, expected_source_hash, changes):
    root = Project(path).root
    with project_lock(root):
        project = Project(path)
        if project.source_hash != expected_source_hash:
            raise ClosureError("Source changed since this patch was prepared", "SOURCE_CONFLICT")
        overrides = {identifier: Datum.model_validate(value) for identifier, value in changes.items()}
        project.resolve_parameters(overrides)
        updated = {}
        for identifier, replacement in overrides.items():
            module_name, local = identifier.split(".", 1)
            file_path = Path(project.locations[module_name])
            document = updated.setdefault(file_path, load_source(file_path))
            original = document["parameters"][local]
            for key, value in replacement.model_dump(exclude_unset=True).items():
                original[key] = value
        # Validate every replacement before any file is committed.
        rendered = {}
        for file_path, document in updated.items():
            rendered[file_path] = render_source(document, json_source=file_path.suffix.lower() == ".json")
        originals = {file_path: file_path.read_bytes() for file_path in rendered}
        try:
            for file_path, text in rendered.items():
                temporary = file_path.with_suffix(file_path.suffix + ".closure-tmp")
                temporary.write_bytes(text.encode("utf-8"))
                os.replace(temporary, file_path)
            revised = Project(path)
        except Exception:
            for file_path, data in originals.items():
                file_path.write_bytes(data)
            raise
        return {"source_hash": revised.source_hash, "changed": list(changes), "impact": [revised.impact(i) for i in changes]}
