"""Read-only audit of explicitly listed historical anchors; never migrate or reclassify evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from codex_blender_modeler.blender_artifacts import publish_bytes_create_once
from codex_blender_modeler.production.validation import ensure_contained_production_path
from codex_blender_modeler.reference_fidelity.models import FidelityArtifact
from codex_blender_modeler.reference_fidelity.service import read_artifact


def audit_history(root: Path, manifest_path: Path) -> dict[str, object]:
    """Rehash only exact declared anchors and report missing/changed bytes without any repair."""

    manifest_path = ensure_contained_production_path(root, manifest_path, must_exist=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "0.1.0":
        raise ValueError("unknown historical anchor manifest version")
    if not manifest.get("anchors"):
        raise ValueError("historical audit needs explicitly listed anchors")
    seen = set()
    findings = []
    for entry in manifest["anchors"]:
        artifact = FidelityArtifact.model_validate(
            {"path": entry["path"], "sha256": entry["sha256"]}
        )
        key = artifact.path.casefold()
        if key in seen:
            raise ValueError("historical anchor paths must be unique")
        seen.add(key)
        error = None
        try:
            read_artifact(root, artifact)
        except (OSError, ValueError) as exc:
            error = str(exc)
        findings.append(
            {
                **artifact.model_dump(mode="json"),
                "status": "matched" if error is None else "failed",
                "error": error,
            }
        )
    return {
        "schema_version": "0.1.0",
        "kind": "reference_fidelity_historical_anchor_audit",
        "scope": "listed_anchors_only_not_a_full_workspace_snapshot",
        "historical_source_commit": manifest.get("historical_source_commit"),
        "passed": all(item["status"] == "matched" for item in findings),
        "checked": len(findings),
        "anchors": findings,
        "history_modified": False,
        "human_quality_disposition_changed": False,
        "activation_authority": False,
    }


def main() -> None:
    """Print an anchor audit and optionally create a separate new local diagnostic report."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    result = audit_history(root, root / args.manifest)
    if args.output is not None:
        output = ensure_contained_production_path(root, root / args.output, must_exist=False)
        relative = output.relative_to(root).as_posix()
        if not relative.startswith((".t/", ".b/", "reports/reference_fidelity/audits/")):
            raise ValueError("audit output must be a separate repository-local diagnostic")
        output.parent.mkdir(parents=True, exist_ok=True)
        publish_bytes_create_once(output, (json.dumps(result, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({key: value for key, value in result.items() if key != "anchors"}, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
