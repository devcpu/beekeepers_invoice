import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def add_fold_and_punch_marks(canvas, doc):
    """
    Fügt Faltmarken und Lochmarke nach DIN 5008 hinzu.
    """
    canvas.saveState()
    canvas.setStrokeColorRGB(0.5, 0.5, 0.5)
    canvas.setLineWidth(0.5)

    # Obere Faltmarke (105mm von oben)
    canvas.line(0, A4[1] - 105 * mm, 5 * mm, A4[1] - 105 * mm)

    # Lochmarke (148.5mm von oben - Mitte der Seite)
    canvas.line(0, A4[1] - 148.5 * mm, 5 * mm, A4[1] - 148.5 * mm)

    # Untere Faltmarke (210mm von oben)
    canvas.line(0, A4[1] - 210 * mm, 5 * mm, A4[1] - 210 * mm)

    canvas.restoreState()


def generate_reminder_pdf(invoice, reminder, pdf_folder, config=None):
    """
    Generiert ein PDF für eine Mahnung.

    Args:
        invoice: Invoice-Objekt aus der Datenbank
        reminder: Reminder-Objekt aus der Datenbank
        pdf_folder: Pfad zum Ordner für PDF-Dateien
        config: Flask config Objekt (optional, für Firmendaten)

    Returns:
        Pfad zur generierten PDF-Datei
    """
    # Dateiname und Pfad
    filename = f"Mahnung_{reminder.reminder_level}_{invoice.invoice_number}.pdf"
    filepath = os.path.join(pdf_folder, filename)

    # PDF erstellen
    doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm, topMargin=20 * mm, bottomMargin=20 * mm)

    # Container für PDF-Elemente
    elements = []

    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        textColor=colors.HexColor("#e74c3c"),  # Rot für Mahnung
        spaceAfter=30,
    )
    heading_style = ParagraphStyle("CustomHeading", parent=styles["Heading2"], fontSize=14, textColor=colors.HexColor("#2c3e50"), spaceAfter=12)
    normal_style = styles["Normal"]
    small_style = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    warning_style = ParagraphStyle(
        "Warning",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#e74c3c"),
        spaceAfter=12,
        spaceBefore=12,
    )

    # Firmendaten aus Config oder Defaults
    company_name = config.get("COMPANY_NAME", "Ihre Firma GmbH") if config else "Ihre Firma GmbH"
    company_holder = config.get("COMPANY_HOLDER", "") if config else ""
    company_street = config.get("COMPANY_STREET", "Musterstraße 123") if config else "Musterstraße 123"
    company_zip = config.get("COMPANY_ZIP", "12345") if config else "12345"
    company_city = config.get("COMPANY_CITY", "Musterstadt") if config else "Musterstadt"
    company_email = config.get("COMPANY_EMAIL", "info@firma.de") if config else "info@firma.de"
    company_phone = config.get("COMPANY_PHONE", "+49 123 456789") if config else "+49 123 456789"

    # Absenderzeile (klein, für Fensterbriefumschlag)
    sender_line = f"{company_name} • {company_street} • {company_zip} {company_city}"

    # Empfängeradresse (Fensterbriefumschlag-Position)
    recipient_data = [Paragraph(sender_line, small_style)]
    recipient_data.append(Spacer(1, 3 * mm))

    if invoice.customer.company_name:
        recipient_data.append(Paragraph(f"<b>{invoice.customer.company_name}</b>", normal_style))
    recipient_data.append(Paragraph(f"{invoice.customer.first_name} {invoice.customer.last_name}", normal_style))
    if invoice.customer.address:
        for line in invoice.customer.address.split("\n"):
            recipient_data.append(Paragraph(line, normal_style))

    # Absender rechts
    sender_data = [
        Paragraph(f"<b>{company_name}</b>", normal_style),
    ]
    if company_holder:
        sender_data.append(Paragraph(company_holder, normal_style))
    sender_data.extend(
        [
            Paragraph(company_street, normal_style),
            Paragraph(f"{company_zip} {company_city}", normal_style),
            Spacer(1, 2 * mm),
            Paragraph(f"Tel: {company_phone}", normal_style),
            Paragraph(f"E-Mail: {company_email}", normal_style),
        ]
    )

    # Mahnstufe als Text
    reminder_level_text = ""
    if reminder.reminder_level == 1:
        reminder_level_text = "1. MAHNUNG"
    elif reminder.reminder_level == 2:
        reminder_level_text = "2. MAHNUNG"
    elif reminder.reminder_level == 3:
        reminder_level_text = "LETZTE MAHNUNG"
    else:
        reminder_level_text = f"{reminder.reminder_level}. MAHNUNG"

    # Header mit Empfänger links und Titel + Absender rechts
    header_table = Table(
        [[recipient_data, [Paragraph(reminder_level_text, title_style), Spacer(1, 5 * mm)] + sender_data]],
        colWidths=[90 * mm, 80 * mm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 15 * mm))

    # Mahnungsdetails
    details_headers = ["Rechnungsnummer", "Rechnungsdatum", "Fälligkeitsdatum", "Mahndatum"]
    details_values = [
        invoice.invoice_number,
        invoice.invoice_date.strftime("%d.%m.%Y"),
        invoice.due_date.strftime("%d.%m.%Y") if invoice.due_date else "-",
        reminder.reminder_date.strftime("%d.%m.%Y"),
    ]

    details_table = Table([details_headers, details_values], colWidths=[45 * mm] * 4)
    details_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("TOPPADDING", (0, 1), (-1, 1), 2),
                ("BACKGROUND", (2, 0), (3, 1), colors.HexColor("#fff3cd")),  # Hervorheben
            ]
        )
    )
    elements.append(details_table)
    elements.append(Spacer(1, 10 * mm))

    # Anrede und Mahntext
    salutation = (
        "Sehr geehrte Damen und Herren," if not invoice.customer.first_name else f"Sehr geehrte/r {invoice.customer.first_name} {invoice.customer.last_name},"
    )
    elements.append(Paragraph(salutation, normal_style))
    elements.append(Spacer(1, 5 * mm))

    # Mahntext abhängig von Mahnstufe
    if reminder.reminder_level == 1:
        reminder_text = """
        leider haben wir bis heute keinen Zahlungseingang für die oben genannte Rechnung feststellen können.
        Möglicherweise haben Sie die Zahlung bereits veranlasst - in diesem Fall betrachten Sie dieses Schreiben bitte als gegenstandslos.
        <br/><br/>
        Falls die Zahlung noch nicht erfolgt ist, bitten wir Sie höflich, den ausstehenden Betrag innerhalb der nächsten 7 Tage zu begleichen.
        """
    elif reminder.reminder_level == 2:
        reminder_text = """
        trotz unserer ersten Mahnung haben wir bis heute keinen Zahlungseingang für die oben genannte Rechnung feststellen können.
        <br/><br/>
        Wir bitten Sie dringend, den ausstehenden Betrag <b>umgehend innerhalb von 5 Tagen</b> zu begleichen,
        um weitere Maßnahmen zu vermeiden.
        """
    else:
        reminder_text = """
        <b>trotz mehrfacher Aufforderung</b> haben wir bis heute keinen Zahlungseingang für die oben genannte Rechnung feststellen können.
        <br/><br/>
        Wir fordern Sie hiermit <b>letztmalig</b> auf, den ausstehenden Betrag <b>innerhalb von 3 Tagen</b> zu begleichen.
        Sollte die Zahlung nicht erfolgen, sehen wir uns gezwungen, rechtliche Schritte einzuleiten und ein Inkassoverfahren einzuleiten.
        """

    elements.append(Paragraph(reminder_text, normal_style))
    elements.append(Spacer(1, 10 * mm))

    # Offene Beträge
    elements.append(Paragraph("Offene Forderung", heading_style))

    amounts_data = [
        ["Rechnungsbetrag:", f"{float(invoice.total):.2f} €"],
        ["Mahngebühr:", f"{float(reminder.reminder_fee):.2f} €"],
        ["", ""],
        ["<b>Gesamtbetrag:</b>", f"<b>{float(invoice.total + reminder.reminder_fee):.2f} €</b>"],
    ]

    amounts_table = Table(amounts_data, colWidths=[130 * mm, 40 * mm])
    amounts_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 2), "Helvetica"),
                ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("FONTSIZE", (0, 3), (-1, 3), 13),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, 3), (-1, 3), 2, colors.HexColor("#e74c3c")),
                ("TOPPADDING", (0, 3), (-1, 3), 8),
                ("TEXTCOLOR", (0, 3), (-1, 3), colors.HexColor("#e74c3c")),
            ]
        )
    )
    elements.append(amounts_table)
    elements.append(Spacer(1, 10 * mm))

    # Zahlungsinformationen
    elements.append(Paragraph("Zahlungsinformationen", heading_style))

    bank_name = config.get("BANK_NAME", "Ihre Bank") if config else "Ihre Bank"
    bank_iban = config.get("BANK_IBAN", "DE00 0000 0000 0000 0000 00") if config else "DE00 0000 0000 0000 0000 00"
    bank_bic = config.get("BANK_BIC", "BANKDEFF") if config else "BANKDEFF"

    payment_info = f"""
    Bitte überweisen Sie den Gesamtbetrag <b>{float(invoice.total + reminder.reminder_fee):.2f} €</b> auf folgendes Konto:<br/>
    <br/>
    <b>{bank_name}</b><br/>
    IBAN: {bank_iban}<br/>
    BIC: {bank_bic}<br/>
    <b>Verwendungszweck: {invoice.invoice_number} - Mahnung {reminder.reminder_level}</b>
    """

    elements.append(Paragraph(payment_info, normal_style))
    elements.append(Spacer(1, 10 * mm))

    # Abschlusstext
    if reminder.reminder_level == 1:
        closing_text = "Wir hoffen auf Ihr Verständnis und eine zeitnahe Begleichung der Rechnung."
    else:
        closing_text = "Wir bitten Sie eindringlich, dieser Zahlungsaufforderung nachzukommen."

    elements.append(Paragraph(closing_text, normal_style))
    elements.append(Spacer(1, 5 * mm))
    elements.append(Paragraph("Mit freundlichen Grüßen", normal_style))
    elements.append(Spacer(1, 5 * mm))
    elements.append(Paragraph(company_name, normal_style))

    # Warnung bei späterer Mahnung
    if reminder.reminder_level >= 2:
        elements.append(Spacer(1, 10 * mm))
        warning_box = Paragraph(
            "<b>WICHTIG:</b> Bei weiterer Nichtzahlung müssen wir zusätzliche Verzugszinsen und Inkassokosten in Rechnung stellen.",
            warning_style,
        )
        elements.append(warning_box)

    # PDF generieren mit Faltmarken
    doc.build(elements, onFirstPage=add_fold_and_punch_marks, onLaterPages=add_fold_and_punch_marks)

    return filepath
