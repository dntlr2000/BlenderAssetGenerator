"""Host preparation of exact authored recipe/texture metadata clone derivatives."""

from __future__ import annotations

import json

from .. import authored_material_runtime as graph
from .. import authored_split_runtime as split
from ..materials.models import ShaderRecipe
from ..texturing.models import TextureManifest


def prepare_material_derivatives(root, run_id, scene, material_plan, rules, *, publisher=None):
    """Preserve every authored value/media byte while cloning exact host-scoped identities."""
    from .authored_service import publish

    publish_candidate = publisher or (lambda path, content: publish(root, path, content))
    derivatives = []
    for ordinal, rule in enumerate(rules):
        manifest, recipe = graph.material_sources(root, scene, material_plan, rule)
        target_dir = graph.material_directory(run_id, rule["source_material_id"])
        item = {
            "object_id": rule["target_object_id"],
            "source_manifest": manifest,
            "source_recipe": recipe,
            "media_copies": {},
            "candidate_manifest": {
                "path": f"{target_dir}/manifest_{ordinal:03d}.json",
                "sha256": "0" * 64,
            }
            if manifest
            else None,
            "candidate_recipe": {
                "path": f"{target_dir}/recipe_{ordinal:03d}.json",
                "sha256": "0" * 64,
            }
            if recipe
            else None,
        }
        if manifest:
            raw = json.loads(split.read(root, manifest))
            TextureManifest.model_validate_json(split.read(root, manifest))
            for relative, path in graph.media_sources(root, manifest, raw).items():
                item["media_copies"][path] = publish_candidate(
                    f"{target_dir}/{relative}", split.read(root, split.reference(root, path))
                )
        if recipe:
            ShaderRecipe.model_validate_json(split.read(root, recipe))
        new_manifest, new_recipe = graph.material_projection(root, rule, item)
        if new_recipe is not None:
            ShaderRecipe.model_validate_json(split.encode(new_recipe))
            item["candidate_recipe"] = publish_candidate(
                item["candidate_recipe"]["path"], new_recipe
            )
        if new_manifest is not None:
            TextureManifest.model_validate_json(split.encode(new_manifest))
            item["candidate_manifest"] = publish_candidate(
                item["candidate_manifest"]["path"], new_manifest
            )
        derivatives.append(item)
    return derivatives


def validate_material_contracts(root, plan):
    """Strict-load every retained and cloned manifest/recipe without changing its bytes."""
    for item in plan["material_derivatives"]:
        for key, model in (
            ("source_manifest", TextureManifest),
            ("candidate_manifest", TextureManifest),
            ("source_recipe", ShaderRecipe),
            ("candidate_recipe", ShaderRecipe),
        ):
            if item[key]:
                model.model_validate_json(split.read(root, item[key]))
