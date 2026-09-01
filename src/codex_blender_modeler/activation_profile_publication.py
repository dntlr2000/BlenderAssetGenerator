"""Fail-closed source-controlled publication for the local AQ v2 profile."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .blender_artifacts import sha256_file, stable_json_digest
from .stabilization.models import PortableId, RelativePath, Sha256, V09StrictModel

LOCAL_PROFILE_PUBLICATION_RELATIVE_PATH = (
    ".codex/activation/autonomous_static_prop_v2.local.json"
)

EXCLUDED_LOCAL_CAPABILITIES = (
    "animation",
    "architecture",
    "client_mediated_controller",
    "codex_imagegen",
    "dependency_rich_bake_material",
    "interior",
    "rig",
    "signage_or_decal",
)

FUTURE_LOCAL_LIMITATIONS = (
    "desktop_in_session is workflow-contract-only and is not a sandbox attestation",
    "destination runtime import and material parity are not verified",
    "supporting-client closed-loop and tool-policy attestation are not verified",
)

GitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


class ActivationPublicationArtifact(V09StrictModel):
    """Bind one immutable repository artifact used to activate the local profile."""

    artifact_id: PortableId
    kind: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(gt=0)


class LocalProfileActivationPublication(V09StrictModel):
    """Bind one exact accepted campaign to the narrow local verified profile."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    publication_id: PortableId
    publication_sha256: Sha256
    source_control_path: Literal[
        ".codex/activation/autonomous_static_prop_v2.local.json"
    ] = LOCAL_PROFILE_PUBLICATION_RELATIVE_PATH
    profile_id: Literal["autonomous_static_prop_v2"] = "autonomous_static_prop_v2"
    profile_version: Literal["0.2.0"] = "0.2.0"
    profile_status: Literal["verified_active"] = "verified_active"
    activation_scope: Literal["local_desktop_in_session"] = (
        "local_desktop_in_session"
    )
    reference_content_scope: Literal["primary_object_only"] = "primary_object_only"
    supported_asset_kinds: list[
        Literal["static_hard_surface", "static_prop"]
    ] = Field(min_length=2, max_length=2)
    supported_delivery_profiles: list[
        Literal["portable_gltf", "review_only"]
    ] = Field(min_length=2, max_length=2)
    source_git_commit_sha: GitSha
    source_git_tree_sha: GitSha
    activation_baseline: ActivationPublicationArtifact
    campaign_outcome_index: ActivationPublicationArtifact
    local_readiness_report: ActivationPublicationArtifact
    human_activation_acceptance: ActivationPublicationArtifact
    activation_evidence: list[ActivationPublicationArtifact] = Field(
        min_length=4,
        max_length=4,
    )
    distinct_primary_reference_sha256s: list[Sha256] = Field(
        min_length=5,
        max_length=5,
    )
    production_package_count: int = Field(ge=1)
    excluded_capabilities: list[str] = Field(min_length=1)
    future_limitations: list[str] = Field(min_length=1)
    published_at: datetime
    single_use_acceptance_consumed: Literal[True] = True
    destination_write_authorized: Literal[False] = False
    is_policy_authorization: Literal[False] = False

    @model_validator(mode="after")
    def validate_publication(self) -> LocalProfileActivationPublication:
        """Require exact support scope, evidence order, and deterministic identity."""

        if self.supported_asset_kinds != ["static_hard_surface", "static_prop"]:
            raise ValueError("local profile asset kinds differ from the verified scope")
        if self.supported_delivery_profiles != ["portable_gltf", "review_only"]:
            raise ValueError("local profile delivery profiles differ from the verified scope")
        expected_evidence = [
            self.activation_baseline,
            self.campaign_outcome_index,
            self.local_readiness_report,
            self.human_activation_acceptance,
        ]
        if self.activation_evidence != expected_evidence:
            raise ValueError("local profile activation evidence order is not canonical")
        hashes = self.distinct_primary_reference_sha256s
        if hashes != sorted(hashes) or len(hashes) != len(set(hashes)):
            raise ValueError("local profile reference hashes must be unique and sorted")
        if self.excluded_capabilities != list(EXCLUDED_LOCAL_CAPABILITIES):
            raise ValueError("local profile excluded capabilities differ from policy")
        if self.future_limitations != list(FUTURE_LOCAL_LIMITATIONS):
            raise ValueError("local profile future limitations differ from policy")
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise ValueError("local profile publication timestamp must be timezone-aware")
        projection = self.model_dump(
            mode="json",
            exclude={"publication_id", "publication_sha256"},
        )
        digest = stable_json_digest(projection)
        if self.publication_sha256 != digest:
            raise ValueError("publication_sha256 differs from the canonical payload")
        if self.publication_id != f"local-profile-publication-{digest[:24]}":
            raise ValueError("publication_id differs from the canonical payload")
        return self


def default_repository_root() -> Path:
    """Resolve the source repository that owns the local-only publication file."""

    return Path(__file__).resolve().parents[2]


def local_profile_publication_path(root: Path | None = None) -> Path:
    """Return the only source-controlled path allowed for local profile publication."""

    repository = (root or default_repository_root()).expanduser().resolve()
    return repository / LOCAL_PROFILE_PUBLICATION_RELATIVE_PATH


def _validate_publication_artifact(
    root: Path,
    artifact: ActivationPublicationArtifact,
) -> None:
    """Reject escaped, missing, resized, or rehashed publication evidence."""

    repository = root.expanduser().resolve(strict=True)
    candidate = (repository / artifact.path).resolve(strict=True)
    try:
        candidate.relative_to(repository)
    except ValueError as exc:
        raise ValueError(f"publication artifact escapes repository: {artifact.path}") from exc
    if not candidate.is_file():
        raise ValueError(f"publication artifact is not a file: {artifact.path}")
    if candidate.stat().st_size != artifact.byte_size:
        raise ValueError(f"publication artifact size changed: {artifact.path}")
    if sha256_file(candidate) != artifact.sha256:
        raise ValueError(f"publication artifact hash changed: {artifact.path}")


def local_profile_publication_is_head_tracked(root: Path) -> bool:
    """Return true only when the publication is unchanged and tracked by current HEAD."""

    repository = root.expanduser().resolve(strict=True)
    relative = LOCAL_PROFILE_PUBLICATION_RELATIVE_PATH
    tracked = subprocess.run(
        ["git", "-C", str(repository), "ls-files", "--error-unmatch", "--", relative],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if tracked.returncode != 0:
        return False
    unchanged = subprocess.run(
        ["git", "-C", str(repository), "diff", "--quiet", "HEAD", "--", relative],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return unchanged.returncode == 0


def load_local_profile_activation_publication(
    root: Path | None = None,
    *,
    require_head_tracked: bool = True,
) -> LocalProfileActivationPublication:
    """Strict-load one publication and optionally require its current HEAD commit."""

    repository = (root or default_repository_root()).expanduser().resolve(strict=True)
    path = local_profile_publication_path(repository)
    publication = LocalProfileActivationPublication.model_validate_json(path.read_bytes())
    if path.relative_to(repository).as_posix() != publication.source_control_path:
        raise ValueError("local profile publication path differs from its contract")
    for artifact in publication.activation_evidence:
        _validate_publication_artifact(repository, artifact)
    if require_head_tracked and not local_profile_publication_is_head_tracked(repository):
        raise PermissionError("local profile publication is not committed in current HEAD")
    return publication
