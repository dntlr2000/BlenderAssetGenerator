"""Pure repository registries used by documentation, CI, and controller-policy checks."""

from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATALOG_SCHEMA_VERSION = "0.1.0"

LEGACY_BUILDER_KINDS = (
    "curve",
    "custom_mesh",
    "primitive",
    "profile_extrude",
    "revolve",
    "terrain",
)
STRUCTURAL_BUILDER_KINDS = (
    "boolean_tree",
    "curve",
    "custom_mesh",
    "geometry_nodes_template",
    "loft",
    "multi_loop_extrude",
    "primitive",
    "profile_extrude",
    "revolve",
    "sweep",
    "terrain",
)

RULE_GROUPS: tuple[tuple[str, int, int], ...] = (
    ("core_modeling_evidence", 1, 27),
    ("portable_interior_optimization", 28, 44),
    ("orchestration_stabilization", 45, 66),
    ("interior_qa", 67, 71),
    ("background_and_content_scope", 72, 100),
    ("visual_convergence", 101, 112),
    ("surface_material_fidelity", 113, 121),
    ("assembly_multiview", 122, 145),
    ("external_static_intake", 146, 150),
    ("candidate_review", 151, 156),
    ("production_controller", 157, 174),
    ("autonomous_quality_v1", 175, 192),
)


@dataclass(frozen=True)
class AutonomyProfileCatalogEntry:
    """Describe one profile without importing the runtime autonomy service."""

    profile_id: str
    status: str
    contract_version: str
    execution_policy: str
    output_scope: str
    notes: str

    def as_dict(self) -> dict[str, str]:
        """Project this immutable profile entry into deterministic JSON data."""

        return {
            "profile_id": self.profile_id,
            "status": self.status,
            "contract_version": self.contract_version,
            "execution_policy": self.execution_policy,
            "output_scope": self.output_scope,
            "notes": self.notes,
        }


AUTONOMY_PROFILES = (
    AutonomyProfileCatalogEntry(
        profile_id="autonomous_static_prop_v1",
        status="verified_active",
        contract_version="0.1.0",
        execution_policy="standard",
        output_scope="portable_gltf",
        notes="Existing AQ 0.1 meaning; this catalog does not re-verify its evidence.",
    ),
    AutonomyProfileCatalogEntry(
        profile_id="autonomous_static_prop_v2",
        status="disabled_experimental",
        contract_version="0.2.0",
        execution_policy="standard",
        output_scope="delivery_profile",
        notes=(
            "AQ 0.2 design target with optional Approval Envelope 0.3 and One-Prompt 0.1 "
            "companions; activation requires actual asset host and Blender gates."
        ),
    ),
    AutonomyProfileCatalogEntry(
        profile_id="autonomous_static_prop_v2_codex_imagegen",
        status="disabled_experimental",
        contract_version="0.1.0",
        execution_policy="standard",
        output_scope="controller-mediated image staging and material-loop companion",
        notes=(
            "Optional Codex built-in ImageGen companion with host-only material promotion "
            "and AQ/IQ handoff; base AQ v2 remains local-only and the repository cannot "
            "spawn a Codex task."
        ),
    ),
    AutonomyProfileCatalogEntry(
        profile_id="autonomous_environment_v1",
        status="disabled_experimental",
        contract_version="0.1.0",
        execution_policy="standard",
        output_scope="unspecified",
        notes="Registry placeholder only; not activated.",
    ),
    AutonomyProfileCatalogEntry(
        profile_id="autonomous_architecture_v1",
        status="disabled_experimental",
        contract_version="0.1.0",
        execution_policy="standard",
        output_scope="unspecified",
        notes="Registry placeholder only; not activated.",
    ),
    AutonomyProfileCatalogEntry(
        profile_id="autonomous_measured_asset_v1",
        status="disabled_experimental",
        contract_version="0.1.0",
        execution_policy="standard",
        output_scope="unspecified",
        notes="Registry placeholder only; not activated.",
    ),
)


@dataclass(frozen=True)
class DeliveryProfileCatalogEntry:
    """Describe one public delivery role and its existing V0.7 mapping."""

    delivery_id: str
    status: str
    asset_profile_id: str | None
    format: str | None
    production_package: bool
    handoff_eligible: bool
    notes: str

    def as_dict(self) -> dict[str, object]:
        """Project this delivery entry without enabling an experimental path."""

        return {
            "delivery_id": self.delivery_id,
            "status": self.status,
            "asset_profile_id": self.asset_profile_id,
            "format": self.format,
            "production_package": self.production_package,
            "handoff_eligible": self.handoff_eligible,
            "notes": self.notes,
        }


DELIVERY_PROFILES = (
    DeliveryProfileCatalogEntry(
        delivery_id="portable_gltf",
        status="existing_v07",
        asset_profile_id="portable_gltf",
        format="glb",
        production_package=True,
        handoff_eligible=True,
        notes="Existing engine-neutral V0.7 package and roundtrip path.",
    ),
    DeliveryProfileCatalogEntry(
        delivery_id="portable_fbx",
        status="disabled_experimental",
        asset_profile_id="fbx_interchange",
        format="fbx",
        production_package=True,
        handoff_eligible=True,
        notes="AQ 0.2 delivery role; maps without renaming the V0.7 asset profile.",
    ),
    DeliveryProfileCatalogEntry(
        delivery_id="review_only",
        status="disabled_experimental",
        asset_profile_id=None,
        format=None,
        production_package=False,
        handoff_eligible=False,
        notes="Human review output only; never a package or handoff source.",
    ),
    DeliveryProfileCatalogEntry(
        delivery_id="obj_legacy",
        status="existing_v07_legacy",
        asset_profile_id="obj_legacy",
        format="obj",
        production_package=True,
        handoff_eligible=False,
        notes="Preserved V0.7 regression surface; not an AQ 0.2 default delivery.",
    ),
)


@dataclass(frozen=True)
class PhaseToolProfile:
    """Declare one bounded controller phase independently of project enablement."""

    profile_id: str
    status: str
    allowed_tools: frozenset[str]
    allowed_file_roles: tuple[str, ...]
    canonical_write: bool
    network_policy: str
    destination_write_policy: str
    default_exclusion_reason: str
    explicit_exclusion_reasons: tuple[tuple[str, str], ...] = ()

    def exclusion_reason(self, tool_name: str) -> str:
        """Return the explicit or conservative default reason for one excluded tool."""

        reasons = dict(self.explicit_exclusion_reasons)
        return reasons.get(tool_name, self.default_exclusion_reason)

    def as_dict(self, server_tools: frozenset[str]) -> dict[str, object]:
        """Project allowed and intentionally excluded tools as separate data."""

        explicit = dict(self.explicit_exclusion_reasons)
        return {
            "profile_id": self.profile_id,
            "status": self.status,
            "allowed_tools": sorted(self.allowed_tools),
            "excluded_tool_count": len(server_tools - self.allowed_tools),
            "default_exclusion_reason": self.default_exclusion_reason,
            "explicit_exclusion_reasons": {
                tool: explicit[tool] for tool in sorted(explicit)
            },
            "allowed_file_roles": list(self.allowed_file_roles),
            "canonical_write": self.canonical_write,
            "network_policy": self.network_policy,
            "destination_write_policy": self.destination_write_policy,
        }


_APPROVAL_TOOL_EXCLUSIONS = (
    (
        "approve_workflow_checkpoint",
        "Specialized or user checkpoint authority is outside delegated phase profiles.",
    ),
    (
        "approve_visual_revision",
        "Guarded revision approval requires its exact user approval boundary.",
    ),
    (
        "approve_visual_convergence",
        "Convergence approval requires an exact user-approved plan hash.",
    ),
    (
        "approve_portable_asset_optimization",
        "V0.7 optimization approval is exact, single-use, and user controlled.",
    ),
    (
        "generate_destination_handoff",
        "Handoff generation follows a separate exact plan-hash approval.",
    ),
)

PHASE_TOOL_PROFILES = (
    PhaseToolProfile(
        profile_id="reference_readonly",
        status="catalog_only",
        allowed_tools=frozenset(
            {
                "get_job_status",
                "get_modeling_capabilities",
                "get_reference_analysis",
                "get_workflow_state",
                "get_autonomy_profile_status",
                "get_autonomy_state",
            }
        ),
        allowed_file_roles=("immutable_reference", "analysis_report", "workflow_state"),
        canonical_write=False,
        network_policy="denied",
        destination_write_policy="denied",
        default_exclusion_reason="Not required for reference-readonly evidence inspection.",
        explicit_exclusion_reasons=_APPROVAL_TOOL_EXCLUSIONS,
    ),
    PhaseToolProfile(
        profile_id="geometry_authoring",
        status="catalog_only",
        allowed_tools=frozenset(
            {
                "analyze_reference",
                "build_scene",
                "render_preview",
                "inspect_scene",
                "validate_scene",
                "plan_assembly_multiview_sanity",
                "run_assembly_multiview_sanity",
                "run_visual_diagnostics",
            }
        ),
        allowed_file_roles=(
            "workflow_candidate",
            "derived_scene",
            "preview",
            "inventory",
            "validation",
            "geometry_diagnostic",
        ),
        canonical_write=False,
        network_policy="denied",
        destination_write_policy="denied",
        default_exclusion_reason="Outside bounded geometry candidate and diagnostic work.",
        explicit_exclusion_reasons=_APPROVAL_TOOL_EXCLUSIONS,
    ),
    PhaseToolProfile(
        profile_id="material_authoring",
        status="catalog_only",
        allowed_tools=frozenset(
            {
                "get_material_presets",
                "validate_material_contracts",
                "validate_material_fidelity",
                "validate_surface_details",
                "get_surface_detail_status",
                "inspect_materials",
                "render_material_swatches",
            }
        ),
        allowed_file_roles=(
            "workflow_material_candidate",
            "material_validation",
            "material_inventory",
            "swatch",
        ),
        canonical_write=False,
        network_policy="denied",
        destination_write_policy="denied",
        default_exclusion_reason="Outside validated workflow-owned material evidence.",
        explicit_exclusion_reasons=_APPROVAL_TOOL_EXCLUSIONS,
    ),
    PhaseToolProfile(
        profile_id="codex_imagegen",
        status="disabled_experimental",
        allowed_tools=frozenset(),
        allowed_file_roles=(
            "codex_image_assignment",
            "codex_image_generation_input",
            "generated_image_staging",
            "completion_marker",
        ),
        canonical_write=False,
        network_policy="codex_builtin_tool_only",
        destination_write_policy="denied",
        default_exclusion_reason=(
            "Codex built-in ImageGen is controller-mediated and grants no project MCP "
            "authority."
        ),
        explicit_exclusion_reasons=_APPROVAL_TOOL_EXCLUSIONS,
    ),
    PhaseToolProfile(
        profile_id="quality_readonly",
        status="catalog_only",
        allowed_tools=frozenset(
            {
                "run_visual_qa",
                "run_visual_diagnostics",
                "get_integrated_quality_status",
                "get_visual_convergence_status",
                "get_interior_qa_status",
                "get_semantic_reference_mask_status",
                "generate_pdf_report",
            }
        ),
        allowed_file_roles=("qa_run", "quality_companion", "derived_pdf"),
        canonical_write=False,
        network_policy="denied",
        destination_write_policy="denied",
        default_exclusion_reason="Not needed for read-only quality evidence production.",
        explicit_exclusion_reasons=_APPROVAL_TOOL_EXCLUSIONS,
    ),
    PhaseToolProfile(
        profile_id="delivery",
        status="catalog_only",
        allowed_tools=frozenset(
            {
                "run_asset_preflight",
                "plan_portable_asset_optimization",
                "optimize_portable_asset",
                "convert_portable_materials",
                "build_portable_package",
                "validate_portable_package",
                "get_portable_asset_status",
            }
        ),
        allowed_file_roles=("optimization_run", "derived_export", "package", "roundtrip"),
        canonical_write=False,
        network_policy="denied",
        destination_write_policy="denied",
        default_exclusion_reason="Outside approved engine-neutral delivery work.",
        explicit_exclusion_reasons=_APPROVAL_TOOL_EXCLUSIONS,
    ),
    PhaseToolProfile(
        profile_id="handoff_plan",
        status="catalog_only",
        allowed_tools=frozenset(
            {
                "plan_destination_handoff",
                "get_destination_handoff_status",
            }
        ),
        allowed_file_roles=("passed_package", "handoff_plan"),
        canonical_write=False,
        network_policy="denied",
        destination_write_policy="denied",
        default_exclusion_reason="Handoff planning cannot generate, approve, or apply delivery.",
        explicit_exclusion_reasons=_APPROVAL_TOOL_EXCLUSIONS,
    ),
    PhaseToolProfile(
        profile_id="admin_audit",
        status="catalog_only",
        allowed_tools=frozenset(
            {
                "probe_release_environment",
                "audit_workspace_state",
                "generate_stability_pdf_report",
                "get_local_workflow_queue",
            }
        ),
        allowed_file_roles=("environment_probe", "workspace_audit", "derived_pdf", "queue_status"),
        canonical_write=False,
        network_policy="denied",
        destination_write_policy="denied",
        default_exclusion_reason="Not required for bounded read-only administration.",
        explicit_exclusion_reasons=_APPROVAL_TOOL_EXCLUSIONS,
    ),
    PhaseToolProfile(
        profile_id="delegated_controller_v1",
        status="existing_contract",
        allowed_tools=frozenset(
            {
                "get_asset_production_dispatch_status",
                "advance_delegated_production_controller",
                "record_delegated_production_step",
            }
        ),
        allowed_file_roles=("production_dispatch", "workflow_state", "advance_receipt"),
        canonical_write=True,
        network_policy="client_attested_only",
        destination_write_policy="denied",
        default_exclusion_reason="The existing delegated controller profile is allowlist-only.",
        explicit_exclusion_reasons=_APPROVAL_TOOL_EXCLUSIONS,
    ),
)

PROJECT_MCP_EXCLUSION_REASONS = {
    "recover_candidate_review_promotion_failure": (
        "Recovery remains intentionally excluded from project-enabled MCP until its "
        "failure-specific user authorization boundary is reviewed."
    ),
}


@dataclass(frozen=True)
class ToolSurfaceCatalog:
    """Hold three deliberately distinct MCP authorization surfaces."""

    server_tools: frozenset[str]
    project_enabled_tools: frozenset[str]
    project_exclusion_reasons: dict[str, str]
    phase_profiles: tuple[PhaseToolProfile, ...]

    def as_dict(self) -> dict[str, object]:
        """Serialize tool surfaces without conflating registration and authority."""

        server_only = sorted(self.server_tools - self.project_enabled_tools)
        return {
            "server_tools": sorted(self.server_tools),
            "project_enabled_tools": sorted(self.project_enabled_tools),
            "project_intentional_exclusions": {
                tool: self.project_exclusion_reasons.get(
                    tool,
                    "MISSING INTENTIONAL EXCLUSION REASON",
                )
                for tool in server_only
            },
            "phase_profiles": [
                profile.as_dict(self.server_tools) for profile in self.phase_profiles
            ],
        }


def _is_named_call(node: ast.expr, owner: str, attribute: str) -> bool:
    """Recognize a simple owner.attribute(...) decorator call."""

    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == owner
        and node.func.attr == attribute
    )


def discover_mcp_server_tools(path: Path) -> frozenset[str]:
    """Parse FastMCP decorators without importing the server or Blender dependencies."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tools: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(_is_named_call(decorator, "mcp", "tool") for decorator in node.decorator_list):
            tools.add(node.name)
    return frozenset(tools)


def discover_cli_commands(path: Path) -> tuple[str, ...]:
    """Parse Typer command decorators without importing the CLI dependency graph."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    commands: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [
            decorator
            for decorator in node.decorator_list
            if _is_named_call(decorator, "app", "command")
        ]
        for decorator in decorators:
            assert isinstance(decorator, ast.Call)
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                commands.add(str(decorator.args[0].value))
            else:
                commands.add(node.name.replace("_", "-"))
    return tuple(sorted(commands))


def load_project_enabled_mcp_tools(
    path: Path,
    *,
    server_name: str = "blender_modeler",
) -> frozenset[str]:
    """Read the project-scoped enabled tool set from TOML without starting MCP."""

    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    servers = payload.get("mcp_servers", {})
    selected = servers.get(server_name, {})
    enabled = selected.get("enabled_tools", [])
    if not isinstance(enabled, list) or not all(isinstance(item, str) for item in enabled):
        raise ValueError(f"{server_name}.enabled_tools must be a list of strings")
    if len(enabled) != len(set(enabled)):
        raise ValueError(f"{server_name}.enabled_tools contains duplicates")
    return frozenset(enabled)


def discover_literal_dict_keys(path: Path, variable_name: str) -> frozenset[str]:
    """Read literal string keys from one module-level registry assignment."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        value: ast.expr | None = None
        names: list[str] = []
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
            value = node.value
        if variable_name not in names or not isinstance(value, ast.Dict):
            continue
        keys: set[str] = set()
        for key in value.keys:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                raise ValueError(f"{variable_name} must use literal string keys")
            keys.add(key.value)
        return frozenset(keys)
    raise ValueError(f"registry {variable_name} not found in {path}")


def build_tool_surface_catalog(root: Path) -> ToolSurfaceCatalog:
    """Build exact server, project, and phase surfaces from their separate sources."""

    server_tools = discover_mcp_server_tools(
        root / "src" / "codex_blender_modeler" / "mcp_server.py"
    )
    enabled_tools = load_project_enabled_mcp_tools(root / ".codex" / "config.toml")
    return ToolSurfaceCatalog(
        server_tools=server_tools,
        project_enabled_tools=enabled_tools,
        project_exclusion_reasons=dict(PROJECT_MCP_EXCLUSION_REASONS),
        phase_profiles=PHASE_TOOL_PROFILES,
    )


def validate_repository_catalog(root: Path) -> tuple[str, ...]:
    """Return deterministic drift findings for pure registries and tool surfaces."""

    findings: list[str] = []
    legacy_source = discover_literal_dict_keys(
        root / "src" / "codex_blender_modeler" / "blender_scripts" / "builders" / "registry.py",
        "_BUILDERS",
    )
    if legacy_source != frozenset(LEGACY_BUILDER_KINDS):
        findings.append("legacy builder catalog differs from Blender registry source")
    structural_source = discover_literal_dict_keys(
        root
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "builders"
        / "structural_registry.py",
        "_STRUCTURAL_BUILDERS",
    )
    if structural_source != frozenset(STRUCTURAL_BUILDER_KINDS):
        findings.append("structural builder catalog differs from Blender registry source")

    from .autonomy.profiles import profile_registry
    from .autonomy_v2.profiles import autonomy_v2_profile_catalog

    runtime_profiles = {
        str(entry["profile_id"]): (
            str(entry["status"]),
            str(entry.get("contract_version", "0.1.0")),
        )
        for entry in profile_registry()
    }
    for v2_profile in autonomy_v2_profile_catalog():
        runtime_profiles[str(v2_profile["profile_id"])] = (
            str(v2_profile["status"]),
            str(v2_profile["contract_version"]),
        )
    catalog_profiles = {
        entry.profile_id: (entry.status, entry.contract_version)
        for entry in AUTONOMY_PROFILES
    }
    if runtime_profiles != catalog_profiles:
        findings.append("autonomy profile catalog differs from runtime profile registry")

    portable_profile_path = (
        root / "src" / "codex_blender_modeler" / "optimization" / "models.py"
    )
    portable_tree = ast.parse(
        portable_profile_path.read_text(encoding="utf-8"),
        filename=str(portable_profile_path),
    )
    runtime_delivery_profiles: set[str] = set()
    for node in portable_tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "PortableProfile"
            for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Subscript) and isinstance(node.value.slice, ast.Tuple):
            runtime_delivery_profiles = {
                str(element.value)
                for element in node.value.slice.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    mapped_delivery_profiles = {
        entry.asset_profile_id
        for entry in DELIVERY_PROFILES
        if entry.asset_profile_id is not None
    }
    if mapped_delivery_profiles != runtime_delivery_profiles:
        findings.append("delivery catalog differs from PortableProfile registry")

    surfaces = build_tool_surface_catalog(root)
    unknown_enabled = surfaces.project_enabled_tools - surfaces.server_tools
    if unknown_enabled:
        findings.append(
            "project enabled tools missing from server: " + ", ".join(sorted(unknown_enabled))
        )
    server_only = surfaces.server_tools - surfaces.project_enabled_tools
    missing_reasons = server_only - surfaces.project_exclusion_reasons.keys()
    stale_reasons = surfaces.project_exclusion_reasons.keys() - server_only
    if missing_reasons:
        findings.append(
            "server-only tools missing exclusion reasons: " + ", ".join(sorted(missing_reasons))
        )
    if stale_reasons:
        findings.append(
            "stale project exclusion reasons: " + ", ".join(sorted(stale_reasons))
        )
    phase_ids = [profile.profile_id for profile in surfaces.phase_profiles]
    if len(phase_ids) != len(set(phase_ids)):
        findings.append("phase profile IDs must be unique")
    for profile in surfaces.phase_profiles:
        unknown_phase_tools = profile.allowed_tools - surfaces.server_tools
        if unknown_phase_tools:
            findings.append(
                f"phase profile {profile.profile_id} has unknown tools: "
                + ", ".join(sorted(unknown_phase_tools))
            )
        disabled_phase_tools = profile.allowed_tools - surfaces.project_enabled_tools
        if disabled_phase_tools:
            findings.append(
                f"phase profile {profile.profile_id} uses project-disabled tools: "
                + ", ".join(sorted(disabled_phase_tools))
            )
        stale_explicit = {
            tool for tool, _reason in profile.explicit_exclusion_reasons
        } - surfaces.server_tools
        if stale_explicit:
            findings.append(
                f"phase profile {profile.profile_id} has stale explicit exclusions: "
                + ", ".join(sorted(stale_explicit))
            )
    return tuple(findings)


def repository_catalog_projection(root: Path) -> dict[str, Any]:
    """Return the deterministic pure catalog used by summary generation."""

    surfaces = build_tool_surface_catalog(root)
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "builders": {
            "legacy": list(LEGACY_BUILDER_KINDS),
            "structural": list(STRUCTURAL_BUILDER_KINDS),
        },
        "autonomy_profiles": [entry.as_dict() for entry in AUTONOMY_PROFILES],
        "delivery_profiles": [entry.as_dict() for entry in DELIVERY_PROFILES],
        "cli_commands": list(
            discover_cli_commands(root / "src" / "codex_blender_modeler" / "cli.py")
        ),
        "mcp": surfaces.as_dict(),
        "catalog_findings": list(validate_repository_catalog(root)),
    }
