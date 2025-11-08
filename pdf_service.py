import os
from io import BytesIO

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_epc_qr_code(beneficiary_name, iban, bic, amount, reference):
    """
    Generiert einen EPC-QR-Code für SEPA-Überweisungen.

    EPC069-12 Standard für SEPA Credit Transfer
    """
    # EPC-QR-Code Daten (Service Tag Version 2)
    epc_data = [
        "BCD",  # Service Tag
        "002",  # Version
        "1",  # Character set (1 = UTF-8)
        "SCT",  # Identification (SEPA Credit Transfer)
        bic,  # BIC
        beneficiary_name[:70],  # Beneficiary Name (max 70 chars)
        iban.replace(" ", ""),  # Beneficiary Account (IBAN without spaces)
        f"EUR{amount:.2f}",  # Amount (EUR + amount with 2 decimals)
        "",  # Purpose (optional)
        reference[:140] if reference else "",  # Structured Reference (max 140 chars)
        "",  # Unstructured Remittance (optional, alternative to structured reference)
    ]

    epc_string = "\n".join(epc_data)

    # QR-Code generieren
    qr = qrcode.QRCode(
        version=None,  # Automatic sizing
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(epc_string)
    qr.make(fit=True)

    # QR-Code als Bild
    img = qr.make_image(fill_color="black", back_color="white")

    # In BytesIO konvertieren für ReportLab
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return buffer


def add_fold_and_punch_marks(canvas, doc):
    """
    Fügt Faltmarken und Lochmarke nach DIN 5008 hinzu.
    - Obere Faltmarke bei 105mm von oben
    - Untere Faltmarke bei 210mm von oben
    - Lochmarke bei 148.5mm von oben (Mitte)
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


def generate_invoice_pdf(invoice, pdf_folder, config=None):
    """
    Generiert ein PDF für die angegebene Rechnung.

    Args:
        invoice: Invoice-Objekt aus der Datenbank
        pdf_folder: Pfad zum Ordner für PDF-Dateien
        config: Flask config Objekt (optional, für Firmendaten)

    Returns:
        Pfad zur generierten PDF-Datei
    """
    # Dateiname und Pfad
    filename = f"Rechnung_{invoice.invoice_number}.pdf"
    filepath = os.path.join(pdf_folder, filename)

    # PDF erstellen
    doc = SimpleDocTemplate(
        filepath, pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm, topMargin=20 * mm, bottomMargin=20 * mm
    )

    # Container für PDF-Elemente
    elements = []

    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle", parent=styles["Heading1"], fontSize=24, textColor=colors.HexColor("#2c3e50"), spaceAfter=30
    )
    heading_style = ParagraphStyle(
        "CustomHeading", parent=styles["Heading2"], fontSize=14, textColor=colors.HexColor("#2c3e50"), spaceAfter=12
    )
    normal_style = styles["Normal"]
    small_style = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)

    # Firmendaten aus Config oder Defaults
    company_name = config.get("COMPANY_NAME", "Ihre Firma GmbH") if config else "Ihre Firma GmbH"
    company_holder = config.get("COMPANY_HOLDER", "") if config else ""
    company_street = config.get("COMPANY_STREET", "Musterstraße 123") if config else "Musterstraße 123"
    company_zip = config.get("COMPANY_ZIP", "12345") if config else "12345"
    company_city = config.get("COMPANY_CITY", "Musterstadt") if config else "Musterstadt"
    company_email = config.get("COMPANY_EMAIL", "info@firma.de") if config else "info@firma.de"
    company_phone = config.get("COMPANY_PHONE", "+49 123 456789") if config else "+49 123 456789"
    company_tax_id = config.get("COMPANY_TAX_ID", "DE123456789") if config else "DE123456789"

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

    # Absender rechts (auf gleicher Höhe wie Titel)
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
    if company_tax_id != "DE123456789":
        sender_data.append(Paragraph(f"Steuernr: {company_tax_id}", normal_style))

    # Header mit Empfänger links und Titel + Absender rechts
    header_table = Table(
        [[recipient_data, [Paragraph("RECHNUNG", title_style), Spacer(1, 5 * mm)] + sender_data]],
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

    # Rechnungsdetails als Tabelle
    details_headers = ["Rechnungsnummer", "Rechnungsdatum"]
    details_values = [invoice.invoice_number, invoice.invoice_date.strftime("%d.%m.%Y")]

    if invoice.due_date:
        details_headers.append("Fälligkeitsdatum")
        details_values.append(invoice.due_date.strftime("%d.%m.%Y"))

    details_table = Table([details_headers, details_values], colWidths=[60 * mm] * len(details_headers))
    details_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("TOPPADDING", (0, 1), (-1, 1), 2),
            ]
        )
    )
    elements.append(details_table)

    if invoice.customer.tax_id:
        elements.append(Spacer(1, 3 * mm))
        elements.append(Paragraph(f"<b>Steuernummer Kunde:</b> {invoice.customer.tax_id}", normal_style))

    elements.append(Spacer(1, 8 * mm))

    # Positionen
    elements.append(Paragraph("Leistungen", heading_style))

    # Tabellenkopf und Daten
    line_items_data = [["Pos.", "Beschreibung", "Menge", "Einzelpreis", "Gesamt"]]

    for idx, item in enumerate(sorted(invoice.line_items, key=lambda x: x.position), 1):
        line_items_data.append(
            [
                str(idx),
                item.description,
                f"{float(item.quantity):.2f}",
                f"{float(item.unit_price):.2f} €",
                f"{float(item.total):.2f} €",
            ]
        )

    line_items_table = Table(line_items_data, colWidths=[15 * mm, 90 * mm, 20 * mm, 25 * mm, 25 * mm])

    line_items_table.setStyle(
        TableStyle(
            [
                # Header
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ALIGN", (0, 0), (-1, 0), "LEFT"),
                # Body
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                # Lines
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#2c3e50")),
                ("LINEBELOW", (0, -1), (-1, -1), 1, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                # Padding
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    elements.append(line_items_table)
    elements.append(Spacer(1, 10 * mm))

    # Summen - abhängig vom Steuermodell
    tax_model = invoice.tax_model if hasattr(invoice, "tax_model") else "standard"

    if tax_model == "kleinunternehmer":
        # Keine MwSt.
        totals_data = [
            ["", "", "", "", ""],
            ["", "", "", "Gesamtbetrag:", f"{float(invoice.total):.2f} €"],
        ]
    elif tax_model == "landwirtschaft":
        # Durchschnittssatz: MwSt. in Endsumme enthalten
        totals_data = [
            ["", "", "", "", ""],
            ["", "", "", "Gesamtbetrag:", f"{float(invoice.total):.2f} €"],
            ["", "", "", f"darin enth. MwSt. ({float(invoice.tax_rate):.2f}%):", f"{float(invoice.tax_amount):.2f} €"],
        ]
    else:
        # Standard: MwSt. wird aufgeschlagen
        totals_data = [
            ["", "", "", "Zwischensumme:", f"{float(invoice.subtotal):.2f} €"],
            ["", "", "", f"MwSt. ({float(invoice.tax_rate):.2f}%):", f"{float(invoice.tax_amount):.2f} €"],
            ["", "", "", "", ""],
            ["", "", "", "Gesamtbetrag:", f"{float(invoice.total):.2f} €"],
        ]

    totals_table = Table(totals_data, colWidths=[15 * mm, 90 * mm, 20 * mm, 25 * mm, 25 * mm])

    # Style abhängig von Anzahl Zeilen
    if tax_model == "kleinunternehmer":
        totals_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (3, 1), (4, 1), "Helvetica-Bold"),
                    ("FONTSIZE", (3, 0), (-1, -1), 12),
                    ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                    ("LINEABOVE", (3, 1), (4, 1), 2, colors.HexColor("#2c3e50")),
                    ("TOPPADDING", (0, 1), (-1, 1), 6),
                ]
            )
        )
    elif tax_model == "landwirtschaft":
        totals_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (3, 1), (4, 1), "Helvetica-Bold"),
                    ("FONTSIZE", (3, 1), (-1, 1), 12),
                    ("FONTNAME", (3, 2), (4, 2), "Helvetica"),
                    ("FONTSIZE", (3, 2), (-1, 2), 9),
                    ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                    ("LINEABOVE", (3, 1), (4, 1), 2, colors.HexColor("#2c3e50")),
                    ("TOPPADDING", (0, 1), (-1, 1), 6),
                ]
            )
        )
    else:
        totals_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (3, 0), (3, 1), "Helvetica"),
                    ("FONTNAME", (4, 0), (4, 1), "Helvetica"),
                    ("FONTNAME", (3, 3), (4, 3), "Helvetica-Bold"),
                    ("FONTSIZE", (3, 0), (-1, -1), 10),
                    ("FONTSIZE", (3, 3), (-1, 3), 12),
                    ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                    ("LINEABOVE", (3, 3), (4, 3), 2, colors.HexColor("#2c3e50")),
                    ("TOPPADDING", (0, 3), (-1, 3), 6),
                ]
            )
        )

    elements.append(totals_table)
    elements.append(Spacer(1, 10 * mm))

    # Steuerhinweise
    if tax_model == "kleinunternehmer":
        tax_note = "<i>Aufgrund der Kleinunternehmerregelung gem. § 19 UStG wird keine Umsatzsteuer berechnet.</i>"
        elements.append(Paragraph(tax_note, normal_style))
        elements.append(Spacer(1, 5 * mm))
    elif tax_model == "landwirtschaft":
        tax_note = f"<i>Landwirtschaftliche Urproduktion - Durchschnittssatzbesteuerung nach § 24 UStG. Der Verkaufspreis enthält {float(invoice.tax_rate):.2f}% Umsatzsteuer, die von umsatzsteuerberechtigten Kunden als Vorsteuer geltend gemacht werden kann.</i>"
        elements.append(Paragraph(tax_note, normal_style))
        elements.append(Spacer(1, 5 * mm))

    # Notizen / Zahlungsbedingungen
    if invoice.notes:
        elements.append(Spacer(1, 5 * mm))
        elements.append(Paragraph("Zahlungsbedingungen", heading_style))
        notes_text = invoice.notes.replace("\n", "<br/>")
        elements.append(Paragraph(notes_text, normal_style))
        elements.append(Spacer(1, 5 * mm))

    # Zahlungsinformationen
    elements.append(Spacer(1, 5 * mm))
    elements.append(Paragraph("Zahlungsinformationen", heading_style))

    bank_name = config.get("BANK_NAME", "Ihre Bank") if config else "Ihre Bank"
    bank_iban = config.get("BANK_IBAN", "DE00 0000 0000 0000 0000 00") if config else "DE00 0000 0000 0000 0000 00"
    bank_bic = config.get("BANK_BIC", "BANKDEFF") if config else "BANKDEFF"

    # EPC-QR-Code generieren
    qr_buffer = generate_epc_qr_code(
        beneficiary_name=company_holder if company_holder else company_name,
        iban=bank_iban,
        bic=bank_bic,
        amount=invoice.total,
        reference=invoice.invoice_number,
    )
    qr_image = Image(qr_buffer, width=25 * mm, height=25 * mm)

    # Bankverbindung und QR-Code nebeneinander
    payment_info = f"""
    Bitte überweisen Sie den Betrag auf folgendes Konto:<br/>
    <b>{bank_name}</b><br/>
    IBAN: {bank_iban}<br/>
    BIC: {bank_bic}<br/>
    Verwendungszweck: {invoice.invoice_number}
    """

    payment_table = Table([[Paragraph(payment_info, normal_style), qr_image]], colWidths=[110 * mm, 60 * mm])
    payment_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
            ]
        )
    )
    elements.append(payment_table)

    # PayPal-Information (falls vorhanden)
    paypal = config.get("PAYPAL", "") if config else ""
    if paypal:
        elements.append(Spacer(1, 3 * mm))
        paypal_text = f"<b>Alternativ per PayPal:</b> {paypal}"
        elements.append(Paragraph(paypal_text, normal_style))

    # Fußzeile mit Integritätshash
    elements.append(Spacer(1, 10 * mm))
    hash_text = f"<font size=7 color='grey'>Daten-Hash (Manipulationssicherheit): {invoice.data_hash}</font>"
    elements.append(Paragraph(hash_text, normal_style))

    # PDF generieren mit Faltmarken
    doc.build(elements, onFirstPage=add_fold_and_punch_marks, onLaterPages=add_fold_and_punch_marks)

    return filepath


def generate_invoice_pdf_simple(invoice, pdf_folder):
    """
    Vereinfachte PDF-Generierung für schnelle Tests.
    """
    from reportlab.pdfgen import canvas

    filename = f"Rechnung_{invoice.invoice_number}.pdf"
    filepath = os.path.join(pdf_folder, filename)

    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4

    # Titel
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, height - 50, "RECHNUNG")

    # Rechnungsnummer und Datum
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 100, f"Rechnungsnummer: {invoice.invoice_number}")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 120, f"Datum: {invoice.invoice_date.strftime('%d.%m.%Y')}")

    # Kunde
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 160, "Kunde:")
    c.setFont("Helvetica", 11)
    y_pos = height - 180

    if invoice.customer.company_name:
        c.drawString(50, y_pos, invoice.customer.company_name)
        y_pos -= 15

    c.drawString(50, y_pos, f"{invoice.customer.first_name} {invoice.customer.last_name}")
    y_pos -= 15
    c.drawString(50, y_pos, invoice.customer.email)

    # Positionen
    y_pos -= 40
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y_pos, "Positionen:")
    y_pos -= 20

    c.setFont("Helvetica", 10)
    for item in invoice.line_items:
        c.drawString(50, y_pos, f"{item.description}")
        c.drawString(350, y_pos, f"{float(item.quantity):.2f} x {float(item.unit_price):.2f} €")
        c.drawString(480, y_pos, f"{float(item.total):.2f} €")
        y_pos -= 18

    # Summen
    y_pos -= 20
    c.drawString(350, y_pos, "Zwischensumme:")
    c.drawString(480, y_pos, f"{float(invoice.subtotal):.2f} €")
    y_pos -= 18

    c.drawString(350, y_pos, f"MwSt. ({float(invoice.tax_rate):.2f}%):")
    c.drawString(480, y_pos, f"{float(invoice.tax_amount):.2f} €")
    y_pos -= 25

    c.setFont("Helvetica-Bold", 12)
    c.drawString(350, y_pos, "Gesamtbetrag:")
    c.drawString(480, y_pos, f"{float(invoice.total):.2f} €")

    # Hash
    c.setFont("Helvetica", 6)
    c.drawString(50, 50, f"Hash: {invoice.data_hash}")

    c.save()
    return filepath
