import os
from pathlib import Path
from typing import Iterable, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)


DATASET_LAYOUTS = {
    'table': {
        'columns': ['rank', 'club', 'played', 'wins', 'draws',
                    'losses', 'goals', 'diff', 'points'],
        'headers': ['#', 'Club', 'P', 'W', 'D', 'L', 'Goals', '+/-', 'Pts'],
        'pagesize': landscape(A4),
        'font_size': 9,
        'header_font_size': 10,
        'row_heights': 18,
        'col_widths': [12 * mm, 62 * mm, 14 * mm, 14 * mm, 14 * mm,
                       14 * mm, 26 * mm, 16 * mm, 16 * mm],
    },
    'teams': {
        'columns': ['name', 'rank', 'played', 'wins', 'draws',
                    'losses', 'goals', 'diff', 'points'],
        'headers': ['Club', '#', 'P', 'W', 'D', 'L', 'Goals', '+/-', 'Pts'],
        'pagesize': landscape(A4),
        'font_size': 9,
        'header_font_size': 10,
        'row_heights': 18,
        'col_widths': [70 * mm, 12 * mm, 14 * mm, 14 * mm, 14 * mm,
                       14 * mm, 26 * mm, 16 * mm, 16 * mm],
    },
    'stats': {
        'columns': ['player_name', 'number', 'position', 'club', 'played',
                    'goals', 'assists', 'yellow_cards', 'second_yellows',
                    'red_cards', 'conceded', 'clean_sheets', 'minutes'],
        'headers': ['Player', '#', 'Position', 'Club', 'P',
                    'G', 'A', 'YC', '2YC', 'RC', 'GA', 'CS', 'Min'],
        'pagesize': landscape(A3),
        'font_size': 6.5,
        'header_font_size': 7,
        'row_heights': 14,
        'col_widths': [52 * mm, 12 * mm, 34 * mm, 34 * mm, 11 * mm,
                       11 * mm, 11 * mm, 12 * mm, 12 * mm, 11 * mm,
                       12 * mm, 12 * mm, 18 * mm],
    },
}

FONT_REGULAR_NAME = 'SnapshotSans'
FONT_BOLD_NAME = 'SnapshotSansBold'
FONT_CANDIDATES = [
    (
        '/System/Library/Fonts/Supplemental/Times New Roman.ttf',
        '/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf',
    ),
    (
        '/System/Library/Fonts/Supplemental/Georgia.ttf',
        '/System/Library/Fonts/Supplemental/Georgia Bold.ttf',
    ),
    (
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        None,
    ),
    (
        '/Library/Fonts/Arial Unicode.ttf',
        None,
    ),
    (
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    ),
    (
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf',
    ),
]
PDF_COMPAT_REPLACEMENTS = str.maketrans({
    'Ș': 'Ş',
    'ș': 'ş',
    'Ț': 'Ţ',
    'ț': 'ţ',
})


def render_pdf(path: Path, dataset_type: str, league_label: str,
               season: int, rows: Iterable[dict]) -> None:
    layout = DATASET_LAYOUTS[dataset_type]
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    regular_font, bold_font = ensure_snapshot_fonts()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'SnapshotTitle',
        parent=styles['Title'],
        fontName=bold_font,
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#102542'),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        'SnapshotSubtitle',
        parent=styles['Normal'],
        fontName=regular_font,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#4f5d75'),
        spaceAfter=10,
    )

    table_data: List[List[str]] = [layout['headers']]
    for row in rows:
        table_data.append([
            stringify_cell(row.get(column, ''))
            for column in layout['columns']
        ])

    title = f'{league_label} {dataset_type.title()} Snapshot'
    subtitle = (
        f'Season {season}/{str(season + 1)[-2:]} '
        f'| Generated from the latest local refresh'
    )

    document = SimpleDocTemplate(
        str(path),
        pagesize=layout['pagesize'],
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    table = Table(table_data,
                  repeatRows=1,
                  colWidths=layout['col_widths'],
                  rowHeights=layout['row_heights'])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102542')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), bold_font),
        ('FONTSIZE', (0, 0), (-1, 0), layout['header_font_size']),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8fafc')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
         [colors.white, colors.HexColor('#eef3f8')]),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 1), (-1, -1), regular_font),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('FONTSIZE', (0, 1), (-1, -1), layout['font_size']),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))

    document.build([
        Paragraph(title, title_style),
        Paragraph(subtitle, subtitle_style),
        Spacer(1, 4),
        table,
    ])


def stringify_cell(value) -> str:
    if value is None:
        return ''
    return str(value).translate(PDF_COMPAT_REPLACEMENTS)


def ensure_snapshot_fonts():
    if FONT_REGULAR_NAME in pdfmetrics.getRegisteredFontNames():
        bold_name = FONT_BOLD_NAME
        if bold_name not in pdfmetrics.getRegisteredFontNames():
            bold_name = FONT_REGULAR_NAME
        return FONT_REGULAR_NAME, bold_name

    font_override = os.getenv('PDF_FONT_PATH')
    if font_override and Path(font_override).exists():
        pdfmetrics.registerFont(TTFont(FONT_REGULAR_NAME, font_override))
        pdfmetrics.registerFont(TTFont(FONT_BOLD_NAME, font_override))
        return FONT_REGULAR_NAME, FONT_BOLD_NAME

    for regular_path, bold_path in FONT_CANDIDATES:
        regular = Path(regular_path)
        bold = Path(bold_path) if bold_path else None
        if not regular.exists():
            continue

        pdfmetrics.registerFont(TTFont(FONT_REGULAR_NAME, str(regular)))
        if bold and bold.exists():
            pdfmetrics.registerFont(TTFont(FONT_BOLD_NAME, str(bold)))
            return FONT_REGULAR_NAME, FONT_BOLD_NAME

        pdfmetrics.registerFont(TTFont(FONT_BOLD_NAME, str(regular)))
        return FONT_REGULAR_NAME, FONT_BOLD_NAME

    return 'Helvetica', 'Helvetica-Bold'
