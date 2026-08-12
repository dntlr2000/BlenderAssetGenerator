"""Strict additive contracts for normalized Codex-image material authoring.

These 0.1.0 companion records preserve the complete MaterialAuthoring 0.2.1
request unchanged.  They bind that selected-source contract to one exact native
normalization plan and receipt, then describe only the derivative staging run.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..blender_artifacts import stable_json_digest
from ..codex_imagegen.material_loop_models import ImageMaterialLoopEvidence
from ..codex_imagegen.models import CodexImageArtifact
from .codex_image_models import (
    CodexImageChannelDerivationV021,
    CodexImageMaterialAuthoringRequestV021,
    CodexImageMaterialQualityV021,
    CodexImageMaterialSourceV021,
    CodexImageMaterialStrategy,
    ExactTextCompositionReceiptV021,
)
from .models import ExactArtifact, MaterialFamily, PortableId, RelativePath, Sha256

NORMALIZED_MATERIAL_SCHEMA_VERSION = "0.1.0"

__all__ = [
    "CodexImageNormalizedAuthoredMaterialManifestV010",
    "CodexImageNormalizedMaterialAuthoringReceiptV010",
    "CodexImageNormalizedMaterialAuthoringRequestV010",
    "NORMALIZED_MATERIAL_SCHEMA_VERSION",
]


def _artifact_payload(artifact: CodexImageArtifact | ExactArtifact) -> dict[str, object]:
    """Return one artifact's exact portable fields for deterministic hashing."""

    return artifact.model_dump(mode="json")


def _request_input_sha256(
    *,
    base_request: CodexImageMaterialAuthoringRequestV021,
    base_request_artifact: CodexImageArtifact,
    normalization_plan: CodexImageArtifact,
    normalization_receipt: CodexImageArtifact,
    effective_source: CodexImageMaterialSourceV021,
    run_id: str,
    output_root: str,
) -> str:
    """Hash every immutable decision that selects one normalized derivation run."""

    return stable_json_digest(
        {
            "base_request": base_request.model_dump(mode="json"),
            "base_request_artifact": _artifact_payload(base_request_artifact),
            "normalization_plan": _artifact_payload(normalization_plan),
            "normalization_receipt": _artifact_payload(normalization_receipt),
            "effective_source": effective_source.model_dump(mode="json"),
            "run_id": run_id,
            "output_root": output_root,
        }
    )


def _manifest_input_sha256(
    *,
    request: CodexImageArtifact,
    base_request_artifact: CodexImageArtifact,
    normalization_plan: CodexImageArtifact,
    normalization_receipt: CodexImageArtifact,
    selected_source: CodexImageMaterialSourceV021,
    effective_source: CodexImageMaterialSourceV021,
    channels: list[CodexImageChannelDerivationV021],
) -> str:
    """Hash the exact request chain and all derived channel declarations."""

    return stable_json_digest(
        {
            "request": _artifact_payload(request),
            "base_request_artifact": _artifact_payload(base_request_artifact),
            "normalization_plan": _artifact_payload(normalization_plan),
            "normalization_receipt": _artifact_payload(normalization_receipt),
            "selected_source": selected_source.model_dump(mode="json"),
            "effective_source": effective_source.model_dump(mode="json"),
            "channels": [item.model_dump(mode="json") for item in channels],
        }
    )


def _receipt_input_sha256(
    *,
    request: CodexImageArtifact,
    manifest: CodexImageArtifact,
    outputs: list[ExactArtifact],
) -> str:
    """Hash one published request, manifest, and ordered output inventory."""

    return stable_json_digest(
        {
            "request": _artifact_payload(request),
            "manifest": _artifact_payload(manifest),
            "outputs": [
                _artifact_payload(item) for item in sorted(outputs, key=lambda value: value.path)
            ],
        }
    )


def _require_exact_provenance(
    actual: list[CodexImageArtifact],
    expected: list[CodexImageArtifact],
    label: str,
) -> None:
    """Require provenance to equal the declared artifact closure without omissions."""

    normalize = lambda values: sorted(  # noqa: E731 - compact deterministic comparison.
        (item.model_dump(mode="json") for item in values),
        key=lambda item: (str(item["path"]), str(item["artifact_id"])),
    )
    if normalize(actual) != normalize(expected):
        raise ValueError(f"{label} provenance differs from its exact artifact closure")


def _as_codex_artifact(artifact: ExactArtifact) -> CodexImageArtifact:
    """Convert structurally identical material artifact evidence without changing fields."""

    return CodexImageArtifact.model_validate(artifact.model_dump(mode="python"))


class CodexImageNormalizedMaterialAuthoringRequestV010(ImageMaterialLoopEvidence):
    """Bind an unchanged 0.2.1 request to one exact normalized effective source."""

    base_request: CodexImageMaterialAuthoringRequestV021
    base_request_artifact: CodexImageArtifact
    normalization_plan: CodexImageArtifact
    normalization_receipt: CodexImageArtifact
    effective_source: CodexImageMaterialSourceV021
    run_id: PortableId
    output_root: RelativePath
    canonical_write_authority: Literal[False] = False
    destination_write_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_normalized_request(self) -> CodexImageNormalizedMaterialAuthoringRequestV010:
        """Reject changed source semantics, loose provenance, and stale input hashes."""

        expected_kinds = {
            "base_request_artifact": "codex-image-material-authoring-request",
            "normalization_plan": "imagegen-native-normalization-plan",
            "normalization_receipt": "imagegen-native-normalization-receipt",
        }
        for field, kind in expected_kinds.items():
            if getattr(self, field).kind != kind:
                raise ValueError(f"{field} must have kind {kind}")
        if self.effective_source.artifact.kind != "codex-imagegen-normalized-material-source":
            raise ValueError("effective source must be an exact normalized material source")
        if (self.job_id, self.workflow_id) != (
            self.base_request.job_id,
            self.base_request.workflow_id,
        ):
            raise ValueError("normalized request identity differs from its base request")
        if self.run_id == self.base_request.run_id:
            raise ValueError("normalized run_id must be distinct from the base request run")
        selected = self.base_request.source
        preserved_fields = (
            "direct_role",
            "color_space",
            "license_id",
            "rights_status",
        )
        if any(
            getattr(self.effective_source, field) != getattr(selected, field)
            for field in preserved_fields
        ):
            raise ValueError("normalization cannot change selected-source material semantics")
        if self.source_fingerprint != selected.artifact.sha256:
            raise ValueError("normalized request fingerprint must equal selected source bytes")
        expected_root = f"material_authoring/codex_imagegen/normalized_runs/{self.run_id}"
        if self.output_root != expected_root:
            raise ValueError(f"output_root must equal {expected_root}")
        expected_input = _request_input_sha256(
            base_request=self.base_request,
            base_request_artifact=self.base_request_artifact,
            normalization_plan=self.normalization_plan,
            normalization_receipt=self.normalization_receipt,
            effective_source=self.effective_source,
            run_id=self.run_id,
            output_root=self.output_root,
        )
        if self.input_sha256 != expected_input:
            raise ValueError("normalized material request input hash is inconsistent")
        _require_exact_provenance(
            self.provenance,
            [
                self.base_request_artifact,
                _as_codex_artifact(selected.artifact),
                self.normalization_plan,
                self.normalization_receipt,
                _as_codex_artifact(self.effective_source.artifact),
            ],
            "normalized material request",
        )
        return self


class CodexImageNormalizedAuthoredMaterialManifestV010(ImageMaterialLoopEvidence):
    """Describe a normalized-source material candidate without claiming 0.2.1 output."""

    manifest_id: PortableId
    run_id: PortableId
    material_id: str = Field(min_length=1, max_length=128)
    strategy: CodexImageMaterialStrategy
    material_family: MaterialFamily
    request: CodexImageArtifact
    base_request_artifact: CodexImageArtifact
    normalization_plan: CodexImageArtifact
    normalization_receipt: CodexImageArtifact
    selected_source: CodexImageMaterialSourceV021
    effective_source: CodexImageMaterialSourceV021
    derivation_policy_sha256: Sha256
    channels: list[CodexImageChannelDerivationV021] = Field(min_length=1)
    exact_text: ExactTextCompositionReceiptV021 | None = None
    quality: CodexImageMaterialQualityV021
    status: Literal["candidate_ready", "review_required"]
    limitations: list[str] = Field(default_factory=list)
    staging_only: Literal[True] = True
    canonical_v05_unchanged: Literal[True] = True
    canonical_write_performed: Literal[False] = False
    destination_write_performed: Literal[False] = False
    actual_codex_imagegen_execution_verified: Literal[False] = False
    blender_compilation_status: Literal["not_run"] = "not_run"

    @model_validator(mode="after")
    def validate_normalized_manifest(self) -> CodexImageNormalizedAuthoredMaterialManifestV010:
        """Require exact normalized provenance, unique channels, and honest status."""

        if self.request.kind != "codex-image-normalized-material-authoring-request":
            raise ValueError("normalized manifest request has the wrong artifact kind")
        names = [channel.channel for channel in self.channels]
        if len(names) != len(set(names)):
            raise ValueError("normalized material channels must be unique")
        if self.status == "candidate_ready" and self.quality.outcome != "passed":
            raise ValueError("candidate_ready requires passed deterministic material checks")
        if (self.strategy == "codex_generated_decal_v1") != (self.exact_text is not None):
            raise ValueError("normalized decal manifests require exact-text composition state")
        if self.source_fingerprint != self.selected_source.artifact.sha256:
            raise ValueError("normalized manifest fingerprint must equal selected source bytes")
        expected_input = _manifest_input_sha256(
            request=self.request,
            base_request_artifact=self.base_request_artifact,
            normalization_plan=self.normalization_plan,
            normalization_receipt=self.normalization_receipt,
            selected_source=self.selected_source,
            effective_source=self.effective_source,
            channels=self.channels,
        )
        if self.input_sha256 != expected_input:
            raise ValueError("normalized material manifest input hash is inconsistent")
        _require_exact_provenance(
            self.provenance,
            [
                self.request,
                self.base_request_artifact,
                self.normalization_plan,
                self.normalization_receipt,
                _as_codex_artifact(self.selected_source.artifact),
                _as_codex_artifact(self.effective_source.artifact),
                *[_as_codex_artifact(channel.output) for channel in self.channels],
            ],
            "normalized material manifest",
        )
        return self


class CodexImageNormalizedMaterialAuthoringReceiptV010(ImageMaterialLoopEvidence):
    """Bind one normalized staging publication to its new request and manifest kinds."""

    receipt_id: PortableId
    run_id: PortableId
    request: CodexImageArtifact
    manifest: CodexImageArtifact
    outputs: list[ExactArtifact] = Field(min_length=1)
    output_bundle_sha256: Sha256
    status: Literal["published_to_staging"] = "published_to_staging"
    staging_only: Literal[True] = True
    canonical_write_performed: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_normalized_receipt(self) -> CodexImageNormalizedMaterialAuthoringReceiptV010:
        """Reject legacy kinds, duplicate outputs, stale hashes, and loose provenance."""

        if self.request.kind != "codex-image-normalized-material-authoring-request":
            raise ValueError("normalized receipt request has the wrong artifact kind")
        if self.manifest.kind != "codex-image-normalized-authored-material-manifest":
            raise ValueError("normalized receipt manifest has the wrong artifact kind")
        paths = [item.path for item in self.outputs]
        if len(paths) != len(set(paths)):
            raise ValueError("normalized material receipt outputs must be unique")
        expected_bundle = stable_json_digest(
            [
                item.model_dump(mode="json")
                for item in sorted(self.outputs, key=lambda value: value.path)
            ]
        )
        if self.output_bundle_sha256 != expected_bundle:
            raise ValueError("normalized material output bundle hash is inconsistent")
        expected_input = _receipt_input_sha256(
            request=self.request,
            manifest=self.manifest,
            outputs=self.outputs,
        )
        if self.input_sha256 != expected_input:
            raise ValueError("normalized material receipt input hash is inconsistent")
        _require_exact_provenance(
            self.provenance,
            [
                self.request,
                self.manifest,
                *[_as_codex_artifact(item) for item in self.outputs],
            ],
            "normalized material receipt",
        )
        return self
