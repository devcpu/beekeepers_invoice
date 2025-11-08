from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from datetime import datetime
import os


def add_fold_and_punch_marks(canvas, doc):
    """Fügt Faltmarken und Lochmarke nach DIN 5008 hinzu."""
    canvas.saveState()
    canvas.setStrokeColorRGB(0.5, 0.5, 0.5)
    canvas.setLineWidth(0.5)
    
    # Obere Faltmarke (105mm von oben)
    canvas.line(0, A4[1] - 105*mm, 5*mm, A4[1] - 105*mm)
    
    # Lochmarke (148.5mm von oben - Mitte der Seite)
    canvas.line(0, A4[1] - 148.5*mm, 5*mm, A4[1] - 148.5*mm)
    
    # Untere Faltmarke (210mm von oben)
    canvas.line(0, A4[1] - 210*mm, 5*mm, A4[1] - 210*mm)
    
    canvas.restoreState()


def generate_delivery_note_pdf(delivery_note, pdf_folder, config=None):
    """
    Generiert ein PDF für einen Lieferschein.
    
    Args:
        delivery_note: DeliveryNote-Objekt aus der Datenbank
        pdf_folder: Pfad zum Ordner für PDF-Dateien
        config: Flask config Objekt (optional, für Firmendaten)
        
    Returns:
        Pfad zur generierten PDF-Datei
    """
    # Dateiname und Pfad
    filename = f"Lieferschein_{delivery_note.delivery_note_number}.pdf"
    filepath = os.path.join(pdf_folder, filename)
    
    # PDF erstellen
    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )
    
    # Container für PDF-Elemente
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=30
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=12
    )
    normal_style = styles['Normal']
    small_style = ParagraphStyle(
        'Small',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey
    )
    
    # Firmendaten aus Config oder Defaults
    company_name = config.get('COMPANY_NAME', 'Ihre Firma GmbH') if config else 'Ihre Firma GmbH'
    company_holder = config.get('COMPANY_HOLDER', '') if config else ''
    company_street = config.get('COMPANY_STREET', 'Musterstraße 123') if config else 'Musterstraße 123'
    company_zip = config.get('COMPANY_ZIP', '12345') if config else '12345'
    company_city = config.get('COMPANY_CITY', 'Musterstadt') if config else 'Musterstadt'
    company_email = config.get('COMPANY_EMAIL', 'info@firma.de') if config else 'info@firma.de'
    company_phone = config.get('COMPANY_PHONE', '+49 123 456789') if config else '+49 123 456789'
    
    # Absenderzeile (klein, für Fensterbriefumschlag)
    sender_line = f"{company_name} • {company_street} • {company_zip} {company_city}"
    
    # Empfängeradresse (Fensterbriefumschlag-Position)
    recipient_data = [Paragraph(sender_line, small_style)]
    recipient_data.append(Spacer(1, 3*mm))
    
    if delivery_note.customer.company_name:
        recipient_data.append(Paragraph(f"<b>{delivery_note.customer.company_name}</b>", normal_style))
    recipient_data.append(Paragraph(f"{delivery_note.customer.first_name} {delivery_note.customer.last_name}", normal_style))
    if delivery_note.customer.address:
        for line in delivery_note.customer.address.split('\n'):
            recipient_data.append(Paragraph(line, normal_style))
    
    # Absender rechts
    sender_data = [
        Paragraph(f"<b>{company_name}</b>", normal_style),
    ]
    if company_holder:
        sender_data.append(Paragraph(company_holder, normal_style))
    sender_data.extend([
        Paragraph(company_street, normal_style),
        Paragraph(f"{company_zip} {company_city}", normal_style),
        Spacer(1, 2*mm),
        Paragraph(f"Tel: {company_phone}", normal_style),
        Paragraph(f"E-Mail: {company_email}", normal_style),
    ])
    
    # Header mit Empfänger links und Titel + Absender rechts
    header_table = Table([
        [recipient_data, [Paragraph("LIEFERSCHEIN", title_style), Spacer(1, 5*mm)] + sender_data]
    ], colWidths=[90*mm, 80*mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (0, 0), 0),
        ('RIGHTPADDING', (1, 0), (1, 0), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 15*mm))
    
    # Lieferscheindetails
    details_headers = ["Lieferscheinnummer", "Lieferdatum"]
    details_values = [
        delivery_note.delivery_note_number, 
        delivery_note.delivery_date.strftime('%d.%m.%Y')
    ]
    
    details_table = Table([details_headers, details_values], 
                         colWidths=[90*mm, 80*mm])
    details_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 2),
        ('TOPPADDING', (0, 1), (-1, 1), 2),
    ]))
    elements.append(details_table)
    elements.append(Spacer(1, 8*mm))
    
    # Hinweis auf Kommissionsware
    elements.append(Paragraph(
        "<i>Kommissionsware - Die Ware bleibt bis zur vollständigen Bezahlung unser Eigentum.</i>",
        ParagraphStyle('Info', parent=normal_style, fontSize=9, textColor=colors.HexColor('#7f8c8d'))
    ))
    elements.append(Spacer(1, 5*mm))
    
    # Positionen
    elements.append(Paragraph("Gelieferte Artikel", heading_style))
    
    # Tabellenkopf und Daten - mit oder ohne MwSt
    if delivery_note.show_tax:
        line_items_data = [
            ["Pos.", "Beschreibung", "Menge", "Einzelpreis (netto)", "MwSt %", "Gesamt (netto)", "Gesamt (brutto)"]
        ]
        
        for idx, item in enumerate(sorted(delivery_note.items, key=lambda x: x.position), 1):
            # Steuersatz aus Produkt oder Standard
            product = item.product if hasattr(item, 'product') else None
            tax_rate = product.tax_rate if product and product.tax_rate else 7.80
            
            net_total = float(item.total)
            tax_amount = net_total * (float(tax_rate) / 100)
            gross_total = net_total + tax_amount
            
            line_items_data.append([
                str(idx),
                item.description,
                f"{float(item.quantity):.2f}",
                f"{float(item.unit_price):.2f} €",
                f"{tax_rate:.1f}%",
                f"{net_total:.2f} €",
                f"{gross_total:.2f} €"
            ])
        
        line_items_table = Table(
            line_items_data,
            colWidths=[10*mm, 60*mm, 15*mm, 25*mm, 15*mm, 25*mm, 25*mm]
        )
    else:
        # Ohne Steuer - wie bisher
        line_items_data = [
            ["Pos.", "Beschreibung", "Menge", "Reseller-Preis", "Wert"]
        ]
        
        for idx, item in enumerate(sorted(delivery_note.items, key=lambda x: x.position), 1):
            line_items_data.append([
                str(idx),
                item.description,
                f"{float(item.quantity):.2f}",
                f"{float(item.unit_price):.2f} €",
                f"{float(item.total):.2f} €"
            ])
        
        line_items_table = Table(
            line_items_data,
            colWidths=[15*mm, 90*mm, 20*mm, 25*mm, 25*mm]
        )
    
    line_items_table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
        
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Lines
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#2c3e50')),
        ('LINEBELOW', (0, -1), (-1, -1), 1, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        
        # Padding
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(line_items_table)
    elements.append(Spacer(1, 10*mm))
    
    # Gesamtwert (nur informativ, keine Rechnung)
    total_value = delivery_note.calculate_total()
    
    if delivery_note.show_tax:
        # Mit Steuer - berechne Netto, MwSt, Brutto
        total_net = 0
        total_tax = 0
        
        for item in delivery_note.items:
            product = item.product if hasattr(item, 'product') else None
            tax_rate = product.tax_rate if product and product.tax_rate else 7.80
            
            net = float(item.total)
            tax = net * (float(tax_rate) / 100)
            
            total_net += net
            total_tax += tax
        
        total_gross = total_net + total_tax
        
        totals_data = [
            ["", "", "", "", "", "", ""],
            ["", "", "", "", "", "Summe (netto):", f"{total_net:.2f} €"],
            ["", "", "", "", "", "MwSt:", f"{total_tax:.2f} €"],
            ["", "", "", "", "", "Summe (brutto):", f"{total_gross:.2f} €"],
        ]
        
        totals_table = Table(
            totals_data,
            colWidths=[10*mm, 60*mm, 15*mm, 25*mm, 15*mm, 25*mm, 25*mm]
        )
        
        totals_table.setStyle(TableStyle([
            ('FONTNAME', (5, 1), (6, 3), 'Helvetica-Bold'),
            ('FONTSIZE', (5, 1), (6, 2), 10),
            ('FONTSIZE', (5, 3), (6, 3), 12),
            ('ALIGN', (5, 0), (-1, -1), 'RIGHT'),
            ('LINEABOVE', (5, 3), (6, 3), 2, colors.HexColor('#2c3e50')),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
        ]))
    else:
        # Ohne Steuer - wie bisher
        totals_data = [
            ["", "", "", "", ""],
            ["", "", "", "Gesamtwert (Reseller):", f"{total_value:.2f} €"],
        ]
        
        totals_table = Table(
            totals_data,
            colWidths=[15*mm, 90*mm, 20*mm, 25*mm, 25*mm]
        )
        
        totals_table.setStyle(TableStyle([
            ('FONTNAME', (3, 1), (4, 1), 'Helvetica-Bold'),
            ('FONTSIZE', (3, 1), (-1, 1), 12),
            ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
            ('LINEABOVE', (3, 1), (4, 1), 2, colors.HexColor('#2c3e50')),
            ('TOPPADDING', (0, 1), (-1, 1), 6),
        ]))
    
    elements.append(totals_table)
    elements.append(Spacer(1, 10*mm))
    
    # Hinweis
    elements.append(Paragraph(
        "<b>Hinweis:</b> Dies ist kein Rechnungsdokument. Die Abrechnung erfolgt separat nach Verkauf der Ware.",
        ParagraphStyle('Warning', parent=normal_style, fontSize=10, textColor=colors.HexColor('#856404'),
                      backColor=colors.HexColor('#fff3cd'), borderPadding=10)
    ))
    
    # Notizen
    if delivery_note.notes:
        elements.append(Spacer(1, 10*mm))
        elements.append(Paragraph("Bemerkungen", heading_style))
        notes_text = delivery_note.notes.replace('\n', '<br/>')
        elements.append(Paragraph(notes_text, normal_style))
    
    # Unterschrift
    elements.append(Spacer(1, 20*mm))
    
    signature_table = Table([
        ["_" * 30, "_" * 30],
        ["Datum, Unterschrift Lieferant", "Datum, Unterschrift Empfänger"]
    ], colWidths=[85*mm, 85*mm])
    signature_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 1), (-1, 1), 2),
    ]))
    elements.append(signature_table)
    
    # PDF generieren mit Faltmarken
    doc.build(elements, onFirstPage=add_fold_and_punch_marks, onLaterPages=add_fold_and_punch_marks)
    
    return filepath
