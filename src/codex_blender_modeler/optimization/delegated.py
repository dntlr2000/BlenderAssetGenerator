"""Explicit host-only issuance and single-use validation of bounded technical delegation."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

from ..orchestration.locks import workflow_write_lock
from ..workspace import current_job_write_lock_owner, job_dir, resolve_job_input_path, sha256_file
from .delegated_models import (
    DelegatedAssetIdentityV01,
    DelegatedOptimizationAuthorizationV01,
    DelegatedOptimizationConsumptionV01,
    DelegatedOptimizationScopeV01,
)
from .io import job_relative, load_model, utc_now, validate_filesystem_id
from .models import (
    AssetProfile,
    HashedArtifact,
    MeshPreflightReport,
    OptimizationPlan,
    OptimizationReview,
)
from .preflight import load_asset_profile, profile_artifact
from .provenance import collect_source_provenance

AUTHORIZATION_FILE = "optimization_delegated_authorization.json"
CONSUMPTION_FILE = "optimization_delegated_consumption.json"
SCOPE_SNAPSHOT = "optimization_delegated_scope.json"
TEXT_SNAPSHOT = "optimization_delegated_text.txt"
CONFIRMATION_SNAPSHOT = "optimization_delegated_confirmation.txt"
CLAIM_SNAPSHOT = "optimization_delegated_claim.json"
TASK_BINDING_SNAPSHOT = "optimization_delegated_task_binding.json"
PROFILE_SNAPSHOT = "optimization_delegated_profile.json"
QUALITY_SNAPSHOT = "optimization_delegated_source_quality.json"


@contextmanager
def _host_lock(root: Path, job_id: str, owner: str, *, held_workflow_lock: str | None = None):
    """Reuse only an explicitly named verified workflow lock, otherwise acquire exclusively."""

    if held_workflow_lock is not None:
        if current_job_write_lock_owner(job_id) != held_workflow_lock:
            raise ValueError("delegated caller does not own the named workflow lock")
        yield
    else:
        with workflow_write_lock(root, job_id, owner):
            yield


def _task_binding_path(root: Path, text_sha256: str, confirmation_sha256: str) -> Path:
    """Pin source delegation bytes independently of caller labels to prevent budget resets."""

    digest = hashlib.sha256(f"{text_sha256}:{confirmation_sha256}".encode()).hexdigest()
    return _safe_path(root, root / "optimization" / "delegation_task_bindings" / f"{digest}.json")


def _require_opt_in(enabled: bool) -> None:
    """Keep this optional authority unavailable unless the caller explicitly selects it."""

    if enabled is not True:
        raise ValueError("delegated optimization requires explicit enable_delegated_authority")


def _safe_path(root: Path, path: Path) -> Path:
    """Reuse native containment and reparse checks for every delegated artifact path."""

    from ..production.validation import ensure_contained_production_path

    candidate = path if path.is_absolute() else root / path
    if any(part == ".." for part in candidate.parts):
        raise ValueError("delegated authority path is not normalized")
    return ensure_contained_production_path(root, candidate, must_exist=False)


def _read_exact(root: Path, artifact: HashedArtifact) -> Path:
    """Rehash every declared artifact through its unlinked job-contained path."""

    path = _safe_path(root, Path(artifact.path))
    if not path.is_file() or sha256_file(path) != artifact.sha256:
        raise ValueError(f"delegated authority artifact changed: {artifact.path}")
    return path


def _artifact(root: Path, path: Path, identity: str) -> HashedArtifact:
    """Capture an exact immutable artifact without extending V0.7 role literals."""

    _safe_path(root, path)
    return HashedArtifact(
        id=identity, kind="other", path=job_relative(root, path), sha256=sha256_file(path)
    )


def _write_once(path: Path, content: bytes) -> None:
    """Publish only a new immutable file; partial failures remain blocking evidence."""

    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()


def _write_contract_once(path: Path, model) -> None:
    """Serialize an append-only strict contract without replacing earlier evidence."""

    _write_once(path, (model.model_dump_json(indent=2) + "\n").encode("utf-8"))


def _reference_hash(root: Path, job_id: str) -> str:
    """Verify immutable primary reference bytes, not just the job name or metadata."""

    metadata_path = _safe_path(root, root / "job.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("job_id") != job_id:
        raise ValueError("delegated authority job identity differs")
    expected = metadata["reference_sha256"]
    reference = resolve_job_input_path(root, metadata["reference_path"], expected)
    _safe_path(root, reference)
    if sha256_file(reference) != expected:
        raise ValueError("delegated authority reference changed")
    return expected


def _validate_scope(
    root: Path, scope_path: Path, expected_sha256: str, job_id: str, *, active: bool = True
):
    """Validate exact host-issued scope/text and match this job to the five-asset set."""

    _safe_path(root, scope_path)
    if sha256_file(scope_path) != expected_sha256:
        raise ValueError("delegation scope SHA-256 differs")
    scope = load_model(scope_path, DelegatedOptimizationScopeV01)
    validate_filesystem_id(scope.delegation_id, "delegation_id")
    expected_path = root / "optimization" / "delegations" / scope.delegation_id / "scope.json"
    if scope.job_id != job_id or scope_path != expected_path:
        raise ValueError("delegation scope has foreign job or path identity")
    text_path = _read_exact(root, scope.delegation_text)
    if text_path != expected_path.parent / "delegation.txt":
        raise ValueError("delegation text is outside its immutable scope")
    confirmation_path = _read_exact(root, scope.extension_confirmation_text)
    if confirmation_path != expected_path.parent / "extension_confirmation.txt":
        raise ValueError("extension confirmation is outside its immutable scope")
    if active and utc_now() >= scope.expires_at:
        raise ValueError("delegated technical completion scope has expired")
    binding_path = _task_binding_path(
        root, scope.delegation_text.sha256, scope.extension_confirmation_text.sha256
    )
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    if binding != {"scope_path": job_relative(root, scope_path), "scope_sha256": expected_sha256}:
        raise ValueError("delegation task binding changed or was renamed")
    reference = _reference_hash(root, job_id)
    if not any(
        item.job_id == job_id and item.reference_sha256 == reference
        for item in scope.allowed_assets
    ):
        raise ValueError("job/reference is outside the exact delegated five-asset scope")
    return scope, text_path, reference


def create_delegated_optimization_scope(
    job_id: str,
    *,
    delegation_id: str,
    delegation_text_path: str,
    delegation_text_sha256: str,
    extension_confirmation_text_path: str,
    extension_confirmation_text_sha256: str,
    task_context_id: str,
    expires_at: str,
    allowed_assets_json: str,
    extension_confirmation: str,
    enable_delegated_authority: bool = False,
) -> DelegatedOptimizationScopeV01:
    """Snapshot explicit user text and five declared identities under host opt-in."""

    _require_opt_in(enable_delegated_authority)
    validate_filesystem_id(delegation_id, "delegation_id")
    root = job_dir(job_id)
    text_path = _safe_path(root, Path(delegation_text_path))
    content = text_path.read_bytes()
    if not content.strip() or sha256_file(text_path) != delegation_text_sha256:
        raise ValueError("exact nonempty delegation text SHA-256 is required")
    content.decode("utf-8")
    confirmation_path = _safe_path(root, Path(extension_confirmation_text_path))
    confirmation = confirmation_path.read_bytes()
    if (
        not confirmation.strip()
        or sha256_file(confirmation_path) != extension_confirmation_text_sha256
    ):
        raise ValueError("exact nonempty extension confirmation SHA-256 is required")
    confirmation.decode("utf-8")
    identities = [
        DelegatedAssetIdentityV01.model_validate(item) for item in json.loads(allowed_assets_json)
    ]
    target = _safe_path(root, root / "optimization" / "delegations" / delegation_id)
    scope = DelegatedOptimizationScopeV01(
        delegation_id=delegation_id,
        job_id=job_id,
        delegation_text=HashedArtifact(
            id=f"delegation.{delegation_id}",
            kind="other",
            path=job_relative(root, target / "delegation.txt"),
            sha256=delegation_text_sha256,
        ),
        extension_confirmation_text=HashedArtifact(
            id=f"confirmation.{delegation_id}",
            kind="other",
            path=job_relative(root, target / "extension_confirmation.txt"),
            sha256=extension_confirmation_text_sha256,
        ),
        task_context_id=task_context_id,
        expires_at=expires_at,
        allowed_assets=identities,
        extension_confirmation=extension_confirmation,
        created_at=utc_now(),
    )
    reference = _reference_hash(root, job_id)
    if not any(item.job_id == job_id and item.reference_sha256 == reference for item in identities):
        raise ValueError("current job/reference is outside the declared delegation")
    with _host_lock(root, job_id, f"delegation-{delegation_id}"):
        binding = _task_binding_path(
            root, delegation_text_sha256, extension_confirmation_text_sha256
        )
        binding.parent.mkdir(parents=True, exist_ok=True)
        scope_bytes = (scope.model_dump_json(indent=2) + "\n").encode("utf-8")
        _write_once(
            binding,
            json.dumps(
                {
                    "scope_path": job_relative(root, target / "scope.json"),
                    "scope_sha256": hashlib.sha256(scope_bytes).hexdigest(),
                },
                sort_keys=True,
            ).encode("utf-8"),
        )
        target.mkdir(parents=True, exist_ok=False)
        _write_once(target / "delegation.txt", content)
        _write_once(target / "extension_confirmation.txt", confirmation)
        _write_contract_once(target / "scope.json", scope)
    return scope


def _current_review(
    root: Path, run_root: Path, job_id: str, plan_sha256: str, *, active: bool = True
):
    """Validate exact reviewed evidence; recheck live candidate bytes only for new effects."""

    from .optimizer import _require_source_quality_current, _validate_reviewed_directives

    plan_path = _safe_path(root, run_root / "review_plan.json")
    plan = load_model(plan_path, OptimizationPlan)
    review_path = _safe_path(root, run_root / "optimization_review.json")
    review = load_model(review_path, OptimizationReview)
    preflight_path = _read_exact(root, plan.preflight_report)
    preflight = load_model(preflight_path, MeshPreflightReport)
    if active:
        profile_path = _read_exact(root, plan.profile_artifact)
        profile = load_asset_profile(root, plan.profile_id)
        source = collect_source_provenance(root, job_id)
        for artifact in source.artifacts():
            _read_exact(root, artifact)
        _require_source_quality_current(root, plan.source_quality)
    else:
        profile_path = _safe_path(root, run_root / PROFILE_SNAPSHOT)
        if sha256_file(profile_path) != plan.profile_artifact.sha256:
            raise ValueError("delegated retained profile snapshot changed")
        profile = load_model(profile_path, AssetProfile)
        source = plan.source
        if plan.source_quality is not None:
            quality = _safe_path(root, run_root / QUALITY_SNAPSHOT)
            if sha256_file(quality) != plan.source_quality.report_artifact.sha256:
                raise ValueError("delegated retained source-quality snapshot changed")
    if (
        plan.status != "draft"
        or plan.job_id != job_id
        or plan.profile_id != "portable_gltf"
        or profile.primary_format != "glb"
        or profile.job_id != job_id
        or preflight_path != run_root / "mesh_preflight_report.json"
        or (active and profile_path != root / "asset_profiles" / "portable_gltf.json")
        or plan_sha256 != sha256_file(plan_path)
        or review.plan_sha256 != plan_sha256
        or review.job_id != job_id
        or review.run_id != run_root.name
        or review.profile_id != plan.profile_id
        or review.primary_format != "glb"
        or review.profile_artifact != plan.profile_artifact
        or review.preflight_report != plan.preflight_report
        or (active and plan.profile_artifact != profile_artifact(root, profile))
        or preflight.job_id != job_id
        or preflight.profile_id != plan.profile_id
        or preflight.profile_artifact != plan.profile_artifact
        or not preflight.ok
        or source != plan.source
        or source != preflight.source
        or source != review.source
        or review.source_quality != plan.source_quality
    ):
        raise ValueError(
            "delegated optimization review/source/profile/preflight is stale or foreign"
        )
    _validate_reviewed_directives(plan, preflight)
    return plan, review


def _require_exclusive(run_root: Path) -> None:
    """Never combine delegated authority with user or AQ policy evidence."""

    if any(
        ((run_root / name).exists() or (run_root / name).is_symlink())
        for name in ("optimization_approval.json", "optimization_policy_authorization.json")
    ):
        raise ValueError("optimization run mixes delegated, user or policy authority")


def _validate_claim_ledger(
    root: Path, scope_path: Path, scope: DelegatedOptimizationScopeV01
) -> list[Path]:
    """Detect lost/changed claims against every preserved run-owned issuance snapshot."""

    claim_root = _safe_path(root, scope_path.parent / "authorization_claims")
    claims = sorted(claim_root.iterdir()) if claim_root.is_dir() else []
    if len(claims) > scope.maximum_authorizations_per_job or [path.name for path in claims] != [
        f"{index:03}.json" for index in range(1, len(claims) + 1)
    ]:
        raise ValueError("delegation ordinal claim ledger has gaps or unknown entries")
    scope_hash = sha256_file(scope_path)
    expected_keys = {
        "run_id",
        "grant_ordinal",
        "authorization_path",
        "authorization_sha256",
        "scope_sha256",
    }
    for index, path in enumerate(claims, start=1):
        _safe_path(root, path)
        claim = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(claim, dict) or set(claim) != expected_keys:
            raise ValueError("delegation claim contract changed")
        validate_filesystem_id(claim["run_id"], "claim run_id")
        if (
            claim["grant_ordinal"] != index
            or claim["scope_sha256"] != scope_hash
            or claim["authorization_path"]
            != f"optimization/runs/{claim['run_id']}/{AUTHORIZATION_FILE}"
        ):
            raise ValueError("delegation claim identity changed")
        HashedArtifact(
            id=f"delegated.{claim['run_id']}",
            kind="other",
            path=claim["authorization_path"],
            sha256=claim["authorization_sha256"],
        )
        grant_path = _safe_path(root, root / claim["authorization_path"])
        if grant_path.exists():
            if sha256_file(grant_path) != claim["authorization_sha256"]:
                raise ValueError("delegation prior claim no longer binds its issued grant")
            previous = load_model(grant_path, DelegatedOptimizationAuthorizationV01)
            if (
                previous.scope.path != job_relative(root, scope_path)
                or previous.scope.sha256 != scope_hash
                or previous.job_id != scope.job_id
                or previous.run_id != claim["run_id"]
                or previous.grant_ordinal != index
            ):
                raise ValueError("delegation prior grant belongs to a different scope or ordinal")
            snapshot = _safe_path(root, grant_path.parent / CLAIM_SNAPSHOT)
            if snapshot.read_bytes() != path.read_bytes():
                raise ValueError("delegation prior claim snapshot differs")
    runs_root = _safe_path(root, root / "optimization" / "runs")
    for directory in runs_root.iterdir():
        _safe_path(root, directory)
        if not directory.is_dir():
            continue
        snapshot = _safe_path(root, directory / CLAIM_SNAPSHOT)
        grant_path = _safe_path(root, directory / AUTHORIZATION_FILE)
        if snapshot.exists():
            prior = json.loads(snapshot.read_text(encoding="utf-8"))
            if not isinstance(prior, dict) or set(prior) != expected_keys:
                raise ValueError("delegation preserved claim is malformed")
            if prior["scope_sha256"] != scope_hash:
                continue
            ordinal = prior["grant_ordinal"]
            if (
                not isinstance(ordinal, int)
                or isinstance(ordinal, bool)
                or not 1 <= ordinal <= len(claims)
            ):
                raise ValueError("delegation reserved ordinal was deleted or reset")
            if (
                claims[ordinal - 1].read_bytes() != snapshot.read_bytes()
                or prior["run_id"] != directory.name
            ):
                raise ValueError("delegation preserved ordinal was reused or changed")
        if grant_path.exists():
            grant = load_model(grant_path, DelegatedOptimizationAuthorizationV01)
            if grant.scope.path != job_relative(root, scope_path):
                continue
            if grant.scope.sha256 != scope_hash or grant.grant_ordinal > len(claims):
                raise ValueError("delegation issued ordinal was deleted or reset")
            claim = json.loads(claims[grant.grant_ordinal - 1].read_text(encoding="utf-8"))
            if (
                claim["run_id"] != directory.name
                or claim["authorization_sha256"] != sha256_file(grant_path)
                or not snapshot.is_file()
            ):
                raise ValueError("delegation issued grant lost its exact nonrefundable claim")
    return claims


def authorize_delegated_asset_optimization(
    job_id: str,
    *,
    run_id: str,
    plan_sha256: str,
    scope_path: str,
    scope_sha256: str,
    decision_note: str,
    enable_delegated_authority: bool = False,
) -> DelegatedOptimizationAuthorizationV01:
    """Issue one immutable delegated grant for a presently reviewed exact candidate."""

    _require_opt_in(enable_delegated_authority)
    root = job_dir(job_id)
    validate_filesystem_id(run_id, "run_id")
    run_root = _safe_path(root, root / "optimization" / "runs" / run_id)
    with _host_lock(root, job_id, f"delegated-{run_id}"):
        _require_exclusive(run_root)
        if any(
            (run_root / name).exists()
            for name in (
                AUTHORIZATION_FILE,
                CONSUMPTION_FILE,
                SCOPE_SNAPSHOT,
                TEXT_SNAPSHOT,
                CONFIRMATION_SNAPSHOT,
                CLAIM_SNAPSHOT,
                TASK_BINDING_SNAPSHOT,
                PROFILE_SNAPSHOT,
                QUALITY_SNAPSHOT,
            )
        ):
            raise FileExistsError("delegated authorization evidence already exists")
        plan, _review = _current_review(root, run_root, job_id, plan_sha256)
        if load_model(run_root / "optimization_plan.json", OptimizationPlan) != plan:
            raise ValueError("delegated grant requires the unchanged draft execution plan")
        scope_file = _safe_path(root, Path(scope_path))
        scope, text_path, reference = _validate_scope(root, scope_file, scope_sha256, job_id)
        claim_root = _safe_path(root, scope_file.parent / "authorization_claims")
        claim_root.mkdir(exist_ok=True)
        claims = _validate_claim_ledger(root, scope_file, scope)
        if len(claims) >= scope.maximum_authorizations_per_job:
            raise ValueError("delegated task authorization reserve is exhausted")
        ordinal = len(claims) + 1
        grant = DelegatedOptimizationAuthorizationV01(
            authorization_id=f"delegated.{run_id}",
            grant_ordinal=ordinal,
            job_id=job_id,
            run_id=run_id,
            scope=_artifact(root, scope_file, f"scope.{scope.delegation_id}"),
            delegation_text_sha256=scope.delegation_text.sha256,
            reference_sha256=reference,
            source=plan.source,
            candidate_sha256=plan.source.scene_spec.sha256,
            plan_sha256=plan_sha256,
            review_sha256=sha256_file(run_root / "optimization_review.json"),
            profile_sha256=plan.profile_artifact.sha256,
            preflight_sha256=plan.preflight_report.sha256,
            decision_note=decision_note.strip(),
            authorized_at=utc_now(),
        )
        grant_bytes = (grant.model_dump_json(indent=2) + "\n").encode("utf-8")
        claim = _safe_path(root, claim_root / f"{ordinal:03}.json")
        _write_once(
            claim,
            json.dumps(
                {
                    "run_id": run_id,
                    "scope_sha256": scope_sha256,
                    "grant_ordinal": ordinal,
                    "authorization_path": job_relative(root, run_root / AUTHORIZATION_FILE),
                    "authorization_sha256": hashlib.sha256(grant_bytes).hexdigest(),
                },
                sort_keys=True,
            ).encode("utf-8"),
        )
        _write_once(run_root / CLAIM_SNAPSHOT, claim.read_bytes())
        _write_once(
            run_root / PROFILE_SNAPSHOT, _read_exact(root, plan.profile_artifact).read_bytes()
        )
        if plan.source_quality is not None:
            _write_once(
                run_root / QUALITY_SNAPSHOT,
                _read_exact(root, plan.source_quality.report_artifact).read_bytes(),
            )
        _write_once(
            run_root / TASK_BINDING_SNAPSHOT,
            _task_binding_path(
                root, scope.delegation_text.sha256, scope.extension_confirmation_text.sha256
            ).read_bytes(),
        )
        _write_once(run_root / SCOPE_SNAPSHOT, scope_file.read_bytes())
        _write_once(run_root / TEXT_SNAPSHOT, text_path.read_bytes())
        _write_once(
            run_root / CONFIRMATION_SNAPSHOT,
            _read_exact(root, scope.extension_confirmation_text).read_bytes(),
        )
        _write_contract_once(run_root / AUTHORIZATION_FILE, grant)
    return grant


def validate_delegated_optimization_authorization(
    root: Path,
    run_root: Path,
    plan: OptimizationPlan,
    *,
    require_consumed: bool,
    expected_authorization_sha256: str | None = None,
    require_current_eligibility: bool | None = None,
) -> DelegatedOptimizationAuthorizationV01:
    """Fail closed on changed, foreign, mixed or replayed exact delegated evidence."""

    if run_root != root / "optimization" / "runs" / run_root.name:
        raise ValueError("delegated run is outside its exact owning path")
    _safe_path(root, run_root)
    _require_exclusive(run_root)
    grant_path = _safe_path(root, run_root / AUTHORIZATION_FILE)
    if (
        expected_authorization_sha256 is not None
        and sha256_file(grant_path) != expected_authorization_sha256
    ):
        raise ValueError("delegated authorization SHA-256 differs")
    grant = load_model(grant_path, DelegatedOptimizationAuthorizationV01)
    scope_path = _read_exact(root, grant.scope)
    scope, text_path, reference = _validate_scope(
        root,
        scope_path,
        grant.scope.sha256,
        plan.job_id,
        active=(
            not require_consumed
            if require_current_eligibility is None
            else require_current_eligibility
        ),
    )
    claim_root = _safe_path(root, scope_path.parent / "authorization_claims")
    _validate_claim_ledger(root, scope_path, scope)
    claim = json.loads(
        _safe_path(root, claim_root / f"{grant.grant_ordinal:03}.json").read_text(encoding="utf-8")
    )
    if claim != {
        "run_id": run_root.name,
        "scope_sha256": grant.scope.sha256,
        "grant_ordinal": grant.grant_ordinal,
        "authorization_path": job_relative(root, grant_path),
        "authorization_sha256": sha256_file(grant_path),
    }:
        raise ValueError("delegation single-use issuance claim differs")
    for name, canonical in (
        (CLAIM_SNAPSHOT, claim_root / f"{grant.grant_ordinal:03}.json"),
        (
            TASK_BINDING_SNAPSHOT,
            _task_binding_path(
                root, scope.delegation_text.sha256, scope.extension_confirmation_text.sha256
            ),
        ),
        (SCOPE_SNAPSHOT, scope_path),
        (TEXT_SNAPSHOT, text_path),
        (CONFIRMATION_SNAPSHOT, _read_exact(root, scope.extension_confirmation_text)),
    ):
        snapshot = _safe_path(root, run_root / name)
        if snapshot.read_bytes() != canonical.read_bytes():
            raise ValueError("delegated authority immutable snapshot changed")
    if sha256_file(_safe_path(root, run_root / PROFILE_SNAPSHOT)) != grant.profile_sha256:
        raise ValueError("delegated retained profile snapshot changed")
    quality_snapshot = _safe_path(root, run_root / QUALITY_SNAPSHOT)
    if plan.source_quality is not None:
        if sha256_file(quality_snapshot) != plan.source_quality.report_artifact.sha256:
            raise ValueError("delegated retained source-quality snapshot changed")
    elif quality_snapshot.exists():
        raise ValueError("delegated run has unexpected source-quality snapshot")
    active = (
        not require_consumed if require_current_eligibility is None else require_current_eligibility
    )
    reviewed, _review = _current_review(
        root, run_root, plan.job_id, grant.plan_sha256, active=active
    )
    if (
        not scope.created_at <= grant.authorized_at < scope.expires_at
        or grant.job_id != plan.job_id
        or grant.run_id != run_root.name
        or grant.profile_id != plan.profile_id
        or grant.source != plan.source
        or grant.reference_sha256 != reference
        or grant.delegation_text_sha256 != scope.delegation_text.sha256
        or grant.review_sha256 != sha256_file(run_root / "optimization_review.json")
        or grant.profile_sha256 != plan.profile_artifact.sha256
        or grant.preflight_sha256 != plan.preflight_report.sha256
        or reviewed.source != plan.source
        or reviewed.directives != plan.directives
        or reviewed.plan_id != plan.plan_id
        or reviewed.source_quality != plan.source_quality
    ):
        raise ValueError("delegated authorization no longer matches the exact run")
    receipt_path = _safe_path(root, run_root / CONSUMPTION_FILE)
    if require_consumed:
        receipt = load_model(receipt_path, DelegatedOptimizationConsumptionV01)
        if (
            receipt.job_id != grant.job_id
            or receipt.run_id != grant.run_id
            or receipt.authorization != _artifact(root, grant_path, grant.authorization_id)
            or receipt.source_fingerprint != grant.source.source_fingerprint
            or receipt.plan_sha256 != grant.plan_sha256
            or not grant.authorized_at <= receipt.consumed_at < scope.expires_at
            or plan.approved_at != grant.authorized_at
        ):
            raise ValueError("delegated consumption receipt differs from exact authority")
    elif receipt_path.exists():
        raise ValueError("delegated authorization has already been consumed")
    elif plan != reviewed:
        raise ValueError("delegated execution requires the unchanged draft plan")
    return grant


def consume_delegated_optimization_authorization(
    root: Path,
    run_root: Path,
    plan: OptimizationPlan,
    *,
    authorization_path: str | Path,
    authorization_sha256: str,
    approved_plan_sha256: str,
    enable_delegated_authority: bool = False,
    workflow_lock_owner: str | None = None,
    held_job_lock_owner: str | None = None,
) -> DelegatedOptimizationAuthorizationV01:
    """Consume only explicitly selected exact authority under the host job lock."""

    _require_opt_in(enable_delegated_authority)
    if _safe_path(root, Path(authorization_path)) != run_root / AUTHORIZATION_FILE:
        raise ValueError("delegated authority must select this exact run's grant")
    binding_path = _safe_path(root, run_root / "optimization_delegated_workflow_binding.json")
    if binding_path.exists():
        from .delegated_models import DelegatedOptimizationWorkflowBindingV01

        binding = load_model(binding_path, DelegatedOptimizationWorkflowBindingV01)
        if workflow_lock_owner != binding.workflow_id:
            raise ValueError("workflow-bound authority requires its exact host workflow lock")
    elif workflow_lock_owner is not None:
        raise ValueError("workflow lock supplied without an explicit delegated binding")
    if (
        held_job_lock_owner is not None
        and workflow_lock_owner is not None
        and held_job_lock_owner != workflow_lock_owner
    ):
        raise ValueError("delegated optimization has conflicting host lock owners")
    with _host_lock(
        root,
        plan.job_id,
        f"delegated-{run_root.name}",
        held_workflow_lock=held_job_lock_owner or workflow_lock_owner,
    ):
        current = load_model(run_root / "optimization_plan.json", OptimizationPlan)
        if current != plan:
            raise ValueError("optimization plan changed before delegated consumption")
        grant = validate_delegated_optimization_authorization(
            root,
            run_root,
            plan,
            require_consumed=False,
            expected_authorization_sha256=authorization_sha256,
        )
        if approved_plan_sha256 != grant.plan_sha256:
            raise ValueError("delegated optimization requires the exact reviewed plan SHA-256")
        receipt = DelegatedOptimizationConsumptionV01(
            job_id=plan.job_id,
            run_id=run_root.name,
            authorization=_artifact(root, run_root / AUTHORIZATION_FILE, grant.authorization_id),
            source_fingerprint=grant.source.source_fingerprint,
            plan_sha256=grant.plan_sha256,
            consumed_at=utc_now(),
        )
        _write_contract_once(run_root / CONSUMPTION_FILE, receipt)
    return grant


def validate_delegated_contract_file(root: Path, path: Path) -> None:
    """Read-only audit of exact new contracts, including cross-file authority validation."""

    model_by_name = {
        AUTHORIZATION_FILE: DelegatedOptimizationAuthorizationV01,
        CONSUMPTION_FILE: DelegatedOptimizationConsumptionV01,
        SCOPE_SNAPSHOT: DelegatedOptimizationScopeV01,
    }
    model = model_by_name.get(path.name)
    if model is not None:
        load_model(path, model)
    if path.name == "scope.json" and path.parent.parent == root / "optimization" / "delegations":
        _validate_scope(root, path, sha256_file(path), root.name, active=False)
    if path.name == AUTHORIZATION_FILE and path.parent.parent == root / "optimization" / "runs":
        plan = load_model(path.parent / "optimization_plan.json", OptimizationPlan)
        validate_delegated_optimization_authorization(
            root,
            path.parent,
            plan,
            require_consumed=(path.parent / CONSUMPTION_FILE).exists(),
            require_current_eligibility=False,
        )
    if path.name in {
        "delegated_optimization_binding.json",
        "optimization_delegated_workflow_binding.json",
    }:
        from .delegated_models import DelegatedOptimizationWorkflowBindingV01
        from .delegated_workflow import load_delegated_workflow_binding

        binding = load_model(path, DelegatedOptimizationWorkflowBindingV01)
        load_delegated_workflow_binding(root, root / "workflows" / binding.workflow_id)
