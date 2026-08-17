"""Fail-closed static gate for the disabled-experimental activation contract surface."""

from __future__ import annotations

import json
from pathlib import Path

from codex_blender_modeler.autonomy_v2.profiles import autonomy_v2_profile_status
from codex_blender_modeler.production import (
    ActivationAssetCandidateIndex,
    ActivationAssetCandidateRegistry,
    ActivationAssetEligibilityReport,
    ActivationAssetEvidence,
    ActivationBaseline,
    ActivationReadinessReport,
    ActivationSourceManifest,
    HumanActivationAcceptance,
    activation_contract_capability,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_MODELS = {
    "activation_source_manifest.schema.json": ActivationSourceManifest,
    "activation_baseline.schema.json": ActivationBaseline,
    "activation_readiness_report.schema.json": ActivationReadinessReport,
    "activation_asset_evidence.schema.json": ActivationAssetEvidence,
    "activation_asset_eligibility_report.schema.json": ActivationAssetEligibilityReport,
    "activation_asset_candidate_registry.schema.json": ActivationAssetCandidateRegistry,
    "activation_asset_candidate_index.schema.json": ActivationAssetCandidateIndex,
    "human_activation_acceptance.schema.json": HumanActivationAcceptance,
}


def activation_readiness_contract_findings() -> list[str]:
    """Return deterministic schema, profile, and authority-surface drift findings."""

    findings: list[str] = []
    capability = activation_contract_capability()
    profile = autonomy_v2_profile_status()
    if capability.get("status") != "disabled_experimental":
        findings.append("activation readiness contract is not disabled_experimental")
    if capability.get("profile_activation_writer_exposed") is not False:
        findings.append("activation readiness service exposes a profile activation writer")
    if capability.get("campaign_creation_supported_by_this_service") is not False:
        findings.append("activation readiness service exposes campaign creation")
    if profile.get("status") != "disabled_experimental":
        findings.append("autonomous_static_prop_v2 profile is not disabled_experimental")
    if profile.get("verified_active") is not False:
        findings.append("autonomous_static_prop_v2 incorrectly claims verified activation")
    for filename, model in sorted(SCHEMA_MODELS.items()):
        path = ROOT / "schemas" / filename
        if not path.is_file():
            findings.append(f"missing activation schema: {filename}")
            continue
        checked_in = json.loads(path.read_text(encoding="utf-8"))
        if checked_in != model.model_json_schema():
            findings.append(f"activation schema drift: {filename}")
    return findings


def main() -> None:
    """Print one machine-readable gate result and fail when any finding remains."""

    findings = activation_readiness_contract_findings()
    payload = {
        "gate": "activation_readiness_contract",
        "contract_version": "0.1.0",
        "status": "passed" if not findings else "failed",
        "profile_status": autonomy_v2_profile_status()["status"],
        "profile_activation_performed": False,
        "campaign_created": False,
        "findings": findings,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
