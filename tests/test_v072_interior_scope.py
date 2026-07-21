"""Regression coverage for the opt-in V0.7.2 architectural-interior boundary."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from codex_blender_modeler.architecture.models import (
    InteriorScope,
    InteriorScopeApproval,
    InteriorScopeValidation,
)
from codex_blender_modeler.architecture.service import (
    APPROVAL_RELATIVE_PATH,
    SCOPE_RELATIVE_PATH,
    approve_interior_scope,
    initialize_interior_scope,
    validate_scene_interior_scope,
)
from codex_blender_modeler.build_provenance import (
    BuildProvenanceError,
    collect_build_provenance,
    sha256_file,
)
from codex_blender_modeler.cli import app
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.reporting.service import collect_job_report_payload
from codex_blender_modeler.revision import apply_revision_plan
from codex_blender_modeler.validation import load_scene_spec
from codex_blender_modeler.versioning import (
    INTERIOR_SCOPE_SCHEMA_VERSION,
    PROJECT_VERSION,
)
from codex_blender_modeler.workspace import create_job

ROOT = Path(__file__).resolve().parents[1]
INTERIOR_CLI_COMMANDS = {
    "interior-scope-init",
    "interior-scope-approve",
    "interior-scope-status",
    "interior-scope-validate",
}
INTERIOR_MCP_TOOLS = {
    "initialize_interior_scope",
    "get_interior_scope_status",
    "validate_interior_scope",
}


def _scene_payload(
    job_id: str,
    *,
    object_id: str = "building.exterior.wall",
    tags: list[str] | None = None,
    evidence_status: str = "observed",
) -> dict[str, object]:
    """Create one compact but schema-valid SceneSpec fixture for interior policy tests."""

    return {
        "schema_version": "0.2.0",
        "job_id": job_id,
        "mode": "concept",
        "units": "METERS",
        "nominal_scene_size": [10.0, 8.0, 4.0],
        "sources": [
            {
                "id": "reference",
                "path": "input/reference.png",
                "kind": "reference",
                "immutable": True,
                "scale_anchors": [],
            }
        ],
        "materials": [
            {
                "id": "mat.wall",
                "name": "Wall",
                "shader": "principled",
                "base_color": [0.6, 0.6, 0.6, 1.0],
                "roughness": 0.7,
                "metallic": 0.0,
            }
        ],
        "objects": [
            {
                "id": object_id,
                "name": "Test wall",
                "geometry": {
                    "kind": "primitive",
                    "primitive": "cube",
                    "dimensions": [2.0, 0.2, 2.5],
                },
                "material_id": "mat.wall",
                "tags": list(tags or []),
                "evidence": [
                    {
                        "source_id": "reference",
                        "bbox_norm": [0.1, 0.1, 0.9, 0.9],
                        "status": evidence_status,
                        "confidence": 0.8,
                    }
                ],
            }
        ],
        "camera": {
            "projection": "ORTHO",
            "location": [5.0, -7.0, 4.0],
            "target": [0.0, 0.0, 1.0],
            "focal_length_mm": 50.0,
            "ortho_scale": 12.0,
            "resolution": [128, 128],
        },
    }


def _create_workspace_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    job_id: str = "interior_asset",
    payload: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    """Create one isolated real workspace job and write its canonical SceneSpec."""

    workspace_root = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace_root))
    reference = tmp_path / f"{job_id}.png"
    reference.write_bytes(b"reference")
    create_job(job_id, reference, "concept", [])
    root = workspace_root / job_id
    scene_path = root / "analysis" / "scene_spec.json"
    scene_path.write_text(
        json.dumps(payload or _scene_payload(job_id), indent=2) + "\n",
        encoding="utf-8",
    )
    return root, scene_path


def _approve_scope(
    job_id: str,
    root: Path,
    *,
    allowed: list[str] | None = None,
    excluded: list[str] | None = None,
    levels: list[str] | None = None,
    spaces: list[str] | None = None,
    furnishing: str = "none",
) -> None:
    """Create and approve one exact proxy scope for a test workspace."""

    initialize_interior_scope(
        job_id,
        policy="proxy",
        request="Create only the explicitly listed test interior.",
        allowed_semantic_prefixes=allowed or ["building.interior"],
        excluded_semantic_prefixes=excluded or [],
        levels=levels or [],
        spaces=spaces or [],
        furnishing=furnishing,
        evidence_status="inferred",
    )
    scope_path = root / SCOPE_RELATIVE_PATH
    approve_interior_scope(
        job_id,
        scope_sha256=sha256_file(scope_path),
        approval_note="User approved this exact test boundary.",
        manual_confirmation=True,
    )


def test_legacy_job_without_scope_stays_disabled_without_creating_architecture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep exterior-only legacy jobs valid without creating opt-in contract files."""

    root, scene_path = _create_workspace_job(tmp_path, monkeypatch)

    assert load_scene_spec(scene_path).job_id == "interior_asset"
    assert not (root / "architecture").exists()


@pytest.mark.parametrize("explicit_disabled", [False, True])
@pytest.mark.parametrize(
    ("object_id", "tags"),
    [
        ("building.exterior.wall", ["interior"]),
        ("building.interior.wall", []),
        ("building.Interior.lobby.wall", []),
        ("building.room.lobby.wall", []),
        ("building.lobby.wall", []),
        ("building.exterior.wall", ["Room"]),
    ],
)
def test_default_or_explicit_disabled_scope_rejects_interior_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    explicit_disabled: bool,
    object_id: str,
    tags: list[str],
) -> None:
    """Reject both explicit tags and the reserved interior ID namespace by default."""

    payload = _scene_payload("interior_asset", object_id=object_id, tags=tags)
    root, scene_path = _create_workspace_job(
        tmp_path,
        monkeypatch,
        payload=payload,
    )
    if explicit_disabled:
        initialize_interior_scope("interior_asset")

    with pytest.raises(ValueError, match="InteriorScope validation failed"):
        load_scene_spec(scene_path)
    if not explicit_disabled:
        assert not (root / "architecture").exists()


def test_facade_helpers_and_incidental_text_do_not_trigger_interior_policy() -> None:
    """Allow facade backing and incidental inferred-interior text without false positives."""

    payload = _scene_payload(
        "facade_asset",
        object_id="building.exterior.window_recess",
        tags=["facade_backing", "window_recess", "inferred-interior"],
    )
    report = validate_scene_interior_scope(
        SceneSpec.model_validate(payload),
        Path("unused-job-root"),
    )

    assert report.ok is True
    assert report.scope_state == "default_disabled"
    assert report.interior_object_ids == []


def test_enabled_draft_without_hash_approval_rejects_interior_geometry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep an enabled scope as a non-executable draft until the user approves its hash."""

    payload = _scene_payload(
        "interior_asset",
        object_id="building.interior.lobby.wall",
        tags=["interior"],
        evidence_status="inferred",
    )
    root, _ = _create_workspace_job(tmp_path, monkeypatch, payload=payload)
    initialize_interior_scope(
        "interior_asset",
        policy="proxy",
        request="Create a lobby proxy.",
        allowed_semantic_prefixes=["building.interior.lobby"],
        evidence_status="inferred",
    )

    report = validate_scene_interior_scope(SceneSpec.model_validate(payload), root)

    assert report.ok is False
    assert report.scope_state == "draft"
    assert any("matching user-approved scope" in error for error in report.errors)


def test_exact_hash_approval_allows_only_the_declared_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept a located interior object when the exact scope hash and prefix match."""

    payload = _scene_payload(
        "interior_asset",
        object_id="building.interior.lobby.wall",
        tags=["interior", "level:level_01", "space:lobby"],
        evidence_status="inferred",
    )
    root, scene_path = _create_workspace_job(tmp_path, monkeypatch, payload=payload)
    _approve_scope(
        "interior_asset",
        root,
        allowed=["building.interior.lobby"],
        levels=["level_01"],
        spaces=["lobby"],
    )

    report = validate_scene_interior_scope(SceneSpec.model_validate(payload), root)

    assert report.ok is True
    assert report.scope_state == "approved"
    assert report.approval_valid is True
    assert load_scene_spec(scene_path).objects[0].id == "building.interior.lobby.wall"


@pytest.mark.parametrize("receipt_state", ["stale", "wrong_hash", "revoked"])
def test_stale_wrong_hash_or_revoked_approval_rejects_interior_geometry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt_state: str,
) -> None:
    """Fail closed whenever an approval no longer matches the active scope exactly."""

    payload = _scene_payload(
        "interior_asset",
        object_id="building.interior.lobby.wall",
        tags=["interior"],
        evidence_status="inferred",
    )
    root, _ = _create_workspace_job(tmp_path, monkeypatch, payload=payload)
    _approve_scope("interior_asset", root, allowed=["building.interior.lobby"])
    scope_path = root / SCOPE_RELATIVE_PATH
    approval_path = root / APPROVAL_RELATIVE_PATH
    if receipt_state == "stale":
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
        scope["notes"] = ["Scope bytes changed after approval."]
        scope_path.write_text(json.dumps(scope, indent=2) + "\n", encoding="utf-8")
    else:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        if receipt_state == "wrong_hash":
            approval["scope_sha256"] = "0" * 64
        else:
            approval["status"] = "revoked"
        approval_path.write_text(json.dumps(approval, indent=2) + "\n", encoding="utf-8")

    report = validate_scene_interior_scope(SceneSpec.model_validate(payload), root)

    assert report.ok is False
    expected_state = "stale" if receipt_state == "wrong_hash" else receipt_state
    assert report.scope_state == expected_state
    assert report.approval_valid is False


@pytest.mark.parametrize(
    ("object_id", "tags", "scope_options", "message"),
    [
        (
            "building.interior.kitchen.wall",
            ["interior"],
            {"allowed": ["building.interior.lobby"]},
            "outside approved semantic prefixes",
        ),
        (
            "building.interior.private.wall",
            ["interior"],
            {
                "allowed": ["building.interior"],
                "excluded": ["building.interior.private"],
            },
            "inside an excluded semantic prefix",
        ),
        (
            "building.interior.lobby.wall",
            ["interior"],
            {
                "allowed": ["building.interior.lobby"],
                "levels": ["level_01"],
                "spaces": ["lobby"],
            },
            "missing a level:<id> locator tag",
        ),
        (
            "building.interior.lobby.chair",
            ["interior", "interior_furniture"],
            {"allowed": ["building.interior.lobby"], "furnishing": "none"},
            "furnishing is not approved",
        ),
        (
            "building.interior.lobby.chair",
            ["interior", "interior_furniture", "furnishing:detailed"],
            {"allowed": ["building.interior.lobby"], "furnishing": "proxy"},
            "exceeds proxy approval",
        ),
    ],
)
def test_approved_scope_rejects_outside_excluded_unlocated_or_unfurnished_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    object_id: str,
    tags: list[str],
    scope_options: dict[str, object],
    message: str,
) -> None:
    """Enforce semantic, exclusion, locator, and furnishing boundaries after approval."""

    payload = _scene_payload(
        "interior_asset",
        object_id=object_id,
        tags=tags,
        evidence_status="inferred",
    )
    root, _ = _create_workspace_job(tmp_path, monkeypatch, payload=payload)
    _approve_scope("interior_asset", root, **scope_options)

    report = validate_scene_interior_scope(SceneSpec.model_validate(payload), root)

    assert report.ok is False
    assert any(message in error for error in report.errors)


def test_semantic_prefix_matching_stops_at_dot_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent lobby authorization from accidentally covering lobby_extra identifiers."""

    payload = _scene_payload(
        "interior_asset",
        object_id="building.interior.lobby_extra.wall",
        tags=["interior"],
        evidence_status="inferred",
    )
    root, _ = _create_workspace_job(tmp_path, monkeypatch, payload=payload)
    _approve_scope("interior_asset", root, allowed=["building.interior.lobby"])

    report = validate_scene_interior_scope(SceneSpec.model_validate(payload), root)

    assert report.ok is False
    assert any("outside approved semantic prefixes" in error for error in report.errors)


def test_measured_scope_requires_observed_evidence_and_constraint_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bind measured interiors to measured mode, observed source evidence, and constraints."""

    payload = _scene_payload(
        "interior_asset",
        object_id="building.interior.lobby.wall",
        tags=["interior"],
        evidence_status="observed",
    )
    payload["mode"] = "measured"
    root, _ = _create_workspace_job(tmp_path, monkeypatch, payload=payload)
    initialize_interior_scope(
        "interior_asset",
        policy="measured",
        request="Build only the measured lobby interior.",
        allowed_semantic_prefixes=["building.interior.lobby"],
        evidence_status="measured",
    )
    approve_interior_scope(
        "interior_asset",
        scope_sha256=sha256_file(root / SCOPE_RELATIVE_PATH),
        approval_note="I manually approve this measured lobby boundary.",
        manual_confirmation=True,
    )

    missing = validate_scene_interior_scope(SceneSpec.model_validate(payload), root)
    assert missing.ok is False
    assert any("requires constraints" in error for error in missing.errors)

    constraint_path = root / "constraints" / "constraints.json"
    constraint_path.write_text(
        json.dumps(
            {
                "schema_version": "0.4.0",
                "job_id": "interior_asset",
                "units": "METERS",
                "constraints": [
                    {
                        "id": "lobby.width",
                        "kind": "dimension",
                        "target_id": "building.interior.lobby",
                        "axis": "X",
                        "value_m": 4.0,
                        "tolerance_m": 0.01,
                    }
                ],
                "notes": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    covered = validate_scene_interior_scope(SceneSpec.model_validate(payload), root)
    assert covered.ok is True

    payload["objects"][0]["evidence"][0]["status"] = "inferred"  # type: ignore[index]
    inferred = validate_scene_interior_scope(SceneSpec.model_validate(payload), root)
    assert inferred.ok is False
    assert any("inferred source evidence" in error for error in inferred.errors)


def test_revision_cannot_introduce_unapproved_interior_or_mutate_canonical_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a guarded revision before writing when it adds an unapproved interior tag."""

    root, scene_path = _create_workspace_job(tmp_path, monkeypatch)
    canonical_before = scene_path.read_bytes()
    plan = {
        "schema_version": "0.1.0",
        "job_id": "interior_asset",
        "base_spec_sha256": sha256_file(scene_path),
        "request": "Add an interior without approval.",
        "operations": [
            {
                "op": "append",
                "target_type": "object",
                "target_id": "building.exterior.wall",
                "path": ["tags"],
                "value": "interior",
                "reason": "Exercise the interior revision guard.",
            }
        ],
        "acceptance_criteria": ["The guard rejects the unapproved change."],
        "assumptions": [],
    }
    plan_path = root / "analysis" / "revision_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="InteriorScope validation failed"):
        apply_revision_plan(scene_spec_path=scene_path, plan_path=plan_path)

    assert scene_path.read_bytes() == canonical_before


def test_interior_contracts_conditionally_extend_build_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve legacy payload shape while binding any explicit scope and approval hashes."""

    root, _ = _create_workspace_job(tmp_path, monkeypatch)
    baseline = collect_build_provenance(root, "interior_asset")
    legacy_keys = {
        "schema_version",
        "job_id",
        "scene_spec_path",
        "scene_spec_sha256",
        "geometry_payloads_sha256",
        "camera_fingerprint",
        "material_plan_path",
        "material_plan_sha256",
        "materials",
        "fingerprint",
    }
    assert set(baseline) == legacy_keys
    assert "interior_contracts" not in baseline

    initialize_interior_scope(
        "interior_asset",
        policy="proxy",
        request="Create a bounded lobby proxy.",
        allowed_semantic_prefixes=["building.interior.lobby"],
        evidence_status="inferred",
    )
    scoped = collect_build_provenance(root, "interior_asset")
    assert scoped["interior_contracts"]["scope_sha256"] == sha256_file(
        root / SCOPE_RELATIVE_PATH
    )
    assert scoped["interior_contracts"]["approval_sha256"] is None
    assert scoped["fingerprint"] != baseline["fingerprint"]

    approve_interior_scope(
        "interior_asset",
        scope_sha256=sha256_file(root / SCOPE_RELATIVE_PATH),
        approval_note="Approve provenance binding.",
        manual_confirmation=True,
    )
    approved = collect_build_provenance(root, "interior_asset")
    assert approved["interior_contracts"]["approval_sha256"] == sha256_file(
        root / APPROVAL_RELATIVE_PATH
    )
    assert approved["fingerprint"] != scoped["fingerprint"]


def test_build_provenance_rejects_unapproved_interior_without_loader_precheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent direct build or packaging callers from bypassing the interior guard."""

    payload = _scene_payload(
        "interior_asset",
        object_id="building.interior.lobby.wall",
        tags=["interior"],
        evidence_status="inferred",
    )
    root, _ = _create_workspace_job(tmp_path, monkeypatch, payload=payload)

    with pytest.raises(BuildProvenanceError, match="InteriorScope validation failed"):
        collect_build_provenance(root, "interior_asset")


def test_v072_interior_schemas_match_strict_models() -> None:
    """Keep checked-in interior schemas identical to their Pydantic contracts."""

    contracts = {
        "interior_scope.schema.json": InteriorScope,
        "interior_scope_approval.schema.json": InteriorScopeApproval,
        "interior_scope_validation.schema.json": InteriorScopeValidation,
    }
    for filename, model in contracts.items():
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema == model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "0.1.0"


def test_v072_interior_cli_and_mcp_surface_is_explicit() -> None:
    """Keep approval in the CLI while exposing only non-approving MCP operations."""

    help_result = CliRunner().invoke(app, ["--help"])
    assert help_result.exit_code == 0
    for command in INTERIOR_CLI_COMMANDS:
        assert command in help_result.stdout

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert INTERIOR_MCP_TOOLS <= enabled
    assert "approve_interior_scope" not in enabled


def test_cli_approval_requires_the_exact_interactive_hash_phrase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse noninteractive or mismatched approval and accept an exact manual phrase."""

    root, _ = _create_workspace_job(tmp_path, monkeypatch)
    initialize_interior_scope(
        "interior_asset",
        policy="proxy",
        request="Create only a lobby proxy.",
        allowed_semantic_prefixes=["building.interior.lobby"],
        evidence_status="inferred",
    )
    scope_hash = sha256_file(root / SCOPE_RELATIVE_PATH)
    with pytest.raises(PermissionError, match="interactive CLI"):
        approve_interior_scope(
            "interior_asset",
            scope_sha256=scope_hash,
            approval_note="This internal call must not be accepted.",
            manual_confirmation=False,
        )
    arguments = [
        "interior-scope-approve",
        "interior_asset",
        "--scope-sha256",
        scope_hash,
        "--approval-note",
        "I approve this exact lobby boundary.",
    ]
    runner = CliRunner()

    rejected = runner.invoke(app, arguments, input="APPROVE wrong-hash\n")
    assert rejected.exit_code != 0
    assert not (root / APPROVAL_RELATIVE_PATH).exists()

    accepted = runner.invoke(app, arguments, input=f"APPROVE {scope_hash}\n")
    assert accepted.exit_code == 0
    assert (root / APPROVAL_RELATIVE_PATH).is_file()


def test_v072_project_and_interior_contract_versions_are_independent() -> None:
    """Advance the host version without changing earlier geometry or portable contracts."""

    assert PROJECT_VERSION == "0.9.0"
    assert INTERIOR_SCOPE_SCHEMA_VERSION == "0.1.0"


def test_build_pdf_payload_includes_interior_scope_machine_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose interior contracts and validation in build PDFs without replacing their JSON."""

    root, _ = _create_workspace_job(tmp_path, monkeypatch)
    initialize_interior_scope("interior_asset")
    validate_scene_interior_scope(
        SceneSpec.model_validate(_scene_payload("interior_asset")),
        root,
        write_report=True,
    )

    payload = collect_job_report_payload("interior_asset", "build")

    assert payload["documents"]["interior_scope"]["policy"] == "disabled"
    assert payload["documents"]["interior_scope_validation"]["ok"] is True
    assert "interior_scope_approval" not in payload["documents"]
