"""Human-readable PDF projection for one machine-authoritative destination handoff."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)


def _font_name() -> str:
    """Register an available Unicode font or use the standard Latin fallback."""

    candidates = [
        Path(r"C:\Windows\Fonts\malgun.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if not path.is_file():
            continue
        name = "CBMHandoffUnicode"
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(path)))
        return name
    return "Helvetica"


def _styles(font: str) -> dict[str, ParagraphStyle]:
    """Build a compact technical-report style set for handoff summaries."""

    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "HandoffTitle",
            parent=base["Title"],
            fontName=font,
            fontSize=22,
            leading=28,
            textColor=colors.HexColor("#14213D"),
            spaceAfter=8 * mm,
        ),
        "h1": ParagraphStyle(
            "HandoffH1",
            parent=base["Heading1"],
            fontName=font,
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#2F6FED"),
            spaceBefore=5 * mm,
            spaceAfter=3 * mm,
        ),
        "body": ParagraphStyle(
            "HandoffBody",
            parent=base["BodyText"],
            fontName=font,
            fontSize=8.5,
            leading=13,
            textColor=colors.HexColor("#1D2939"),
        ),
        "small": ParagraphStyle(
            "HandoffSmall",
            parent=base["BodyText"],
            fontName=font,
            fontSize=7,
            leading=10,
            textColor=colors.HexColor("#344054"),
        ),
    }


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    """Render arbitrary report data as escaped paragraph text."""

    return Paragraph(escape(str(value)), style)


def _table(
    headings: list[str],
    rows: list[list[Any]],
    widths: list[float],
    styles: dict[str, ParagraphStyle],
) -> LongTable:
    """Create one repeated-header table with safe text wrapping."""

    data = [[_paragraph(item, styles["small"]) for item in headings]]
    data.extend([[_paragraph(item, styles["small"]) for item in row] for row in rows])
    table = LongTable(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF1FF")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#14213D")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D0D5DD")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def render_handoff_pdf(documents: dict[str, dict[str, Any]], output: Path) -> dict[str, str]:
    """Render a deterministic PDF summary from validated handoff JSON documents."""

    font = _font_name()
    styles = _styles(font)
    manifest = documents["handoff_manifest"]
    context = documents["destination_context"]
    assembly = documents["assembly_manifest"]
    materials = documents["material_mapping"]
    checklist = documents["import_checklist"]
    story: list[Any] = [
        _paragraph("Codex Destination Handoff Report", styles["title"]),
        _paragraph(
            "This PDF is a derived review aid. The JSON contracts and exact SHA-256 "
            "receipts remain authoritative.",
            styles["body"],
        ),
        Spacer(1, 3 * mm),
        _table(
            ["Field", "Value"],
            [
                ["Handoff ID", manifest["handoff_id"]],
                ["Job / Package", f"{manifest['job_id']} / {manifest['package_id']}"],
                ["Profile", manifest["profile_id"]],
                ["Primary model", manifest["primary_model"]["path"]],
                ["Package manifest SHA-256", manifest["package_manifest"]["sha256"]],
                ["Round-trip SHA-256", manifest["roundtrip_validation"]["sha256"]],
                ["LOD / Collider", f"{manifest['lod_present']} / {manifest['collider_present']}"],
            ],
            [46 * mm, 128 * mm],
            styles,
        ),
        _paragraph("Destination context", styles["h1"]),
        _table(
            ["Contract", "Evidence"],
            [
                ["Asset scope", context["asset_kind"]],
                ["Units", context["axis"]["unit"]],
                [
                    "Orientation",
                    f"source {context['axis']['source_up_axis']} up / "
                    f"interchange {context['axis']['interchange_up_axis']} up",
                ],
                ["Pivot policy", context["pivot_policy"]],
                ["Export hierarchy", context["hierarchy"]["exported_hierarchy"]],
                [
                    "LOD reconstruction",
                    f"{context['lod_and_collider']['lod_group_count']} explicit groups; "
                    f"default LOD {context['lod_and_collider']['default_active_lod']}; "
                    f"{context['lod_and_collider']['switch_policy']}",
                ],
                ["Format losses", "; ".join(context["known_format_losses"]) or "none declared"],
                ["Unverified", "; ".join(context["unverified_items"])],
            ],
            [46 * mm, 128 * mm],
            styles,
        ),
        PageBreak(),
        _paragraph("Assembly manifest", styles["h1"]),
        _table(
            ["Semantic ID", "Role", "LOD", "Default", "LOD group", "Export object"],
            [
                [
                    item["semantic_id"],
                    item["asset_role"],
                    item["lod_level"] if item["lod_level"] is not None else "-",
                    item["default_active"],
                    item["lod_group_id"] or "-",
                    item["object_name"],
                ]
                for item in assembly["nodes"]
            ],
            [38 * mm, 16 * mm, 10 * mm, 15 * mm, 43 * mm, 52 * mm],
            styles,
        ),
        PageBreak(),
        _paragraph("Portable material mapping", styles["h1"]),
        _table(
            ["Material ID", "Representation", "UV binding", "Available channels", "Known loss"],
            [
                [
                    item["material_id"],
                    item["texture_representation"],
                    (
                        f"{item['texture_coordinate_binding']['required_uv_set']} -> "
                        f"{item['texture_coordinate_binding']['destination_semantic']} "
                        f"(index {item['texture_coordinate_binding']['required_uv_channel_index']})"
                        if item["texture_coordinate_binding"] is not None
                        else "not declared"
                    ),
                    ", ".join(
                        channel["channel"]
                        for channel in item["channels"]
                        if channel["status"] != "unavailable"
                    )
                    or "none",
                    "; ".join(item["known_losses"]) or "none declared",
                ]
                for item in materials["materials"]
            ],
            [34 * mm, 34 * mm, 42 * mm, 32 * mm, 32 * mm],
            styles,
        ),
        _paragraph("Destination import checklist", styles["h1"]),
        _table(
            ["#", "Gate", "Checkpoint", "Instruction"],
            [
                [item["order"], item["gate"], item["title"], item["instruction"]]
                for item in checklist["items"]
            ],
            [9 * mm, 19 * mm, 42 * mm, 104 * mm],
            styles,
        ),
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Codex Destination Handoff Report",
        author="Codex Blender Modeler",
    )
    document.build(story)
    return {"font": font}
