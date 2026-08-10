"""Companion broad-, narrow-, and semantic-phase assembly evidence."""

from .models import (
    AABB,
    AssemblyCompanionReport,
    AssemblyCompanionRequest,
    AssemblyFinding,
    BVHNarrowObservation,
    SemanticAssemblyRelation,
    TriangleMeshEvidence,
)
from .service import (
    bounded_nearest_distance,
    build_assembly_companion_report,
    build_broad_phase_pairs,
    build_pure_python_observation,
)

__all__ = [
    "AABB",
    "AssemblyCompanionReport",
    "AssemblyCompanionRequest",
    "AssemblyFinding",
    "BVHNarrowObservation",
    "SemanticAssemblyRelation",
    "TriangleMeshEvidence",
    "bounded_nearest_distance",
    "build_assembly_companion_report",
    "build_broad_phase_pairs",
    "build_pure_python_observation",
]
