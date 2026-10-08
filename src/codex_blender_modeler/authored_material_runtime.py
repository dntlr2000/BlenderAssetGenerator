"""Finite metadata-only texture/recipe clone projections for authored identity splits."""

from __future__ import annotations

import copy
import json
from pathlib import Path, PurePosixPath

from . import authored_split_runtime as split


def material_directory(run_id: str, source_material_id: str) -> str:
    """Share immutable media once for every clone of the same exact source identity."""
    return (
        f"{split.prefix(run_id)}/candidate/materials/{split.sha(source_material_id.encode())[:16]}"
    )


def manifest_member(root: Path, manifest_path: str, relative: str) -> str:
    """Resolve only a normalized manifest-local media/recipe locator without path ambiguity."""
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or ":" in relative
        or relative.startswith("/")
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise ValueError("authored split manifest member must be normalized and manifest-local")
    path = (PurePosixPath(manifest_path).parent / relative).as_posix()
    split.contained_file(root, path)
    return path


def material_sources(
    root: Path, scene: dict, material_plan: dict, rule: dict
) -> tuple[dict | None, dict | None]:
    """Resolve one source graph with explicit agreement between SceneSpec/plan/manifest/recipe."""
    material = next(item for item in scene["materials"] if item["id"] == rule["source_material_id"])
    matches = [
        item
        for item in material_plan["materials"]
        if item["material_id"] == rule["source_material_id"]
    ]
    if len(matches) != 1:
        raise ValueError("authored split source material requires one authored plan item")
    item = matches[0]
    manifest_path = material.get("texture_manifest")
    recipe_path = item.get("shader_recipe")
    manifest_ref = split.reference(root, manifest_path) if manifest_path else None
    recipe_ref = split.reference(root, recipe_path) if recipe_path else None
    manifest = json.loads(split.read(root, manifest_ref)) if manifest_ref else None
    recipe_bytes = split.read(root, recipe_ref) if recipe_ref else None
    linked_ref = None
    if manifest is not None and manifest.get("shader_recipe"):
        linked = manifest_member(root, manifest_path, manifest["shader_recipe"])
        if recipe_ref is None:
            raise ValueError(
                "authored split cannot substitute a latent manifest recipe "
                "for the effective MaterialPlan recipe"
            )
        if recipe_path != linked:
            linked_ref = split.reference(root, linked)
            if split.read(root, linked_ref) != recipe_bytes:
                raise ValueError("authored split source manifest/plan recipe bytes disagree")
        # Ordinary promotion can copy an identical recipe into a new workflow path.
        # Preserve the effective MaterialPlan locator; the closure binds both paths.
    recipe = json.loads(recipe_bytes) if recipe_bytes is not None else None
    selected_manifest = item.get("texture_manifest") or (
        recipe.get("texture_manifest") if recipe else None
    )
    if selected_manifest != manifest_path:
        raise ValueError("authored split source SceneSpec and authored graph manifest differ")
    if (
        item.get("texture_manifest")
        and recipe
        and recipe.get("texture_manifest")
        and item["texture_manifest"] != recipe["texture_manifest"]
    ):
        raise ValueError("authored split source authored manifest locators disagree")
    for value in (manifest, recipe):
        if value is not None and value.get("material_id") != rule["source_material_id"]:
            raise ValueError("authored split source graph has a foreign material identity")
    # Recheck captured identities rather than rebinding a late changed graph.
    for ref in (manifest_ref, recipe_ref, linked_ref):
        if ref is not None:
            split.read(root, ref)
    return manifest_ref, recipe_ref


def media_sources(root: Path, manifest_ref: dict, manifest: dict) -> dict[str, str]:
    """Enumerate every exact image/mask consumed by a manifest, including retained rows."""
    result = {}
    for channel in manifest.get("channels", {}).values():
        if channel.get("source") == "image":
            relative = channel["path"]
            result[relative] = manifest_member(root, manifest_ref["path"], relative)
    for binding in manifest.get("surface_detail_bindings", []):
        placement = binding["placement"]
        if placement.get("mode") == "mask_image":
            relative = placement["mask_path"]
            path = manifest_member(root, manifest_ref["path"], relative)
            if split.reference(root, path)["sha256"] != placement["mask_sha256"]:
                raise ValueError("authored split source placement mask hash changed")
            result[relative] = path
    return dict(sorted(result.items()))


def material_projection(
    root: Path, rule: dict, derivative: dict
) -> tuple[dict | None, dict | None]:
    """Clone exact graph scalars/images while selecting only the declared host's binding rows."""
    source_manifest, source_recipe = derivative["source_manifest"], derivative["source_recipe"]
    manifest = json.loads(split.read(root, source_manifest)) if source_manifest else None
    recipe = json.loads(split.read(root, source_recipe)) if source_recipe else None
    if (source_manifest is None) != (derivative["candidate_manifest"] is None) or (
        source_recipe is None
    ) != (derivative["candidate_recipe"] is None):
        raise ValueError("authored split material derivative cannot invent or drop a graph")
    new_manifest, new_recipe = copy.deepcopy(manifest), copy.deepcopy(recipe)
    if new_manifest is not None:
        selected = set(rule["surface_detail_ids"])
        if not selected <= set(new_manifest.get("surface_detail_ids", [])):
            raise ValueError("authored split source manifest lacks an exact declared detail row")
        bindings = new_manifest.get("surface_detail_bindings", [])
        kept = [item for item in bindings if item["parent_object_id"] == rule["target_object_id"]]
        if bindings and {item["detail_id"] for item in kept} != selected:
            raise ValueError("authored split manifest must select every exact host/detail binding")
        new_manifest["material_id"] = rule["new_material_id"]
        new_manifest["surface_detail_ids"] = [
            item for item in manifest["surface_detail_ids"] if item in selected
        ]
        if "surface_detail_bindings" in new_manifest:
            new_manifest["surface_detail_bindings"] = kept
            for binding in kept:
                if binding["material_id"] != rule["source_material_id"]:
                    raise ValueError("authored split source binding has foreign material")
                binding["material_id"] = rule["new_material_id"]
        if new_manifest.get("shader_recipe"):
            new_manifest["shader_recipe"] = PurePosixPath(
                derivative["candidate_recipe"]["path"]
            ).name
        # Channel and mask paths keep their exact original manifest-local spellings;
        # every referenced media byte is copied verbatim into the new run-owned graph.
    if new_recipe is not None:
        new_recipe["material_id"] = rule["new_material_id"]
        if new_recipe.get("texture_manifest"):
            new_recipe["texture_manifest"] = derivative["candidate_manifest"]["path"]
    return new_manifest, new_recipe


def material_dependencies(
    root: Path, scene: dict, material_plan: dict, derivatives: list[dict]
) -> dict[str, str]:
    """Traverse finite declared manifest/recipe path cycles and every media dependency."""
    pending = []
    for item in [*scene["materials"], *material_plan["materials"]]:
        for key, kind in (("texture_manifest", "manifest"), ("shader_recipe", "recipe")):
            if item.get(key):
                pending.append((item[key], kind))
    for derivative in derivatives:
        for key, kind in (
            ("source_manifest", "manifest"),
            ("candidate_manifest", "manifest"),
            ("source_recipe", "recipe"),
            ("candidate_recipe", "recipe"),
        ):
            if derivative[key]:
                pending.append((derivative[key]["path"], kind))
    visited, kinds, folded, total = {}, {}, set(), 0
    while pending:
        path, kind = pending.pop()
        if path in visited:
            if kinds[path] != kind:
                raise ValueError("authored split material closure has conflicting file roles")
            continue
        if len(visited) >= 512 or path.casefold() in folded:
            raise ValueError("authored split material closure exceeds bounded unique inventory")
        ref = split.reference(root, path)
        data = split.read(root, ref)
        total += len(data)
        if total > 64 * 1024 * 1024:
            raise ValueError("authored split material closure exceeds byte bound")
        visited[path], kinds[path] = ref["sha256"], kind
        folded.add(path.casefold())
        if kind == "image":
            continue
        value = json.loads(data)
        if kind == "manifest":
            for media_path in media_sources(root, ref, value).values():
                pending.append((media_path, "image"))
            if value.get("shader_recipe"):
                pending.append((manifest_member(root, path, value["shader_recipe"]), "recipe"))
            generated = (value.get("provenance") or {}).get("generated_sha256")
            if generated is not None:
                images = {
                    key: member
                    for key, member in value["channels"].items()
                    if member.get("source") == "image"
                }
                if set(generated) != set(images) or any(
                    split.reference(root, manifest_member(root, path, images[key]["path"]))[
                        "sha256"
                    ]
                    != digest
                    for key, digest in generated.items()
                ):
                    raise ValueError("authored split image provenance hash changed")
        elif value.get("texture_manifest"):
            pending.append((value["texture_manifest"], "manifest"))
    return dict(sorted(visited.items()))


def validate_material_derivatives(
    root: Path, plan: dict, scene: dict, material_plan: dict
) -> dict[str, str]:
    """Reject any undeclared texture/recipe/identity/binding/image change in the cloned graph."""
    derivatives = plan["material_derivatives"]
    if len(derivatives) != len(plan["clone_rules"]):
        raise ValueError("authored split material derivative coverage changed")
    for ordinal, (rule, item) in enumerate(zip(plan["clone_rules"], derivatives, strict=True)):
        if item["object_id"] != rule["target_object_id"]:
            raise ValueError("authored split material derivative host changed")
        source_manifest, source_recipe = material_sources(root, scene, material_plan, rule)
        if item["source_manifest"] != source_manifest or item["source_recipe"] != source_recipe:
            raise ValueError("authored split material source graph changed")
        target_dir = material_directory(plan["run_id"], rule["source_material_id"])
        for key, leaf in (
            ("candidate_manifest", f"manifest_{ordinal:03d}.json"),
            ("candidate_recipe", f"recipe_{ordinal:03d}.json"),
        ):
            if item[key] and item[key]["path"] != f"{target_dir}/{leaf}":
                raise ValueError("authored split cloned graph path is outside its fixed run")
        manifest, recipe = material_projection(root, rule, item)
        for key, expected in (("candidate_manifest", manifest), ("candidate_recipe", recipe)):
            if expected is not None and split.stable(
                json.loads(split.read(root, item[key]))
            ) != split.stable(expected):
                raise ValueError(
                    "authored split material graph changed outside exact metadata projection"
                )
        source_media = (
            media_sources(root, source_manifest, json.loads(split.read(root, source_manifest)))
            if source_manifest
            else {}
        )
        expected_media = {}
        for relative, path in source_media.items():
            expected_media[path] = {
                "path": f"{target_dir}/{relative}",
                "sha256": split.reference(root, path)["sha256"],
            }
        if item["media_copies"] != expected_media:
            raise ValueError("authored split material media copy inventory changed")
        for ref in item["media_copies"].values():
            split.read(root, ref)
    return material_dependencies(root, scene, material_plan, derivatives)


def identity_split_closure(run_id, files, source_files, source_provenance):
    """Bind immutable historical source appearance without claiming a MaterialPlan promotion."""
    return {
        "schema_version": "0.2.0",
        "run_id": run_id,
        "files": files,
        "native_identity_split_source": {
            "construction": "bound_source_blend_identity_clone_v1",
            "blend_sha256": source_files["blender/scene.blend"]["sha256"],
            "material_plan_sha256": source_files["analysis/material_plan.json"]["sha256"],
            "build_provenance_sha256": split.sha(split.encode(source_provenance)),
        },
    }


def provenance_closure(root: Path, metadata: dict) -> dict | None:
    """Select the nearest validated specialized ancestor's immutable material graph closure."""
    pointer, seen = metadata.get("attachment_revision"), set()
    while pointer is not None:
        if pointer["path"] in seen or len(seen) >= 64:
            raise ValueError("authored split material provenance ancestry is cyclic or excessive")
        seen.add(pointer["path"])
        record = json.loads(split.read(root, pointer))
        if record.get("kind") == "solid_root_attachment_material_identity_split_revision":
            plan, _ = split.run_contract(root, record["run_id"], "plan.json", "plan")
            for path, digest in plan["material_dependencies"].items():
                split.read(root, {"path": path, "sha256": digest})
            return identity_split_closure(
                record["run_id"],
                plan["material_dependencies"],
                plan["source_files"],
                json.loads(split.read(root, plan["source_build_provenance"])),
            )
        pointer = record["previous_revision"]
    return None
