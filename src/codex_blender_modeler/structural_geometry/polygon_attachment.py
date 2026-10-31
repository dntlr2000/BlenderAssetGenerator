"""Explicit polygon-source attachment versions; legacy 0.1 admission remains unchanged."""

import json
from typing import Literal, Self

from pydantic import Field, model_validator

from .attachment_companion import Artifact, AttachmentIntentV01
from .solid_attachment_companion import SolidRootAttachmentIntentV01


def _validate_view_paths(intent):
    """Require one distinct inspection artifact per authored source without path aliases."""
    paths = [a.path for a in intent.source_triangle_views]
    existing = {a.path for a in intent.source_geometry}
    existing.update(a.path for a in (intent.source_scene, intent.source_reference,
                                    intent.source_modeling_plan))
    if (len(paths) != len(intent.source_geometry) or len(set(paths)) != len(paths)
            or existing.intersection(paths)):
        raise ValueError("polygon attachment views must be distinct and cover every source")


class AttachmentIntentV02(AttachmentIntentV01):
    """Select polygon source correspondence explicitly for the existing surface proof."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    source_triangle_views: list[Artifact] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_view_paths(self) -> Self:
        """Reject duplicate, omitted and aliased triangle-view selections."""
        _validate_view_paths(self)
        return self


class SolidRootAttachmentIntentV02(SolidRootAttachmentIntentV01):
    """Select polygon sources for the unchanged complete-solid/local-ball mathematics."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    source_triangle_views: list[Artifact] = Field(min_length=2, max_length=128)

    @model_validator(mode="after")
    def validate_view_paths(self) -> Self:
        """Keep views separate from canonical payload and camera artifacts."""
        _validate_view_paths(self)
        if self.source_camera_hypothesis.path in {a.path for a in self.source_triangle_views}:
            raise ValueError("triangle view aliases camera hypothesis")
        return self


def parse_solid_root_intent(data: bytes):
    """Dispatch only explicit solid-root versions; never admit another proof domain."""
    value = json.loads(data)
    version = value.get("schema_version") if isinstance(value, dict) else None
    model = SolidRootAttachmentIntentV02 if version == "0.2.0" else SolidRootAttachmentIntentV01
    return model.model_validate_json(data)
