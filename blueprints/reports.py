"""Jahresuebersicht Einnahmen nach Kundentyp (Web + PDF-Export)."""

from datetime import datetime
from decimal import Decimal
from io import BytesIO

from flask import Blueprint, render_template, request, send_file
from flask_login import login_required
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import extract

from models import Invoice, db

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")

_MONTH_NAMES = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


def _build_annual_revenue_stats(year):
    invoices = Invoice.query.filter(
        extract("year", Invoice.invoice_date) == year,
        Invoice.status == "paid",
    ).all()

    stats = {
        "year": year,
        "total_revenue": Decimal("0.00"),
        "total_invoices": 0,
        "by_type": {
            "endkunde": {"revenue": Decimal("0.00"), "count": 0, "label": "Endkunden (direkt)"},
            "type1_ust_extern": {"revenue": Decimal("0.00"), "count": 0, "label": "Typ 1: USt.-pflichtig extern"},
            "type2_non_ust_extern": {
                "revenue": Decimal("0.00"),
                "count": 0,
                "label": "Typ 2: Nicht USt.-pflichtig extern",
            },
            "type3_non_ust_pwa": {
                "revenue": Decimal("0.00"),
                "count": 0,
                "label": "Typ 3: Nicht USt.-pflichtig PWA",
            },
            "type4_owner_market": {"revenue": Decimal("0.00"), "count": 0, "label": "Typ 4: Owner Markt (BAR)"},
            "bar": {"revenue": Decimal("0.00"), "count": 0, "label": "BAR-Verkäufe (Kasse)"},
            "other": {"revenue": Decimal("0.00"), "count": 0, "label": "Sonstige"},
        },
        "by_month": {},
    }

    for month in range(1, 13):
        stats["by_month"][month] = {"revenue": Decimal("0.00"), "count": 0, "label": _MONTH_NAMES[month - 1]}

    for invoice in invoices:
        total = invoice.total or Decimal("0.00")
        stats["total_revenue"] += total
        stats["total_invoices"] += 1

        month = invoice.invoice_date.month
        stats["by_month"][month]["revenue"] += total
        stats["by_month"][month]["count"] += 1

        customer_type = "other"
        if invoice.invoice_number and invoice.invoice_number.startswith("BAR-"):
            customer_type = "bar"
        elif invoice.customer and invoice.customer.reseller_user:
            for user in invoice.customer.reseller_user:
                if user.reseller_type != "none":
                    customer_type = user.reseller_type
                    break
        elif invoice.customer_type == "endkunde" or (invoice.customer and not invoice.customer.reseller_user):
            customer_type = "endkunde"

        if customer_type in stats["by_type"]:
            stats["by_type"][customer_type]["revenue"] += total
            stats["by_type"][customer_type]["count"] += 1

    return stats


@reports_bp.route("/annual-revenue")
@login_required
def annual_revenue_report():
    """Jahresübersicht Einnahmen nach Kundentyp"""
    year = request.args.get("year", datetime.now().year, type=int)

    stats = _build_annual_revenue_stats(year)
    stats["max_month_revenue"] = max([stats["by_month"][m]["revenue"] for m in range(1, 13)], default=Decimal("0.00"))

    available_years_query = (
        db.session.query(extract("year", Invoice.invoice_date).label("year")).distinct().order_by(extract("year", Invoice.invoice_date).desc()).all()
    )
    available_years = [int(y[0]) for y in available_years_query if y[0]]

    return render_template("reports/annual_revenue.html", stats=stats, available_years=available_years)


@reports_bp.route("/annual-revenue/pdf")
@login_required
def annual_revenue_report_pdf():
    """PDF-Export der Jahresübersicht"""
    year = request.args.get("year", datetime.now().year, type=int)
    stats = _build_annual_revenue_stats(year)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)

    elements = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#2c3e50"),
        spaceAfter=30,
        alignment=1,
    )
    elements.append(Paragraph(f"Jahresübersicht Einnahmen {year}", title_style))
    elements.append(Spacer(1, 0.5 * cm))

    summary_data = [
        ["Gesamtumsatz:", f'{float(stats["total_revenue"]):.2f} €'],
        ["Anzahl Rechnungen:", str(stats["total_invoices"])],
        [
            "Durchschnitt pro Rechnung:",
            (f'{float(stats["total_revenue"] / stats["total_invoices"]):.2f} €' if stats["total_invoices"] > 0 else "0,00 €"),
        ],
    ]

    summary_table = Table(summary_data, colWidths=[8 * cm, 8 * cm])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e8f4f8")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 12),
                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#2c3e50")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 1 * cm))

    elements.append(Paragraph("Aufschlüsselung nach Kundentyp", styles["Heading2"]))
    elements.append(Spacer(1, 0.3 * cm))

    type_data = [["Kundentyp", "Umsatz", "Anzahl", "Anteil"]]
    for type_key, type_info in stats["by_type"].items():  # pylint: disable=unused-variable
        if type_info["count"] > 0:
            percentage = (type_info["revenue"] / stats["total_revenue"] * 100) if stats["total_revenue"] > 0 else 0
            type_data.append(
                [
                    type_info["label"],
                    f'{float(type_info["revenue"]):.2f} €',
                    str(type_info["count"]),
                    f"{float(percentage):.1f}%",
                ]
            )

    type_table = Table(type_data, colWidths=[10 * cm, 4 * cm, 3 * cm, 3 * cm])
    type_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 1, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.append(type_table)
    elements.append(Spacer(1, 1 * cm))

    elements.append(Paragraph("Monatliche Aufschlüsselung", styles["Heading2"]))
    elements.append(Spacer(1, 0.3 * cm))

    month_data = [["Monat", "Umsatz", "Anzahl"]]
    for month in range(1, 13):
        month_info = stats["by_month"][month]
        month_data.append([month_info["label"], f'{float(month_info["revenue"]):.2f} €', str(month_info["count"])])

    month_table = Table(month_data, colWidths=[8 * cm, 6 * cm, 6 * cm])
    month_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#27ae60")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 1, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.append(month_table)
    elements.append(Spacer(1, 1 * cm))

    footer_style = ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    elements.append(
        Paragraph(
            f'Erstellt am: {datetime.now().strftime("%d.%m.%Y %H:%M")} | ' f"Berücksichtigt: Alle bezahlten Rechnungen des Jahres {year}",
            footer_style,
        )
    )

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name=f"Jahresuebersicht_{year}.pdf", mimetype="application/pdf")
