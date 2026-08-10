"""Human-readable projections of authoritative reference-evidence JSON."""

from __future__ import annotations

from .models import CameraHypothesisSet, ReferenceEvidence


def render_reference_evidence_markdown(
    evidence: ReferenceEvidence,
    cameras: CameraHypothesisSet,
) -> str:
    """Render a compact review summary without turning Markdown into authority."""

    lines = [
        f"# Reference Evidence — {evidence.job_id}",
        "",
        f"- Run: `{evidence.run_id}`",
        f"- Status: `{evidence.status}`",
        f"- Source fingerprint: `{evidence.source_fingerprint}`",
        f"- Mask candidates: `{len(evidence.mask_candidates)}`",
        f"- Selected mask: `{evidence.selected_candidate_id}`",
        f"- Camera ambiguity: `{cameras.projection_ambiguity}`",
        f"- Staging hypothesis: `{cameras.staging_hypothesis_id}`",
        "- Canonical camera changed: `false`",
        "",
        "## Mask candidates",
        "",
    ]
    for candidate in evidence.mask_candidates:
        lines.append(
            "- "
            f"`{candidate.candidate_id}` ({candidate.provenance.provider}/"
            f"{candidate.provenance.method}): confidence="
            f"{candidate.metrics.confidence:.6f}, area="
            f"{candidate.metrics.area_ratio:.6f}, edge="
            f"{candidate.metrics.edge_agreement:.6f}"
        )
    lines.extend(["", "## Camera hypotheses", ""])
    for hypothesis in cameras.hypotheses:
        lines.append(
            f"- `{hypothesis.hypothesis_id}`: {hypothesis.projection}, "
            f"confidence={hypothesis.confidence:.6f}"
        )
    lines.extend(
        [
            "",
            "This summary is derived from JSON evidence and must not be parsed as authority.",
            "",
        ]
    )
    return "\n".join(lines)
