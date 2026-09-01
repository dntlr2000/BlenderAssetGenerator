"""Fail-closed gate for unpublished or source-committed local AQ activation."""

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
    ActivationCampaignOutcomeEligibilityReport,
    ActivationCampaignOutcomeEvidence,
    ActivationCampaignOutcomeIndex,
    ActivationCampaignOutcomeRegistry,
    ActivationHumanQualityDisposition,
    ActivationReadinessReport,
    ActivationSourceManifest,
    HumanActivationAcceptance,
    HumanLocalActivationAcceptance,
    LocalActivationReadinessReport,
    LocalProfileActivationPublication,
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
    "activation_human_quality_disposition.schema.json": (
        ActivationHumanQualityDisposition
    ),
    "activation_campaign_outcome_evidence.schema.json": (
        ActivationCampaignOutcomeEvidence
    ),
    "activation_campaign_outcome_eligibility_report.schema.json": (
        ActivationCampaignOutcomeEligibilityReport
    ),
    "activation_campaign_outcome_registry.schema.json": (
        ActivationCampaignOutcomeRegistry
    ),
    "activation_campaign_outcome_index.schema.json": ActivationCampaignOutcomeIndex,
    "human_local_activation_acceptance.schema.json": HumanLocalActivationAcceptance,
    "local_activation_readiness_report.schema.json": LocalActivationReadinessReport,
    "local_profile_activation_publication.schema.json": (
        LocalProfileActivationPublication
    ),
    "human_activation_acceptance.schema.json": HumanActivationAcceptance,
}


def activation_readiness_contract_findings() -> list[str]:
    """Return deterministic schema, profile, and authority-surface drift findings."""

    findings: list[str] = []
    capability = activation_contract_capability()
    profile = autonomy_v2_profile_status()
    if capability.get("status") != "disabled_experimental":
        findings.append("activation readiness contract is not disabled_experimental")
    if capability.get("profile_activation_writer_exposed") is not True:
        findings.append("activation readiness service lacks the exact publication writer")
    if capability.get("profile_activation_requires_source_commit") is not True:
        findings.append("local profile publication does not require a source commit")
    if capability.get("campaign_creation_supported_by_this_service") is not False:
        findings.append("activation readiness service exposes campaign creation")
    publication_state = profile.get("publication_state")
    if publication_state == "absent":
        if profile.get("status") != "disabled_experimental":
            findings.append("unpublished AQ v2 profile is not disabled_experimental")
        if profile.get("verified_active") is not False:
            findings.append("unpublished AQ v2 profile claims verified activation")
    elif publication_state == "verified_active":
        if profile.get("status") != "verified_active":
            findings.append("committed AQ v2 publication is not projected active")
        if profile.get("verified_active") is not True:
            findings.append("committed AQ v2 publication lacks verified activation")
        if not profile.get("activation_evidence"):
            findings.append("committed AQ v2 publication lacks activation evidence")
    else:
        findings.append(f"local AQ v2 publication is not terminal: {publication_state}")
    if profile.get("activation_scope") != "local_desktop_in_session":
        findings.append("autonomous_static_prop_v2 local activation scope drifted")
    if capability.get("campaign_outcome_index_supported") is not True:
        findings.append("activation readiness lacks a separate campaign outcome index")
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
    profile = autonomy_v2_profile_status()
    payload = {
        "gate": "activation_readiness_contract",
        "contract_version": "0.1.0",
        "status": "passed" if not findings else "failed",
        "profile_status": profile["status"],
        "profile_activation_performed": profile["status"] == "verified_active",
        "campaign_created": False,
        "findings": findings,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
