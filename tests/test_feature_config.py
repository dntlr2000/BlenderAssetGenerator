from __future__ import annotations

from pathlib import Path

import pytest

from codex_blender_modeler.config import load_feature_config


def test_feature_config_defaults_are_conservative(tmp_path: Path) -> None:
    """Missing configuration keeps generated targets and automatic revision disabled."""

    config = load_feature_config(tmp_path / "missing.toml")
    assert config.features.material_core is True
    assert config.features.image_model_qa is False
    assert config.features.automatic_revision is False
    assert config.features.portable_asset_core is True
    assert config.qa.revision_mode == "suggest"
    assert config.qa.max_revision_iterations == 1
    assert config.qa.generated_target_weight == 0.15


def test_feature_config_loads_explicit_values(tmp_path: Path) -> None:
    """Explicit TOML values override defaults without changing core settings."""

    path = tmp_path / "cbm.toml"
    path.write_text(
        """
[features]
material_core = true
shader_core = false
texture_provider = "disabled"
visual_qa = true
image_model_qa = true
automatic_revision = false

[qa]
revision_mode = "approve"
max_revision_iterations = 2
generated_target_weight = 0.1
""".strip(),
        encoding="utf-8",
    )
    config = load_feature_config(path)
    assert config.features.shader_core is False
    assert config.features.image_model_qa is True
    assert config.qa.revision_mode == "approve"
    assert config.qa.max_revision_iterations == 2
    assert config.qa.generated_target_weight == 0.1


def test_feature_config_rejects_unsafe_revision_iterations(tmp_path: Path) -> None:
    """Unbounded automatic revision loops are rejected during configuration loading."""

    path = tmp_path / "cbm.toml"
    path.write_text("[qa]\nmax_revision_iterations = 99\n", encoding="utf-8")
    with pytest.raises(ValueError, match="max_revision_iterations"):
        load_feature_config(path)


def test_feature_config_requires_explicit_automatic_revision_flag(tmp_path: Path) -> None:
    """Auto mode cannot be activated while its independent safety flag is disabled."""

    path = tmp_path / "cbm.toml"
    path.write_text(
        "[features]\nautomatic_revision = false\n[qa]\nrevision_mode = \"auto\"\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="automatic_revision=true"):
        load_feature_config(path)

    path.write_text(
        "[features]\nautomatic_revision = true\n[qa]\nrevision_mode = \"auto\"\n",
        encoding="utf-8",
    )
    config = load_feature_config(path)
    assert config.features.automatic_revision is True
    assert config.qa.revision_mode == "auto"
