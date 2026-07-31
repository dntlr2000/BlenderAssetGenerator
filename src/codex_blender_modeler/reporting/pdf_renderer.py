from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Image,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#14213D")
BLUE = colors.HexColor("#2F6FED")
PALE_BLUE = colors.HexColor("#EAF1FF")
GREEN = colors.HexColor("#1B7F5A")
PALE_GREEN = colors.HexColor("#E7F6EF")
AMBER = colors.HexColor("#A96700")
PALE_AMBER = colors.HexColor("#FFF4D6")
RED = colors.HexColor("#B42318")
PALE_RED = colors.HexColor("#FDECEA")
INK = colors.HexColor("#1D2939")
MUTED = colors.HexColor("#667085")
LINE = colors.HexColor("#D0D5DD")
PANEL = colors.HexColor("#F8FAFC")


def _font_candidates() -> list[tuple[Path, Path | None]]:
    """Return cross-platform Korean font candidates in deterministic preference order."""

    configured = os.getenv("CBM_PDF_FONT_PATH", "").strip()
    configured_bold = os.getenv("CBM_PDF_BOLD_FONT_PATH", "").strip()
    candidates: list[tuple[Path, Path | None]] = []
    if configured:
        candidates.append((Path(configured), Path(configured_bold) if configured_bold else None))
    candidates.extend(
        [
            (Path(r"C:\Windows\Fonts\malgun.ttf"), Path(r"C:\Windows\Fonts\malgunbd.ttf")),
            (
                Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
                Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
            ),
            (
                Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
                Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
            ),
            (
                Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
                Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
            ),
        ]
    )
    return candidates


def _register_report_fonts() -> dict[str, str]:
    """Register an embedded Korean font or a standard Korean CID fallback."""

    regular_name = "CBMReportRegular"
    bold_name = "CBMReportBold"
    for regular_path, bold_path in _font_candidates():
        if not regular_path.is_file():
            continue
        if regular_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
        usable_bold = bold_path if bold_path and bold_path.is_file() else regular_path
        if bold_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(bold_name, str(usable_bold)))
        return {
            "regular": regular_name,
            "bold": bold_name,
            "source": f"embedded:{regular_path.name}",
        }
    if "HYGoThic-Medium" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont("HYGoThic-Medium"))
    return {
        "regular": "HYGoThic-Medium",
        "bold": "HYGoThic-Medium",
        "source": "cid-fallback:HYGoThic-Medium",
    }


def _report_styles(fonts: dict[str, str]) -> dict[str, ParagraphStyle]:
    """Build a compact Korean-capable style set for A4 technical reports."""

    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "CBMTitle",
            parent=base["Title"],
            fontName=fonts["bold"],
            fontSize=23,
            leading=30,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=7 * mm,
            wordWrap="CJK",
        ),
        "subtitle": ParagraphStyle(
            "CBMSubtitle",
            parent=base["BodyText"],
            fontName=fonts["regular"],
            fontSize=9,
            leading=14,
            textColor=MUTED,
            wordWrap="CJK",
        ),
        "h1": ParagraphStyle(
            "CBMH1",
            parent=base["Heading1"],
            fontName=fonts["bold"],
            fontSize=16,
            leading=21,
            textColor=NAVY,
            spaceBefore=7 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
            wordWrap="CJK",
        ),
        "h2": ParagraphStyle(
            "CBMH2",
            parent=base["Heading2"],
            fontName=fonts["bold"],
            fontSize=11,
            leading=15,
            textColor=BLUE,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
            wordWrap="CJK",
        ),
        "body": ParagraphStyle(
            "CBMBody",
            parent=base["BodyText"],
            fontName=fonts["regular"],
            fontSize=8.5,
            leading=13,
            textColor=INK,
            spaceAfter=2 * mm,
            wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "CBMSmall",
            parent=base["BodyText"],
            fontName=fonts["regular"],
            fontSize=7,
            leading=10,
            textColor=INK,
            wordWrap="CJK",
        ),
        "small_center": ParagraphStyle(
            "CBMSmallCenter",
            parent=base["BodyText"],
            fontName=fonts["regular"],
            fontSize=7,
            leading=10,
            textColor=INK,
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "table_header": ParagraphStyle(
            "CBMTableHeader",
            parent=base["BodyText"],
            fontName=fonts["bold"],
            fontSize=7,
            leading=9,
            textColor=colors.white,
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "metric": ParagraphStyle(
            "CBMMetric",
            parent=base["BodyText"],
            fontName=fonts["bold"],
            fontSize=16,
            leading=20,
            textColor=NAVY,
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "metric_label": ParagraphStyle(
            "CBMMetricLabel",
            parent=base["BodyText"],
            fontName=fonts["regular"],
            fontSize=7,
            leading=10,
            textColor=MUTED,
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
    }


def _text(value: Any) -> str:
    """Convert arbitrary report values to escaped, compact human-readable text."""

    if value is None:
        return "-"
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(item) for item in value)
    return escape(str(value))


def _bounded_table_value(
    value: Any,
    *,
    max_items: int = 12,
    max_chars: int = 720,
) -> str:
    """Summarize oversized table values so one PDF row cannot exceed a page."""

    if value is None:
        rendered = "-"
    elif isinstance(value, bool):
        rendered = str(value)
    elif isinstance(value, float):
        rendered = f"{value:.6g}"
    elif isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
        rendered = ", ".join(items[:max_items])
        if len(items) > max_items:
            rendered += f", ... (+{len(items) - max_items} more; see canonical JSON)"
    else:
        rendered = str(value)

    if len(rendered) <= max_chars:
        return rendered
    suffix = f" ... [truncated {len(rendered) - max_chars} chars; see canonical JSON]"
    prefix_length = max(1, max_chars - len(suffix))
    return rendered[:prefix_length].rstrip() + suffix


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    """Create a safe paragraph suitable for table cells and long Korean text."""

    return Paragraph(_text(value).replace("\n", "<br/>"), style)


def _rich_paragraph(markup: str, style: ParagraphStyle) -> Paragraph:
    """Create a paragraph from trusted markup whose dynamic values were already escaped."""

    return Paragraph(markup, style)


def _status(value: Any) -> tuple[str, colors.Color, colors.Color]:
    """Map report status values to a Korean label and accessible badge colors."""

    if value is True or str(value).lower() in {"passed", "complete", "ok", "true"}:
        return "통과", GREEN, PALE_GREEN
    if value is False or str(value).lower() in {"failed", "error", "false"}:
        return "실패", RED, PALE_RED
    return "주의", AMBER, PALE_AMBER


def _metric_table(
    items: list[tuple[str, Any]],
    styles: dict[str, ParagraphStyle],
) -> Table:
    """Render two to four prominent summary metrics as equal-width cards."""

    cells = [
        [
            _paragraph(value, styles["metric"]),
            _paragraph(label, styles["metric_label"]),
        ]
        for label, value in items
    ]
    table = Table([cells], colWidths=[(174 * mm) / len(cells)] * len(cells))
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _data_table(
    headers: list[str],
    rows: list[list[Any]],
    widths: list[float],
    styles: dict[str, ParagraphStyle],
) -> LongTable:
    """Render a repeating-header technical table with wrapped text and zebra striping."""

    data = [[_paragraph(item, styles["table_header"]) for item in headers]]
    data.extend([[_paragraph(item, styles["small"]) for item in row] for row in rows])
    table = LongTable(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for index in range(1, len(data)):
        if index % 2 == 0:
            commands.append(("BACKGROUND", (0, index), (-1, index), PANEL))
    table.setStyle(TableStyle(commands))
    return table


def _scaled_image(path: str, max_width: float, max_height: float) -> Image:
    """Create a proportionally scaled image without altering the source artifact."""

    image = Image(path)
    scale = min(max_width / image.imageWidth, max_height / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    return image


def _scope_title(scope: str) -> str:
    """Return a concise Korean title for one report presentation scope."""

    return {
        "build": "빌드 및 구조 검사 보고서",
        "material": "재질·셰이더 검사 보고서",
        "qa": "레퍼런스 시각 QA 보고서",
        "export": "V0.7 이식형 자산 내보내기 보고서",
        "full": "통합 자산 검사 보고서",
    }[scope]


def _append_background_quality_banner(
    story: list[Any],
    documents: dict[str, dict[str, Any]],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Show fast-preview execution and visual acceptance as separate cover outcomes."""

    quality = documents.get("background_quality_report")
    if quality is None:
        return
    status = str(quality.get("quality_status", "unscorable"))
    label, foreground, background = {
        "passed": ("품질 상태: passed", GREEN, PALE_GREEN),
        "needs_revision": ("품질 상태: needs_revision", RED, PALE_RED),
        "unscorable": ("품질 상태: unscorable", AMBER, PALE_AMBER),
    }.get(status, ("품질 상태: unknown", AMBER, PALE_AMBER))
    direct_score = quality.get("overall_direct_score")
    primary_score = quality.get("primary_silhouette_score")
    message = (
        "파이프라인 실행 및 검토 자료 전달은 완료되었습니다. "
        + (
            "현재 시각 품질도 fast-lane 기준을 통과했습니다."
            if status == "passed"
            else "이는 품질 합격을 의미하지 않으며 표준 수정 workflow 검토가 권장됩니다."
        )
    )
    table = Table(
        [
            [_paragraph(label, styles["h2"])],
            [_paragraph(message, styles["body"])],
            [
                _paragraph(
                    "Direct score: "
                    f"{direct_score if direct_score is not None else 'unavailable'}"
                    "  |  Primary silhouette: "
                    f"{primary_score if primary_score is not None else 'unavailable'}",
                    styles["metric_label"],
                )
            ],
        ],
        colWidths=[174 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("TEXTCOLOR", (0, 0), (-1, -1), foreground),
                ("BOX", (0, 0), (-1, -1), 1, foreground),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(table)


def _append_cover(
    story: list[Any],
    payload: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Append the report title, job metadata, provenance, and overall availability banner."""

    job = payload["job"]
    story.append(_paragraph(_scope_title(payload["scope"]), styles["title"]))
    story.append(
        _rich_paragraph(
            f"Job ID: <b>{escape(payload['job_id'])}</b><br/>"
            f"작업 모드: {_text(job.get('mode'))}<br/>"
            f"작업 생성 버전: {_text(job.get('project_version_created', '0.6.0'))}<br/>"
            f"소스 지문: {payload['source_fingerprint'][:16]}…",
            styles["subtitle"],
        )
    )
    _append_background_quality_banner(story, payload["documents"], styles)
    story.append(Spacer(1, 6 * mm))
    documents = payload["documents"]
    qa_revision_state: bool | str = (
        True
        if "revision_application" in documents
        else (
            "pending_approval"
            if "revision_plan" in documents or "revision_candidates" in documents
            else False
        )
    )
    has_interior_qa = "interior_qa_report" in documents
    qa_availability = (
        [
            ("SceneSpec", "scene_spec" in documents),
            ("실내 QA 계획", "interior_qa_plan" in documents),
            ("다각도 패스", "interior_qa_render_manifest" in documents),
            ("실내 QA 보고서", has_interior_qa),
        ]
        if has_interior_qa and "visual_qa_report" not in documents
        else [
            ("SceneSpec", "scene_spec" in documents),
            ("QA 패스", "qa_pass_manifest" in documents),
            ("직접 비교", "visual_qa_report" in documents),
            (
                "수정 결과" if qa_revision_state is True else "수정 계획",
                qa_revision_state,
            ),
        ]
    )
    availability = {
        "build": [
            ("SceneSpec", "scene_spec" in documents),
            ("구조 검증", "validation" in documents),
            ("Scene Inventory", "scene_inventory" in documents),
            ("실측 제약", "constraint_solution" in documents),
        ],
        "material": [
            ("SceneSpec", "scene_spec" in documents),
            ("재질 계약", "material_contract_validation" in documents),
            ("Blender 검사", "material_validation" in documents),
            ("스와치", "material_swatches" in documents),
        ],
        "qa": qa_availability,
        "export": [
            ("최적화 계획", "optimization_plan" in documents),
            ("메시 사전 검사", "mesh_preflight_report" in documents),
            ("패키지", "package_manifest" in documents),
            ("재임포트", "roundtrip_validation" in documents),
        ],
        "full": [
            ("구조 검증", "validation" in documents),
            ("재질 검사", "material_validation" in documents),
            ("시각 QA", "visual_qa_report" in documents or has_interior_qa),
            ("출처", bool(payload["sources"])),
        ],
    }[payload["scope"]]
    cells = []
    for label, available in availability:
        status_label, foreground, background = _status(available)
        if available == "pending_approval":
            status_label = "승인 대기"
        cell = Table(
            [
                [_paragraph(label, styles["metric_label"])],
                [_paragraph(status_label if available else "미생성", styles["metric_label"])],
            ],
            colWidths=[41 * mm],
        )
        cell.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), background),
                    ("TEXTCOLOR", (0, 1), (-1, 1), foreground),
                    ("BOX", (0, 0), (-1, -1), 0.5, foreground),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        cells.append(cell)
    story.append(Table([cells], colWidths=[43.5 * mm] * 4))
    if payload["warnings"]:
        story.append(Spacer(1, 5 * mm))
        story.append(_paragraph("보고서 생성 메모", styles["h2"]))
        for warning in payload["warnings"]:
            story.append(_paragraph(f"• {warning}", styles["body"]))


def _append_build_section(
    story: list[Any],
    documents: dict[str, dict[str, Any]],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Append structural, interior-scope, runtime, metric, and measured validation."""

    story.append(_paragraph("빌드 및 구조 상태", styles["h1"]))
    validation = documents.get("validation")
    if validation is None:
        story.append(_paragraph("구조 검증 보고서가 아직 생성되지 않았습니다.", styles["body"]))
        return
    metrics = validation.get("metrics", {})
    story.append(
        _metric_table(
            [
                ("검증", _status(validation.get("ok"))[0]),
                ("오류", len(validation.get("errors", []))),
                ("경고", len(validation.get("warnings", []))),
                ("메시 객체", metrics.get("generated_mesh_objects", "-")),
            ],
            styles,
        )
    )
    surface_detail = documents.get("surface_detail_validation") or {}
    if surface_detail:
        story.append(_paragraph("표면 디테일 텍스처 결속", styles["h2"]))
        story.append(
            _metric_table(
                [
                    ("검증", _status(surface_detail.get("ok"))[0]),
                    ("계약 상태", surface_detail.get("material_status", "-")),
                    ("텍스처 대상", surface_detail.get("textured", 0)),
                    ("명시적 생략", surface_detail.get("omitted", 0)),
                    ("실패 검사", surface_detail.get("failed", 0)),
                ],
                styles,
            )
        )
    runtime = validation.get("runtime", {})
    story.append(_paragraph("실행 환경", styles["h2"]))
    story.append(
        _data_table(
            ["항목", "값"],
            [
                ["Blender", runtime.get("blender_version")],
                ["렌더 엔진", runtime.get("render_engine")],
                ["렌더 장치", runtime.get("render_device")],
                ["Color Management", runtime.get("color_management_look")],
            ],
            [45 * mm, 129 * mm],
            styles,
        )
    )
    if metrics:
        story.append(_paragraph("구조 통계", styles["h2"]))
        rows = [[key, value] for key, value in metrics.items()]
        story.append(_data_table(["지표", "값"], rows, [70 * mm, 104 * mm], styles))
    interior = documents.get("interior_scope_validation")
    if interior:
        story.append(_paragraph("Interior opt-in boundary", styles["h2"]))
        story.append(
            _metric_table(
                [
                    ("Status", _status(interior.get("ok"))[0]),
                    ("Policy", interior.get("effective_policy", "disabled")),
                    ("Scope", interior.get("scope_state", "default_disabled")),
                    ("Objects", len(interior.get("interior_object_ids", []))),
                ],
                styles,
            )
        )
        findings = [
            ["error", message] for message in interior.get("errors", [])
        ] + [["warning", message] for message in interior.get("warnings", [])]
        if findings:
            story.append(
                _data_table(
                    ["Severity", "Finding"],
                    findings,
                    [28 * mm, 146 * mm],
                    styles,
                )
            )
    constraints = documents.get("constraint_solution")
    if constraints:
        story.append(_paragraph("실측 제약", styles["h2"]))
        story.append(
            _metric_table(
                [
                    ("평가", constraints.get("evaluated", 0)),
                    ("통과", constraints.get("passed", 0)),
                    ("실패", constraints.get("failed", 0)),
                    ("누락", constraints.get("missing", 0)),
                ],
                styles,
            )
        )
        rows = [
            [
                item.get("id"),
                item.get("kind"),
                item.get("status"),
                item.get("requested"),
                item.get("actual"),
                item.get("residual_m"),
                item.get("tolerance_m"),
            ]
            for item in constraints.get("results", [])
        ]
        if rows:
            story.append(
                _data_table(
                    ["ID", "종류", "상태", "요청", "실제", "잔차", "허용오차"],
                    rows,
                    [48 * mm, 20 * mm, 18 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm],
                    styles,
                )
            )


def _group_warning_rows(warnings: list[Any]) -> list[list[Any]]:
    """Group repeated Blender warnings while preserving one representative object ID."""

    grouped: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for raw in warnings:
        text = str(raw)
        if ": " in text:
            example, issue = text.split(": ", 1)
        else:
            example, issue = "-", text
        translated = {
            "Mesh has no active UV layer": "활성 UV 레이어 없음",
            "UV coordinates extend outside the 0..1 tile": "UV 좌표가 0..1 타일 밖으로 확장됨",
            "Mesh contains degenerate UV triangles": "퇴화한 UV 삼각형 존재",
        }.get(issue, issue)
        grouped[translated] += 1
        examples.setdefault(translated, example)
    return [[count, issue, examples[issue]] for issue, count in grouped.most_common()]


def _append_material_scene_preview(
    story: list[Any],
    images: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Append the reference and material-applied scene preview when both are available."""

    cells: list[Any] = []
    for label, key in (("Reference", "reference"), ("Material preview", "preview")):
        path = images.get(key)
        if path:
            cells.append(
                [
                    _scaled_image(path, 82 * mm, 61 * mm),
                    _paragraph(label, styles["small_center"]),
                ]
            )
    if not cells:
        return
    if len(cells) == 1:
        cells.append("")
    story.append(_paragraph("적용 장면", styles["h2"]))
    table = Table([cells], colWidths=[87 * mm, 87 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)


def _append_material_section(
    story: list[Any],
    documents: dict[str, dict[str, Any]],
    images: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Append V0.5 material contracts, runtime inspection, warnings, and swatch evidence."""

    story.append(_paragraph("재질·텍스처·셰이더 상태", styles["h1"]))
    contract = documents.get("material_contract_validation") or {}
    inspection = documents.get("material_validation") or {}
    swatches = documents.get("material_swatches") or {}
    if not contract and not inspection:
        story.append(_paragraph("재질 검사 보고서가 아직 생성되지 않았습니다.", styles["body"]))
        return
    summary = inspection.get("summary", {})
    story.append(
        _metric_table(
            [
                ("계약 검사", _status(contract.get("ok"))[0] if contract else "미실행"),
                ("재질 수", summary.get("material_count", swatches.get("material_count", 0))),
                ("검사 경고", len(inspection.get("warnings", []))),
                ("검사 오류", len(inspection.get("errors", []))),
            ],
            styles,
        )
    )
    surface_detail = documents.get("surface_detail_validation") or {}
    if surface_detail:
        story.append(_paragraph("표면 디테일 텍스처 결속", styles["h2"]))
        story.append(
            _metric_table(
                [
                    ("검증", _status(surface_detail.get("ok"))[0]),
                    ("계약 상태", surface_detail.get("material_status", "-")),
                    ("텍스처 대상", surface_detail.get("textured", 0)),
                    ("명시적 생략", surface_detail.get("omitted", 0)),
                    ("실패 검사", surface_detail.get("failed", 0)),
                ],
                styles,
            )
        )
    _append_material_scene_preview(story, images, styles)
    if contract:
        story.append(_paragraph("호스트 계약 검증", styles["h2"]))
        story.append(
            _data_table(
                ["통과", "경고", "실패", "결론"],
                [
                    [
                        contract.get("passed", 0),
                        contract.get("warnings", 0),
                        contract.get("failed", 0),
                        _status(contract.get("ok"))[0],
                    ]
                ],
                [35 * mm, 35 * mm, 35 * mm, 69 * mm],
                styles,
            )
        )
    warning_rows = _group_warning_rows(inspection.get("warnings", []))
    if warning_rows:
        story.append(_paragraph("주의가 필요한 항목", styles["h2"]))
        story.append(
            _data_table(
                ["횟수", "문제", "대표 객체"],
                warning_rows,
                [18 * mm, 100 * mm, 56 * mm],
                styles,
            )
        )
    bakes = documents.get("material_bakes")
    story.append(_paragraph("베이크 준비 상태", styles["h2"]))
    if bakes:
        story.append(
            _rich_paragraph(
                f"베이크 프로필: <b>{_text(bakes.get('profile'))}</b>, "
                f"재질 수: {_text(bakes.get('material_count'))}, "
                f"결과: {_status(bakes.get('ok'))[0]}",
                styles["body"],
            )
        )
    else:
        story.append(
            _paragraph(
                "Portable PBR 베이크는 아직 실행되지 않았습니다. "
                "스와치 승인 전에는 정상적인 상태입니다.",
                styles["body"],
            )
        )
    plan_items = {
        item.get("material_id"): item
        for item in (documents.get("material_plan") or {}).get("materials", [])
        if isinstance(item, dict)
    }
    material_rows = []
    for material in inspection.get("materials", []):
        material_id = material.get("material_id")
        plan = plan_items.get(material_id, {})
        material_rows.append(
            [
                material_id,
                plan.get("shader_family", "-"),
                plan.get("texture_strategy", material.get("source_type", "-")),
                (plan.get("mapping") or {}).get("mode", "-"),
                material.get("users", 0),
                material.get("node_count", 0),
                len(material.get("images", [])),
                len(material.get("warnings", [])),
            ]
        )
    if material_rows:
        story.append(_paragraph("재질별 런타임 검사", styles["h2"]))
        story.append(
            _data_table(
                ["Material ID", "셰이더", "텍스처", "매핑", "사용", "노드", "이미지", "경고"],
                material_rows,
                [50 * mm, 28 * mm, 25 * mm, 18 * mm, 13 * mm, 13 * mm, 14 * mm, 13 * mm],
                styles,
            )
        )
    swatch_images = images.get("material_swatches", [])
    if swatch_images:
        story.append(_paragraph("재질 스와치", styles["h1"]))
        grid: list[list[Any]] = []
        row: list[Any] = []
        for item in swatch_images:
            material_id = item["record"].get("material_id", "unknown")
            cell = [
                _scaled_image(item["path"], 48 * mm, 48 * mm),
                _paragraph(material_id, styles["small_center"]),
            ]
            row.append(cell)
            if len(row) == 3:
                grid.append(row)
                row = []
        if row:
            row.extend([""] * (3 - len(row)))
            grid.append(row)
        table = Table(grid, colWidths=[58 * mm] * 3, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(table)
        story.append(_paragraph("승인 전 체크리스트", styles["h2"]))
        story.append(
            _data_table(
                ["확인 항목", "현재 상태", "판단 기준"],
                [
                    [
                        "재질 계약",
                        _status(contract.get("ok"))[0] if contract else "미실행",
                        "Material ID, ShaderRecipe, TextureManifest 연결이 모두 유효해야 함",
                    ],
                    [
                        "Blender 런타임 검사",
                        f"오류 {len(inspection.get('errors', []))} / "
                        f"경고 {len(inspection.get('warnings', []))}",
                        "오류는 0이어야 하며 경고는 객체별 영향과 수정 필요성을 검토",
                    ],
                    [
                        "스와치 증거",
                        f"{len(swatch_images)}개 생성",
                        "색상, 거칠기, 노멀, 발광, 반복 스케일을 재질별로 육안 확인",
                    ],
                    [
                        "Portable PBR 베이크",
                        _status(bakes.get("ok"))[0] if bakes else "보류",
                        "스와치 승인 후 별도 베이크 계약과 대상 엔진 프로필로 검증",
                    ],
                ],
                [42 * mm, 38 * mm, 94 * mm],
                styles,
            )
        )


def _append_qa_images(
    story: list[Any],
    images: dict[str, Any],
    styles: dict[str, ParagraphStyle],
    *,
    include_current_preview: bool = False,
) -> None:
    """Append reference, optional accepted preview, and QA passes in a comparison grid."""

    cells: list[tuple[str, str]] = []
    if images.get("reference"):
        cells.append(("Reference", images["reference"]))
    if include_current_preview and images.get("preview"):
        cells.append(("현재 승인 프리뷰", images["preview"]))
    for item in images.get("qa_passes", []):
        kind = str(item["record"].get("kind", "pass"))
        if kind == "beauty":
            label = (
                "승인 전 QA beauty"
                if include_current_preview
                else "현재 QA 기준 프리뷰 (후보 적용 전)"
            )
        else:
            label = kind
        cells.append((label, item["path"]))
    if not cells:
        return
    story.append(_paragraph("비교 이미지", styles["h2"]))
    if include_current_preview:
        story.append(
            _paragraph(
                "QA beauty는 승인 수정 전 기준선이며, 현재 승인 프리뷰는 적용 후 결과입니다.",
                styles["body"],
            )
        )
    else:
        story.append(
            _paragraph(
                "QA beauty는 현재 SceneSpec 기준선입니다. 이 보고서의 수정 후보와 "
                "RevisionPlan은 아직 적용되지 않았습니다.",
                styles["body"],
            )
        )
    grid: list[list[Any]] = []
    row: list[Any] = []
    for label, path in cells:
        row.append(
            [
                _scaled_image(path, 53 * mm, 40 * mm),
                _paragraph(label, styles["small_center"]),
            ]
        )
        if len(row) == 3:
            grid.append(row)
            row = []
    if row:
        row.extend([""] * (3 - len(row)))
        grid.append(row)
    table = Table(grid, colWidths=[58 * mm] * 3)
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)


def _append_revision_result(
    story: list[Any],
    documents: dict[str, dict[str, Any]],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Append approved change details and convergence evidence when a QA run was applied."""

    application = documents.get("revision_application")
    convergence = documents.get("convergence")
    if application is None and convergence is None:
        return
    story.append(_paragraph("승인 수정 및 수렴 결과", styles["h2"]))
    if convergence is not None:
        story.append(
            _metric_table(
                [
                    ("적용 전", convergence.get("before_direct_score", "-")),
                    ("적용 후", convergence.get("after_direct_score", "-")),
                    ("점수 변화", convergence.get("score_delta", "-")),
                    ("수렴 상태", convergence.get("status", "-")),
                ],
                styles,
            )
        )
        reasons = convergence.get("reasons", [])
        story.append(
            _paragraph(
                "수정은 직접 레퍼런스 점수가 설정 임계값 이상 개선되고 실측 제약이 "
                f"퇴행하지 않을 때만 채택됩니다. 판정 근거: {_text(reasons)}",
                styles["body"],
            )
        )
    changes = (application or {}).get("changes", [])
    if changes:
        rows = [
            [
                item.get("target_id"),
                ".".join(str(part) for part in item.get("path", [])),
                item.get("before"),
                item.get("after"),
            ]
            for item in changes
        ]
        story.append(
            _data_table(
                ["대상", "경로", "적용 전", "적용 후"],
                rows,
                [52 * mm, 32 * mm, 45 * mm, 45 * mm],
                styles,
            )
        )


def _append_qa_finding_table(
    story: list[Any],
    title: str,
    findings: list[dict[str, Any]],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Append one evidence-specific QA finding table without mixing finding classes."""

    if not findings:
        return
    story.append(_paragraph(title, styles["h2"]))
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ordered = sorted(
        findings,
        key=lambda item: (
            severity_order.get(str(item.get("severity", "low")), 9),
            -float(item.get("confidence", 0)),
        ),
    )
    rows = [
        [
            item.get("severity"),
            item.get("issue_type"),
            ", ".join(item.get("target_ids", [])) or "global",
            item.get("description"),
            item.get("confidence"),
        ]
        for item in ordered[:30]
    ]
    story.append(
        _data_table(
            ["심각도", "유형", "대상", "설명", "신뢰도"],
            rows,
            [18 * mm, 27 * mm, 44 * mm, 67 * mm, 18 * mm],
            styles,
        )
    )


def _append_destination_handoff_section(
    story: list[Any],
    documents: dict[str, dict[str, Any]],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Append one concise V0.9 source-side handoff summary to export reports."""

    handoff = documents.get("destination_handoff_manifest") or {}
    handoff_validation = documents.get("destination_handoff_validation") or {}
    context = documents.get("destination_context") or {}
    assembly = documents.get("assembly_manifest") or {}
    material_mapping = documents.get("material_mapping") or {}
    checklist = documents.get("import_checklist") or {}
    story.append(_paragraph("V0.9 Codex Destination Handoff", styles["h2"]))
    if not handoff:
        story.append(
            _paragraph(
                "No valid destination handoff is available for the selected package. "
                "The portable package remains usable, but destination reconstruction must be "
                "planned manually and no engine parity is implied.",
                styles["body"],
            )
        )
        return

    lod_context = context.get("lod_and_collider") or {}
    story.append(
        _metric_table(
            [
                (
                    "Handoff status",
                    _status(
                        handoff_validation.get(
                            "ok", handoff_validation.get("status")
                        )
                    )[0],
                ),
                ("Assembly nodes", len(assembly.get("nodes", []))),
                ("Materials", len(material_mapping.get("materials", []))),
                ("Checklist gates", len(checklist.get("items", []))),
            ],
            styles,
        )
    )
    story.append(
        _data_table(
            ["Field", "Value"],
            [
                ["Handoff ID", handoff.get("handoff_id")],
                ["Profile / package", [handoff.get("profile_id"), handoff.get("package_id")]],
                ["Package manifest SHA-256", handoff.get("package_manifest", {}).get("sha256")],
                ["Primary model", handoff.get("primary_model", {}).get("path")],
                ["LOD present", lod_context.get("lod_present")],
                ["LOD levels", lod_context.get("lod_levels")],
                [
                    "Collider present / count",
                    [
                        lod_context.get("collider_present"),
                        lod_context.get("collider_count"),
                    ],
                ],
                [
                    "Known format losses",
                    context.get("known_format_losses") or "None declared",
                ],
                ["Unverified items", context.get("unverified_items")],
                ["Runtime parity", "not verified"],
            ],
            [55 * mm, 119 * mm],
            styles,
        )
    )
    material_rows = []
    for material in material_mapping.get("materials", []):
        if not isinstance(material, dict):
            continue
        channels = [
            item.get("channel")
            for item in material.get("channels", [])
            if isinstance(item, dict) and item.get("status") != "unavailable"
        ]
        material_rows.append(
            [
                material.get("material_id"),
                channels or "None",
                material.get("blender_master_shader_baked"),
                material.get("known_losses") or "None",
            ]
        )
    if material_rows:
        story.append(
            _data_table(
                ["Material ID", "Portable channels", "Master baked", "Known losses"],
                material_rows,
                [42 * mm, 58 * mm, 24 * mm, 50 * mm],
                styles,
            )
        )


def _append_export_section(
    story: list[Any],
    documents: dict[str, dict[str, Any]],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Append V0.7 package evidence and an optional V0.9 destination handoff."""

    story.append(_paragraph("V0.7 이식형 게임 자산 패키지", styles["h1"]))
    plan = documents.get("optimization_plan") or {}
    review = documents.get("optimization_review") or {}
    approval = documents.get("optimization_approval") or {}
    preflight = documents.get("mesh_preflight_report") or {}
    cost = documents.get("asset_cost_report") or {}
    conversion = documents.get("material_conversion_manifest") or {}
    package = documents.get("package_manifest") or {}
    roundtrip = documents.get("roundtrip_validation") or {}
    handoff = documents.get("destination_handoff_manifest") or {}
    if not any(
        (plan, review, approval, preflight, cost, conversion, package, roundtrip, handoff)
    ):
        story.append(
            _paragraph(
                "V0.7 최적화 또는 내보내기 JSON이 아직 없습니다. 이 보고서는 통과 상태를 "
                "추정하지 않으며 해당 증거를 사용할 수 없음으로 표시합니다.",
                styles["body"],
            )
        )
        return

    story.append(
        _metric_table(
            [
                ("최적화 계획", _status(plan.get("status"))[0] if plan else "미생성"),
                (
                    "메시 사전 검사",
                    _status(preflight.get("ok", preflight.get("status")))[0]
                    if preflight
                    else "미생성",
                ),
                ("패키지", _status(package.get("status"))[0] if package else "미생성"),
                (
                    "재임포트 검증",
                    _status(roundtrip.get("ok", roundtrip.get("status")))[0]
                    if roundtrip
                    else "미생성",
                ),
            ],
            styles,
        )
    )

    if review:
        story.append(_paragraph("Pre-optimization LOD and Collider Review", styles["h2"]))
        lod_review = review.get("lod") or {}
        collision_review = review.get("collision") or {}
        source_quality = review.get("source_quality") or {}
        level_summary = [
            {
                "level": item.get("level"),
                "ratio": item.get("target_triangle_ratio"),
                "triangles": item.get("estimated_triangle_ceiling"),
            }
            for item in lod_review.get("levels", [])
            if isinstance(item, dict)
        ]
        story.append(
            _data_table(
                ["Field", "Reviewed value"],
                [
                    ["Run ID", review.get("run_id")],
                    ["Plan SHA-256", review.get("plan_sha256")],
                    ["Decision required", review.get("decision_required")],
                    ["LOD enabled", lod_review.get("enabled")],
                    ["LOD levels", level_summary or "None"],
                    ["LOD source objects", lod_review.get("source_object_count")],
                    ["Collision strategy", collision_review.get("strategy")],
                    [
                        "Estimated colliders",
                        collision_review.get("estimated_collider_count"),
                    ],
                    [
                        "Collider triangle ceiling",
                        collision_review.get("maximum_triangle_ceiling"),
                    ],
                    ["Consolidation", review.get("consolidation_mode")],
                    [
                        "Source quality status",
                        source_quality.get("quality_status", "not supplied"),
                    ],
                    [
                        "Primary high findings",
                        source_quality.get("primary_high_findings") or "None",
                    ],
                    [
                        "Decorative warnings",
                        source_quality.get("decorative_warnings") or "None",
                    ],
                    [
                        "Standard revision recommended",
                        source_quality.get("standard_workflow_recommended"),
                    ],
                    ["Approval recorded", bool(approval)],
                    ["Approval consumed", approval.get("used") if approval else None],
                ],
                [55 * mm, 119 * mm],
                styles,
            )
        )
        for warning in review.get("warnings", []):
            story.append(_paragraph(f"Warning: {warning}", styles["small"]))

    profile = documents.get("asset_profile") or {}
    if profile or plan:
        story.append(_paragraph("대상 프로필과 원본 보존", styles["h2"]))
        source = plan.get("source") or package.get("source") or {}
        story.append(
            _data_table(
                ["항목", "값"],
                [
                    ["Profile ID", profile.get("profile_id", plan.get("profile_id"))],
                    ["Asset kind", profile.get("asset_kind")],
                    ["Primary format", profile.get("primary_format")],
                    ["Units", profile.get("units")],
                    ["Up / Forward", [profile.get("up_axis"), profile.get("forward_axis")]],
                    ["Plan ID", plan.get("plan_id")],
                    ["Run ID", package.get("run_id", plan.get("run_id"))],
                    ["Build fingerprint", source.get("build_fingerprint")],
                    [
                        "Canonical unchanged",
                        package.get(
                            "canonical_unchanged",
                            preflight.get("canonical_unchanged"),
                        ),
                    ],
                ],
                [55 * mm, 119 * mm],
                styles,
            )
        )

    if conversion:
        story.append(_paragraph("Portable material conversion", styles["h2"]))
        outputs = [
            item for item in conversion.get("outputs", []) if isinstance(item, dict)
        ]
        entries = [
            item for item in conversion.get("entries", []) if isinstance(item, dict)
        ]
        losses = [
            str(loss)
            for entry in entries
            for loss in entry.get("losses", [])
        ]
        warnings = [
            str(warning)
            for entry in entries
            for warning in entry.get("warnings", [])
        ]
        story.append(
            _metric_table(
                [
                    ("Converted", len(conversion.get("converted_material_ids", []))),
                    ("Required", len(conversion.get("required_material_ids", []))),
                    ("Atlas tiles", len(conversion.get("tiles", []))),
                    ("Channels", len(outputs)),
                ],
                styles,
            )
        )
        atlas = conversion.get("atlas_policy") or {}
        story.append(
            _data_table(
                ["Field", "Value"],
                [
                    ["Conversion ID", conversion.get("manifest_id")],
                    ["Status", conversion.get("status")],
                    ["Atlas layout", atlas.get("layout")],
                    ["Atlas resolution", atlas.get("resolution")],
                    ["Atlas UV", atlas.get("uv_set")],
                    ["Channels", [item.get("channel") for item in outputs]],
                    [
                        "Portable blend",
                        (conversion.get("portable_blend") or {}).get("path"),
                    ],
                    ["Canonical unchanged", conversion.get("canonical_unchanged")],
                    ["Declared losses", sorted(set(losses)) or "None"],
                    ["Warnings", sorted(set(warnings)) or "None"],
                ],
                [55 * mm, 119 * mm],
                styles,
            )
        )

    if preflight:
        story.append(_paragraph("메시 사전 검사", styles["h2"]))
        story.append(
            _metric_table(
                [
                    ("통과", preflight.get("passed", 0)),
                    ("경고", preflight.get("warnings", 0)),
                    ("실패", preflight.get("failed", 0)),
                    ("메시 그룹", len(preflight.get("meshes", []))),
                ],
                styles,
            )
        )
        failed_checks = [
            item
            for item in preflight.get("checks", [])
            if isinstance(item, dict) and item.get("status") != "passed"
        ]
        if failed_checks:
            rows = [
                [
                    item.get("id"),
                    item.get("target_id"),
                    item.get("category"),
                    item.get("status"),
                    item.get("message"),
                ]
                for item in failed_checks
            ]
            story.append(
                _data_table(
                    ["Check", "Target", "Category", "Status", "Message"],
                    rows,
                    [35 * mm, 38 * mm, 24 * mm, 18 * mm, 59 * mm],
                    styles,
                )
            )

    if cost:
        story.append(_paragraph("V0.7.3 Static Asset Cost Optimization", styles["h2"]))
        before = cost.get("before") or {}
        after = cost.get("after") or {}
        story.append(
            _metric_table(
                [
                    (
                        "LOD0 objects",
                        f"{before.get('lod0_render_objects', 0)} → "
                        f"{after.get('lod0_render_objects', 0)}",
                    ),
                    (
                        "Draw-call proxy",
                        f"{before.get('lod0_estimated_draw_calls', 0)} → "
                        f"{after.get('lod0_estimated_draw_calls', 0)}",
                    ),
                    (
                        "Material slots",
                        f"{before.get('lod0_material_slots', 0)} → "
                        f"{after.get('lod0_material_slots', 0)}",
                    ),
                    (
                        "Overlap candidates",
                        f"{before.get('overlap_candidates', 0)} → "
                        f"{after.get('overlap_candidates', 0)}",
                    ),
                ],
                styles,
            )
        )
        story.append(
            _data_table(
                ["Evidence", "Count"],
                [
                    ["Consolidation batches", len(cost.get("consolidation_batches", []))],
                    ["Cleanup records", len(cost.get("cleanup_records", []))],
                    ["Exact instance groups", len(cost.get("instance_groups", []))],
                    ["Budget checks", len(cost.get("budgets", []))],
                    ["Quality", cost.get("quality_status")],
                ],
                [80 * mm, 94 * mm],
                styles,
            )
        )
        budget_rows = [
            [
                item.get("metric"),
                item.get("actual"),
                item.get("maximum"),
                item.get("status"),
                item.get("message"),
            ]
            for item in cost.get("budgets", [])
            if isinstance(item, dict)
        ]
        if budget_rows:
            story.append(
                _data_table(
                    ["Metric", "Actual", "Maximum", "Status", "Message"],
                    budget_rows,
                    [42 * mm, 20 * mm, 22 * mm, 20 * mm, 70 * mm],
                    styles,
                )
            )

    lod = documents.get("lod_manifest") or {}
    if lod:
        story.append(_paragraph("LOD 파생 메시", styles["h2"]))
        entries = [item for item in lod.get("entries", []) if isinstance(item, dict)]
        rows = [
            [
                item.get("target_id"),
                item.get("level"),
                item.get("source_triangle_count"),
                item.get("triangle_count"),
                item.get("triangle_ratio"),
                item.get("silhouette_iou"),
            ]
            for item in entries
        ]
        if rows:
            story.append(
                _data_table(
                    ["Target", "LOD", "Source tris", "Tris", "Ratio", "Silhouette IoU"],
                    rows,
                    [53 * mm, 14 * mm, 27 * mm, 25 * mm, 24 * mm, 31 * mm],
                    styles,
                )
            )
        else:
            story.append(_paragraph("LOD 결과가 아직 생성되지 않았습니다.", styles["body"]))

    collision = documents.get("collision_manifest") or {}
    if collision:
        story.append(_paragraph("Collider", styles["h2"]))
        collision_rows = [
            [
                item.get("collider_id"),
                item.get("target_id"),
                item.get("strategy"),
                item.get("hull_count"),
                item.get("triangle_count"),
                item.get("dimensions"),
            ]
            for item in collision.get("entries", [])
            if isinstance(item, dict)
        ]
        if collision_rows:
            story.append(
                _data_table(
                    ["Collider", "Target", "Strategy", "Hulls", "Tris", "Dimensions"],
                    collision_rows,
                    [38 * mm, 43 * mm, 27 * mm, 16 * mm, 17 * mm, 33 * mm],
                    styles,
                )
            )
        else:
            story.append(
                _paragraph(
                    f"Collider strategy: {_text(collision.get('strategy', 'none'))}. "
                    "생성된 collider 항목이 없습니다.",
                    styles["body"],
                )
            )

    uv = documents.get("uv_manifest") or {}
    if uv:
        story.append(_paragraph("UV와 Texel Density", styles["h2"]))
        uv_rows = [
            [
                item.get("target_id"),
                item.get("uv_set"),
                item.get("purpose"),
                item.get("generated"),
                item.get("overlap_fraction"),
                item.get("degenerate_face_count"),
                item.get("texel_density_px_m"),
                item.get("padding_px"),
            ]
            for item in uv.get("records", [])
            if isinstance(item, dict)
        ]
        if uv_rows:
            story.append(
                _data_table(
                    [
                        "Target",
                        "UV",
                        "Purpose",
                        "Generated",
                        "Overlap",
                        "Degenerate",
                        "px/m",
                        "Pad",
                    ],
                    uv_rows,
                    [40 * mm, 23 * mm, 23 * mm, 19 * mm, 20 * mm, 22 * mm, 18 * mm, 9 * mm],
                    styles,
                )
            )

    texture_pack = documents.get("texture_pack_manifest") or {}
    if texture_pack:
        story.append(_paragraph("Portable PBR 텍스처 패킹", styles["h2"]))
        textures = [
            item for item in texture_pack.get("textures", []) if isinstance(item, dict)
        ]
        story.append(
            _data_table(
                ["항목", "값"],
                [
                    ["Manifest ID", texture_pack.get("manifest_id")],
                    ["Profile", texture_pack.get("profile_id")],
                    ["Status", texture_pack.get("status")],
                    ["Raw channels preserved", texture_pack.get("raw_channels_preserved")],
                    ["Packing required", texture_pack.get("packing_required")],
                    ["Texture outputs", len(textures)],
                ],
                [55 * mm, 119 * mm],
                styles,
            )
        )
        if textures:
            texture_rows = [
                [
                    item.get("texture_id"),
                    item.get("material_ids"),
                    item.get("packing"),
                    (item.get("output") or {}).get("path"),
                    item.get("color_space"),
                    f"{_text(item.get('width'))} x {_text(item.get('height'))}",
                    [
                        f"{mapping.get('output_channel')}={mapping.get('source_channel')}"
                        for mapping in item.get("mappings", [])
                        if isinstance(mapping, dict)
                    ],
                ]
                for item in textures
            ]
            story.append(
                _data_table(
                    ["Texture", "Materials", "Packing", "Output", "Space", "Size", "Mapping"],
                    texture_rows,
                    [25 * mm, 25 * mm, 18 * mm, 38 * mm, 18 * mm, 16 * mm, 34 * mm],
                    styles,
                )
            )

    if package:
        story.append(_paragraph("불변 패키지", styles["h2"]))
        files = [item for item in package.get("files", []) if isinstance(item, dict)]
        story.append(
            _metric_table(
                [
                    ("Files", len(files)),
                    ("Semantic IDs", len(package.get("semantic_ids", []))),
                    ("Material IDs", len(package.get("material_ids", []))),
                    ("Losses", len(package.get("known_losses", []))),
                ],
                styles,
            )
        )
        story.append(
            _data_table(
                ["항목", "값"],
                [
                    ["Package ID", package.get("package_id")],
                    ["Profile", package.get("profile_id")],
                    ["Primary file ID", package.get("primary_file_id")],
                    ["Package root", package.get("package_root")],
                    ["Absolute paths", package.get("absolute_path_count")],
                    ["Missing dependencies", package.get("missing_dependency_count")],
                    ["Canonical unchanged", package.get("canonical_unchanged")],
                ],
                [55 * mm, 119 * mm],
                styles,
            )
        )
        if files:
            file_rows = [
                [
                    item.get("id"),
                    item.get("kind"),
                    item.get("path"),
                    item.get("byte_size", item.get("size_bytes")),
                    str(item.get("sha256", ""))[:16],
                ]
                for item in files
            ]
            story.append(
                _data_table(
                    ["ID", "Kind", "Job-relative path", "Bytes", "SHA-256"],
                    file_rows,
                    [31 * mm, 28 * mm, 71 * mm, 19 * mm, 25 * mm],
                    styles,
                )
            )

    if roundtrip:
        if package:
            story.append(PageBreak())
        story.append(_paragraph("Clean reimport round-trip", styles["h2"]))
        checks = [item for item in roundtrip.get("checks", []) if isinstance(item, dict)]
        bounds = roundtrip.get("bounds") or {}
        story.append(
            _metric_table(
                [
                    ("Passed", roundtrip.get("passed", 0)),
                    ("Warnings", roundtrip.get("warnings", 0)),
                    ("Failed", roundtrip.get("failed", 0)),
                    ("Result", _status(roundtrip.get("ok", roundtrip.get("status")))[0]),
                ],
                styles,
            )
        )
        story.append(
            _data_table(
                ["항목", "값"],
                [
                    ["Validation ID", roundtrip.get("validation_id")],
                    ["Semantic ID coverage", roundtrip.get("semantic_id_coverage")],
                    ["Material ID coverage", roundtrip.get("material_id_coverage")],
                    [
                        "Expected semantic IDs",
                        _bounded_table_value(roundtrip.get("expected_semantic_ids")),
                    ],
                    [
                        "Observed semantic IDs",
                        _bounded_table_value(roundtrip.get("observed_semantic_ids")),
                    ],
                    [
                        "Expected material IDs",
                        _bounded_table_value(roundtrip.get("expected_material_ids")),
                    ],
                    [
                        "Observed material IDs",
                        _bounded_table_value(roundtrip.get("observed_material_ids")),
                    ],
                    ["Bounds max error (m)", bounds.get("max_abs_error_m")],
                    ["Bounds tolerance (m)", bounds.get("tolerance_m")],
                    ["Bounds passed", bounds.get("passed")],
                ],
                [55 * mm, 119 * mm],
                styles,
            )
        )
        failed_checks = [item for item in checks if item.get("status") != "passed"]
        if failed_checks:
            story.append(
                _paragraph(
                    "Long ID lists and messages are summarized in this PDF; "
                    "the canonical round-trip JSON remains authoritative.",
                    styles["small"],
                )
            )
            story.append(
                _data_table(
                    ["Check", "Category", "Status", "Message"],
                    [
                        [
                            item.get("id"),
                            item.get("category"),
                            item.get("status"),
                            _bounded_table_value(item.get("message")),
                        ]
                        for item in failed_checks
                    ],
                    [42 * mm, 32 * mm, 22 * mm, 78 * mm],
                    styles,
                )
            )

    _append_destination_handoff_section(story, documents, styles)


def _append_interior_qa_section(
    story: list[Any],
    documents: dict[str, dict[str, Any]],
    images: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Append separately approved multi-view interior evidence to the QA report."""

    report = documents.get("interior_qa_report")
    if report is None:
        return
    plan = documents.get("interior_qa_plan") or {}
    manifest = documents.get("interior_qa_render_manifest") or {}
    candidates = documents.get("interior_qa_revision_candidates") or {}
    story.append(PageBreak())
    story.append(_paragraph("실내 다각도 QA", styles["h1"]))
    story.append(
        _metric_table(
            [
                ("상태", report.get("status", "-")),
                ("검사 뷰", len(manifest.get("views", []))),
                (
                    "Semantic visibility",
                    f"{float(report.get('semantic_visibility_fraction', 0.0)):.3f}",
                ),
                ("수정 후보", len(candidates.get("candidates", []))),
            ],
            styles,
        )
    )
    story.append(
        _paragraph(
            "Semantic visibility는 승인된 실내 semantic ID가 Object ID 패스에서 "
            "관찰된 비율이며 완성도 백분율이 아닙니다. 실내 전용 레퍼런스 뷰가 "
            "연결되지 않은 실행에서는 레퍼런스 유사도 점수를 만들지 않습니다.",
            styles["body"],
        )
    )
    story.append(
        _data_table(
            ["항목", "값"],
            [
                ["Run ID", report.get("run_id", "-")],
                ["검사 프로필", plan.get("profile", "-")],
                ["Reference 비교", report.get("reference_comparison_status", "-")],
                ["비교 메모", report.get("reference_comparison_note", "-")],
                ["대상 semantic ID 수", len(report.get("target_ids", []))],
                ["미관찰 ID 수", len(report.get("unseen_target_ids", []))],
            ],
            [52 * mm, 122 * mm],
            styles,
        )
    )
    coverage_rows = [
        [
            item.get("level_id") or "-",
            item.get("space_id") or "-",
            len(item.get("view_ids", [])),
            f"{float(item.get('semantic_visibility_fraction', 0.0)):.3f}",
            _bounded_table_value(item.get("unseen_target_ids", [])),
        ]
        for item in report.get("space_coverage", [])
    ]
    if coverage_rows:
        story.append(_paragraph("공간별 관찰 범위", styles["h2"]))
        story.append(
            _data_table(
                ["Level", "Space", "Views", "Visibility", "Unseen IDs"],
                coverage_rows,
                [28 * mm, 34 * mm, 18 * mm, 26 * mm, 68 * mm],
                styles,
            )
        )
    contact_sheets = images.get("interior_qa_contact_sheets", [])
    if contact_sheets:
        story.append(_paragraph("다각도 Contact Sheet", styles["h2"]))
        cells = [
            [
                _scaled_image(item["path"], 53 * mm, 40 * mm),
                _paragraph(item["kind"], styles["small_center"]),
            ]
            for item in contact_sheets
        ]
        table = Table([cells], colWidths=[58 * mm] * len(cells), hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(table)
    finding_rows = [
        [
            item.get("category", "-"),
            item.get("severity", "-"),
            _bounded_table_value(item.get("target_ids", [])),
            _bounded_table_value(item.get("description", "-")),
        ]
        for item in report.get("findings", [])
    ]
    if finding_rows:
        story.append(_paragraph("실내 QA 발견 사항", styles["h2"]))
        story.append(
            _data_table(
                ["Category", "Severity", "Targets", "Description"],
                finding_rows,
                [27 * mm, 24 * mm, 54 * mm, 69 * mm],
                styles,
            )
        )


def _append_qa_section(
    story: list[Any],
    documents: dict[str, dict[str, Any]],
    images: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Append fixed-camera direct scores, visual evidence, findings, and revision candidates."""

    story.append(_paragraph("레퍼런스 시각 QA", styles["h1"]))
    report = documents.get("visual_qa_report")
    if report is None:
        story.append(_paragraph("시각 QA 보고서가 아직 생성되지 않았습니다.", styles["body"]))
        return
    metrics = report.get("direct_metrics", {})
    bbox = metrics.get("global_bbox", {})
    story.append(
        _metric_table(
            [
                ("직접 점수", metrics.get("overall_direct_score", "-")),
                ("Silhouette IoU", metrics.get("silhouette_iou", "-")),
                ("중심 오차", bbox.get("center_error_norm", "-")),
                ("크기 오차", bbox.get("size_error_norm", "-")),
            ],
            styles,
        )
    )
    surface_detail = report.get("surface_detail_summary")
    if isinstance(surface_detail, dict):
        story.append(_paragraph("표면 디테일 전달 상태", styles["h2"]))
        story.append(
            _metric_table(
                [
                    ("계약 상태", surface_detail.get("contract_status", "-")),
                    ("선언된 디테일", surface_detail.get("declared_details", 0)),
                    (
                        "텍스처 결속 디테일",
                        surface_detail.get("texture_bound_details", 0),
                    ),
                    ("명시적 생략", surface_detail.get("omitted_details", 0)),
                    ("실패 검사", surface_detail.get("failed_checks", 0)),
                ],
                styles,
            )
        )
        story.append(
            _paragraph(
                "이 값은 TextureManifest 결속 상태입니다. 작은 무늬의 픽셀 유사도나 "
                "전체 모델 완성도 점수가 아니며, 표면 디테일은 geometry 후보에서 "
                "제외됩니다.",
                styles["body"],
            )
        )
    story.append(
        _paragraph(
            "직접 점수는 고정 카메라에서 reference mask와 Blender render를 비교한 지표이며, "
            "구조 검증이나 실측 정확도를 대체하지 않습니다.",
            styles["body"],
        )
    )
    _append_qa_images(
        story,
        images,
        styles,
        include_current_preview=documents.get("convergence") is not None,
    )
    findings = report.get("findings", [])
    group_suggestions = [
        item
        for item in findings
        if str(item.get("id", "")).startswith("direct.group_position.")
    ]
    direct_findings = [
        item
        for item in findings
        if (
            not str(item.get("id", "")).startswith("direct.group_position.")
            and "direct_reference" in set(item.get("evidence_sources", []))
        )
    ]
    generated_target_advisories = [
        item
        for item in findings
        if (
            not str(item.get("id", "")).startswith("direct.group_position.")
            and set(item.get("evidence_sources", [])) == {"generated_target"}
        )
    ]
    other_findings = [
        item
        for item in findings
        if (
            item not in group_suggestions
            and item not in direct_findings
            and item not in generated_target_advisories
        )
    ]
    other_summary = (
        f" 기타 근거 발견: <b>{len(other_findings)}</b>개." if other_findings else ""
    )
    story.append(
        _rich_paragraph(
            f"직접 QA 발견: <b>{len(direct_findings)}</b>개. "
            f"생성 타깃 보조 발견: <b>{len(generated_target_advisories)}</b>개. "
            f"일관 그룹 이동 제안: <b>{len(group_suggestions)}</b>개 묶음. "
            f"그룹 제안은 품질 회귀가 아니라 안전한 수정 후보 묶음입니다.{other_summary}",
            styles["body"],
        )
    )
    _append_qa_finding_table(story, "직접 레퍼런스 발견", direct_findings, styles)
    _append_qa_finding_table(
        story,
        "생성 타깃 보조 발견",
        generated_target_advisories,
        styles,
    )
    _append_qa_finding_table(story, "일관 그룹 이동 제안", group_suggestions, styles)
    _append_qa_finding_table(story, "기타 근거 발견", other_findings, styles)
    candidates = (documents.get("revision_candidates") or {}).get("candidates", [])
    group_member_candidates = [
        item
        for item in candidates
        if str(item.get("finding_id", "")).startswith("direct.group_position.")
    ]
    ordinary_candidates = [
        item
        for item in candidates
        if not str(item.get("finding_id", "")).startswith("direct.group_position.")
    ]
    group_bundle_count = len(
        {str(item.get("finding_id")) for item in group_member_candidates}
    )
    candidate_summary = (
        f"일반 후보: <b>{len(ordinary_candidates)}</b>개. "
        f"그룹 이동 묶음: <b>{group_bundle_count}</b>개. "
        f"그룹 member 연산: <b>{len(group_member_candidates)}</b>개."
    )
    story.append(_paragraph("수정 후보", styles["h2"]))
    application = documents.get("revision_application")
    if application is not None:
        story.append(
            _rich_paragraph(
                f"{candidate_summary} 승인 적용 원자 연산: "
                f"<b>{len(application.get('approved_candidate_ids', []))}</b>개. "
                f"현재 상태: <b>{escape(str(application.get('status', '-')))}</b>.",
                styles["body"],
            )
        )
    else:
        story.append(
            _rich_paragraph(
                f"{candidate_summary} PDF는 승인 문서가 아니며, 실제 적용에는 "
                "hash-bound 단일 사용 승인이 별도로 필요합니다.",
                styles["body"],
            )
        )
    _append_revision_result(story, documents, styles)


def _append_source_appendix(
    story: list[Any],
    payload: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Append redacted source paths and short hashes for reproducible report review."""

    if payload["scope"] == "material":
        story.append(PageBreak())
    story.append(_paragraph("부록. 보고서 출처", styles["h1"]))
    story.append(
        _paragraph(
            "아래 JSON과 이미지가 PDF의 근거입니다. PDF는 보기 편한 파생 산출물이며, "
            "기계 검증과 수정 보호에는 원본 JSON의 전체 SHA-256을 사용합니다.",
            styles["body"],
        )
    )
    rows = [
        [source.kind, source.path, f"{source.sha256[:16]}…", source.size_bytes]
        for source in payload["sources"]
    ]
    story.append(
        _data_table(
            ["종류", "Job-relative 경로", "SHA-256", "Bytes"],
            rows,
            [38 * mm, 88 * mm, 33 * mm, 15 * mm],
            styles,
        )
    )


def _page_callback(
    fonts: dict[str, str],
    job_id: str,
    scope: str,
) -> Callable[[Canvas, SimpleDocTemplate], None]:
    """Create a header/footer callback with stable job, scope, and page numbering."""

    def draw_page(canvas: Canvas, document: SimpleDocTemplate) -> None:
        """Draw non-overlapping page furniture outside the report content frame."""

        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(18 * mm, height - 14 * mm, width - 18 * mm, height - 14 * mm)
        canvas.setFont(fonts["regular"], 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, height - 11 * mm, f"BlenderAssetGenerator · {job_id}")
        canvas.drawRightString(width - 18 * mm, height - 11 * mm, _scope_title(scope))
        canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
        canvas.drawString(18 * mm, 9 * mm, "Machine JSON remains the canonical validation source")
        canvas.drawRightString(width - 18 * mm, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    return draw_page


def render_job_pdf(payload: dict[str, Any], output: Path) -> dict[str, str]:
    """Render one polished A4 PDF from prevalidated job-local report evidence."""

    fonts = _register_report_fonts()
    styles = _report_styles(fonts)
    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=f"BlenderAssetGenerator {_scope_title(payload['scope'])}",
        author="Codex Blender Modeler",
        subject=f"{payload['job_id']} {payload['scope']} report",
    )
    story: list[Any] = []
    _append_cover(story, payload, styles)
    documents = payload["documents"]
    images = payload["images"]
    if payload["scope"] in {"build", "full"}:
        _append_build_section(story, documents, styles)
    if payload["scope"] in {"material", "full"}:
        _append_material_section(story, documents, images, styles)
    if payload["scope"] in {"qa", "full"}:
        if (
            "visual_qa_report" in documents
            or "interior_qa_report" not in documents
        ):
            _append_qa_section(story, documents, images, styles)
        _append_interior_qa_section(story, documents, images, styles)
    if payload["scope"] in {"export", "full"}:
        _append_export_section(story, documents, styles)
    _append_source_appendix(story, payload, styles)
    callback = _page_callback(fonts, payload["job_id"], payload["scope"])
    document.build(story, onFirstPage=callback, onLaterPages=callback)
    return {"font": fonts["source"]}
