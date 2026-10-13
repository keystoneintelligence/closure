"""Published schema identities, independent of a hosting domain."""
from .models import Manifest, Module, Study
from .protocol import RUNTIME_SCHEMAS


def schemas():
    models = {"project": Manifest, "module": Module, "study": Study, **RUNTIME_SCHEMAS}
    return {
        name: {"$schema": "https://json-schema.org/draft/2020-12/schema",
               "$id": f"urn:closure:schema:0.1:{name}",
               **model.model_json_schema(by_alias=True)}
        for name, model in models.items()
    }
