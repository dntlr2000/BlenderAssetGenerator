"""Pure repository catalog and authorization-surface tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from codex_blender_modeler import repository_catalog as catalog

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_matches_current_source_registries() -> None:
    """Keep pure builder and tool catalogs synchronized with source declarations."""

    assert catalog.validate_repository_catalog(ROOT) == ()


def test_mcp_surfaces_remain_distinct_and_explained() -> None:
    """Separate server registration, project enablement, and phase authority."""

    surfaces = catalog.build_tool_surface_catalog(ROOT)
    assert surfaces.project_enabled_tools < surfaces.server_tools
    assert surfaces.server_tools - surfaces.project_enabled_tools == {
        "recover_candidate_review_promotion_failure"
    }
    assert set(surfaces.project_exclusion_reasons) == (
        surfaces.server_tools - surfaces.project_enabled_tools
    )
    assert all(surfaces.project_exclusion_reasons.values())

    for profile in surfaces.phase_profiles:
        assert profile.allowed_tools <= surfaces.project_enabled_tools
        assert profile.allowed_tools <= surfaces.server_tools
        assert profile.default_exclusion_reason
        for tool in surfaces.server_tools - profile.allowed_tools:
            assert profile.exclusion_reason(tool)


def test_v2_catalog_entries_remain_experimental() -> None:
    """Prevent design-time AQ v2 and delivery roles from claiming verified support."""

    profiles = {entry.profile_id: entry for entry in catalog.AUTONOMY_PROFILES}
    deliveries = {entry.delivery_id: entry for entry in catalog.DELIVERY_PROFILES}

    assert profiles["autonomous_static_prop_v1"].status == "verified_active"
    assert profiles["autonomous_static_prop_v2"].status == "disabled_experimental"
    assert (
        profiles["autonomous_static_prop_v2_codex_imagegen"].status
        == "disabled_experimental"
    )
    assert deliveries["portable_fbx"].asset_profile_id == "fbx_interchange"
    assert deliveries["portable_fbx"].status == "disabled_experimental"
    assert deliveries["review_only"].production_package is False
    assert deliveries["review_only"].handoff_eligible is False


def test_pure_catalog_import_never_loads_bpy() -> None:
    """Keep registry and CI discovery independent of an installed Blender runtime."""

    code = (
        "import sys; "
        "import codex_blender_modeler.repository_catalog; "
        "raise SystemExit(1 if 'bpy' in sys.modules else 0)"
    )
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)

