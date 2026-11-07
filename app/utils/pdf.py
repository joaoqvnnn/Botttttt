from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


TZ = ZoneInfo("America/Sao_Paulo")


CATEGORY_LABEL = {
    "purchase": "Compra",
    "recharge": "Recarga",
    "bonus": "Bônus",
    "gift": "Gift Card",
    "refund": "Reembolso",
    "affiliate": "Afiliados",
    "withdraw": "Saque",
}


def _fmt_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ).strftime("%d/%m/%Y %H:%M")


def _fmt_money(value) -> str:
    return f"R$ {float(value):.2f}".replace(".", ",")


def generate_history_pdf(
    user_id: int,
    telegram_id: int,
    username: str | None,
    first_name: str,
    balance: float,
    transactions: list,
) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="BELLAMY | Histórico",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleBellamy",
        parent=styles["Title"],
        fontSize=18,
        textColor=colors.HexColor("#1F2937"),
        alignment=1,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleBellamy",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#6B7280"),
        alignment=1,
    )
    header_style = ParagraphStyle(
        "HeaderBellamy",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.white,
    )
    cell_style = ParagraphStyle(
        "CellBellamy",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
    )

    story = []
    story.append(Paragraph("BELLAMY | DIGITAL STORE", title_style))
    story.append(Paragraph("Histórico de Movimentações", subtitle_style))
    story.append(Spacer(1, 0.6 * cm))

    # Dados do usuário
    username_str = f"@{username}" if username else "—"
    user_info = [
        ["Usuário:", first_name],
        ["Username:", username_str],
        ["Telegram ID:", str(telegram_id)],
        ["ID da carteira:", f"#{user_id}"],
        ["Saldo atual:", _fmt_money(balance)],
        ["Gerado em:", datetime.now(TZ).strftime("%d/%m/%Y às %H:%M")],
    ]
    user_table = Table(
        user_info,
        colWidths=[4 * cm, 12 * cm],
    )
    user_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#374151")),
                ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#111827")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(user_table)
    story.append(Spacer(1, 0.8 * cm))

    # Tabela de movimentações
    if not transactions:
        story.append(
            Paragraph(
                "<i>Nenhuma movimentação registrada.</i>",
                ParagraphStyle(
                    "Empty",
                    parent=styles["Normal"],
                    fontSize=10,
                    textColor=colors.HexColor("#6B7280"),
                    alignment=1,
                ),
            )
        )
    else:
        headers = [
            "Data",
            "Tipo",
            "Descrição",
            "Valor",
            "Status",
            "Saldo após",
        ]
        data = [
            [Paragraph(f"<b>{h}</b>", header_style) for h in headers]
        ]

        for tx in transactions:
            tipo = CATEGORY_LABEL.get(tx.category, tx.category)
            sinal = "+" if tx.type == "credit" else "−"
            valor_str = f"{sinal} {_fmt_money(tx.amount)}"
            valor_color = "#059669" if tx.type == "credit" else "#DC2626"
            data.append(
                [
                    Paragraph(_fmt_datetime(tx.created_at), cell_style),
                    Paragraph(tipo, cell_style),
                    Paragraph(tx.description or "—", cell_style),
                    Paragraph(
                        f"<font color='{valor_color}'>{valor_str}</font>",
                        cell_style,
                    ),
                    Paragraph("Concluído", cell_style),
                    Paragraph(_fmt_money(tx.balance_after), cell_style),
                ]
            )

        table = Table(
            data,
            colWidths=[2.3 * cm, 2 * cm, 5.5 * cm, 2.3 * cm, 1.8 * cm, 2.1 * cm],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                        [colors.white, colors.HexColor("#F9FAFB")]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)

    doc.build(story)
    buffer.seek(0)
    return buffer
