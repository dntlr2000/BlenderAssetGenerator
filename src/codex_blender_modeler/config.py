from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    workspace_root: Path
    blender_bin: str
    codex_bin: str
    blender_timeout: int


@dataclass(frozen=True)
class FeatureFlags:
    """Control optional material, QA, portable-asset, workflow, and V0.9 capabilities."""

    material_core: bool = True
    shader_core: bool = True
    texture_provider: str = "procedural"
    visual_qa: bool = True
    image_model_qa: bool = False
    automatic_revision: bool = False
    portable_asset_core: bool = True
    workflow_orchestration: bool = True
    stabilization_core: bool = True


@dataclass(frozen=True)
class QaSettings:
    """Define conservative visual-QA and revision defaults."""

    revision_mode: Literal["off", "suggest", "approve", "auto"] = "suggest"
    max_revision_iterations: int = 1
    generated_target_weight: float = 0.15


@dataclass(frozen=True)
class OrchestrationSettings:
    """Define conservative V0.8 resume and lock defaults."""

    default_scope: Literal["proxy_only"] = "proxy_only"
    max_host_steps_per_resume: int = 8
    lock_ttl_seconds: int = 900


@dataclass(frozen=True)
class StabilizationSettings:
    """Bound V0.9 workspace audits and the single-worker local workflow queue."""

    audit_scan_limit: int = 100000
    queue_lock_ttl_seconds: int = 300
    queue_lease_seconds: int = 7200


@dataclass(frozen=True)
class FeatureConfig:
    """Bundle feature flags with QA, orchestration, and stabilization policies."""

    features: FeatureFlags
    qa: QaSettings
    orchestration: OrchestrationSettings
    stabilization: StabilizationSettings


def get_settings() -> Settings:
    """Load executable, workspace, and timeout settings from the environment."""

    workspace_value = os.getenv("CBM_WORKSPACE_ROOT", "").strip()
    workspace_root = (
        Path(workspace_value).expanduser().resolve()
        if workspace_value
        else REPO_ROOT / "workspaces"
    )
    blender_bin = os.getenv("BLENDER_BIN", "blender").strip() or "blender"
    codex_bin = os.getenv("CODEX_BIN", "codex").strip() or "codex"
    timeout = int(os.getenv("CBM_BLENDER_TIMEOUT", "900"))
    return Settings(REPO_ROOT, workspace_root, blender_bin, codex_bin, timeout)


def load_feature_config(path: Path | None = None) -> FeatureConfig:
    """Load optional V0.5-V0.9 feature flags and conservative runtime policies."""

    config_path = (path or REPO_ROOT / "cbm.toml").expanduser().resolve()
    raw: dict = {}
    if config_path.is_file():
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)

    feature_values = raw.get("features", {})
    qa_values = raw.get("qa", {})
    orchestration_values = raw.get("orchestration", {})
    stabilization_values = raw.get("stabilization", {})
    if not all(
        isinstance(value, dict)
        for value in (
            feature_values,
            qa_values,
            orchestration_values,
            stabilization_values,
        )
    ):
        raise ValueError(
            "cbm.toml features, qa, orchestration, and stabilization sections "
            "must be TOML tables"
        )

    features = FeatureFlags(
        material_core=bool(feature_values.get("material_core", True)),
        shader_core=bool(feature_values.get("shader_core", True)),
        texture_provider=str(feature_values.get("texture_provider", "procedural")),
        visual_qa=bool(feature_values.get("visual_qa", True)),
        image_model_qa=bool(feature_values.get("image_model_qa", False)),
        automatic_revision=bool(feature_values.get("automatic_revision", False)),
        portable_asset_core=bool(feature_values.get("portable_asset_core", True)),
        workflow_orchestration=bool(
            feature_values.get("workflow_orchestration", True)
        ),
        stabilization_core=bool(feature_values.get("stabilization_core", True)),
    )
    revision_mode = str(qa_values.get("revision_mode", "suggest"))
    if revision_mode not in {"off", "suggest", "approve", "auto"}:
        raise ValueError("qa.revision_mode must be off, suggest, approve, or auto")
    if revision_mode == "auto" and not features.automatic_revision:
        raise ValueError(
            "qa.revision_mode=auto requires features.automatic_revision=true"
        )
    max_iterations = int(qa_values.get("max_revision_iterations", 1))
    if max_iterations < 0 or max_iterations > 10:
        raise ValueError("qa.max_revision_iterations must be within [0, 10]")
    target_weight = float(qa_values.get("generated_target_weight", 0.15))
    if target_weight < 0 or target_weight > 1:
        raise ValueError("qa.generated_target_weight must be within [0, 1]")
    qa = QaSettings(
        revision_mode=revision_mode,  # type: ignore[arg-type]
        max_revision_iterations=max_iterations,
        generated_target_weight=target_weight,
    )
    default_scope = str(orchestration_values.get("default_scope", "proxy_only"))
    if default_scope != "proxy_only":
        raise ValueError("orchestration.default_scope must remain proxy_only in V0.8")
    max_host_steps = int(
        orchestration_values.get("max_host_steps_per_resume", 8)
    )
    if max_host_steps < 1 or max_host_steps > 64:
        raise ValueError(
            "orchestration.max_host_steps_per_resume must be within [1, 64]"
        )
    lock_ttl = int(orchestration_values.get("lock_ttl_seconds", 900))
    if lock_ttl < 30 or lock_ttl > 86400:
        raise ValueError("orchestration.lock_ttl_seconds must be within [30, 86400]")
    orchestration = OrchestrationSettings(
        default_scope="proxy_only",
        max_host_steps_per_resume=max_host_steps,
        lock_ttl_seconds=lock_ttl,
    )
    audit_scan_limit = int(stabilization_values.get("audit_scan_limit", 100000))
    if audit_scan_limit < 100 or audit_scan_limit > 1_000_000:
        raise ValueError("stabilization.audit_scan_limit must be within [100, 1000000]")
    queue_lock_ttl = int(
        stabilization_values.get("queue_lock_ttl_seconds", 300)
    )
    if queue_lock_ttl < 30 or queue_lock_ttl > 86400:
        raise ValueError(
            "stabilization.queue_lock_ttl_seconds must be within [30, 86400]"
        )
    queue_lease = int(stabilization_values.get("queue_lease_seconds", 7200))
    if queue_lease < 60 or queue_lease > 86400:
        raise ValueError("stabilization.queue_lease_seconds must be within [60, 86400]")
    if queue_lease <= queue_lock_ttl:
        raise ValueError(
            "stabilization.queue_lease_seconds must exceed queue_lock_ttl_seconds"
        )
    stabilization = StabilizationSettings(
        audit_scan_limit=audit_scan_limit,
        queue_lock_ttl_seconds=queue_lock_ttl,
        queue_lease_seconds=queue_lease,
    )
    return FeatureConfig(
        features=features,
        qa=qa,
        orchestration=orchestration,
        stabilization=stabilization,
    )


def executable_exists(value: str) -> bool:
    """Return whether an executable path or PATH entry can be resolved."""

    candidate = Path(value).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate.exists()
    return shutil.which(value) is not None
