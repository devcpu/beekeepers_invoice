#!/usr/bin/env python3
"""
Debug-Script: Prüft warum die Hash-Verifikation fehlschlägt
"""
from app import create_app
from models import db, Invoice
import os
import json
import hashlib

def debug_invoice_hash():
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        # Letzte Rechnung holen (neueste mit aktuellem Schema)
        invoice = Invoice.query.order_by(Invoice.id.desc()).first()
        
        if not invoice:
            print("❌ Keine Rechnung gefunden")
            return
        
        print(f"\n=== Debug für Rechnung {invoice.invoice_number} ===\n")
        
        # Gespeicherter Hash
        print(f"Gespeicherter Hash: {invoice.data_hash}")
        
        # Daten die für Hash verwendet werden
        hash_data = {
            'invoice_number': invoice.invoice_number,
            'customer_id': invoice.customer_id,
            'invoice_date': invoice.invoice_date.isoformat() if invoice.invoice_date else None,
            'subtotal': f"{float(invoice.subtotal):.2f}",
            'tax_rate': f"{float(invoice.tax_rate):.2f}",
            'tax_amount': f"{float(invoice.tax_amount):.2f}",
            'total': f"{float(invoice.total):.2f}",
            'tax_model': invoice.tax_model,
            'customer_type': invoice.customer_type,
            'line_items': [
                {
                    'description': item.description,
                    'quantity': f"{float(item.quantity):.2f}",
                    'unit_price': f"{float(item.unit_price):.2f}",
                    'total': f"{float(item.total):.2f}"
                }
                for item in invoice.line_items
            ]
        }
        
        print("\nHash-Daten:")
        print(json.dumps(hash_data, indent=2, sort_keys=True))
        
        # Hash berechnen
        hash_string = json.dumps(hash_data, sort_keys=True)
        calculated_hash = hashlib.sha256(hash_string.encode()).hexdigest()
        
        print(f"\nBerechneter Hash: {calculated_hash}")
        print(f"\nHashes stimmen überein: {invoice.data_hash == calculated_hash}")
        
        # Einzelne Felder prüfen
        print("\n=== Feldwerte ===")
        print(f"invoice_number: {invoice.invoice_number}")
        print(f"customer_id: {invoice.customer_id}")
        print(f"invoice_date: {invoice.invoice_date}")
        print(f"subtotal: {invoice.subtotal}")
        print(f"tax_rate: {invoice.tax_rate}")
        print(f"tax_amount: {invoice.tax_amount}")
        print(f"total: {invoice.total}")
        print(f"tax_model: {invoice.tax_model}")
        print(f"customer_type: {invoice.customer_type}")
        print(f"Anzahl Line Items: {len(invoice.line_items)}")

if __name__ == '__main__':
    debug_invoice_hash()
