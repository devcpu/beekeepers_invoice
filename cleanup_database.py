#!/usr/bin/env python3
"""
Script zum Bereinigen der Datenbank
Löscht alle Daten AUSSER Kunden (customers)
"""
import os

from sqlalchemy import text

from app import create_app
from models import (
    ConsignmentStock,
    Customer,
    DeliveryNote,
    DeliveryNoteItem,
    Invoice,
    InvoicePdfArchive,
    InvoiceStatusLog,
    LineItem,
    PaymentCheck,
    Product,
    Reminder,
    db,
)


def cleanup_database():
    """Löscht alle Tabellen außer customers"""
    app = create_app(os.getenv("FLASK_ENV", "development"))

    with app.app_context():
        try:
            print("🗑️  Starte Datenbank-Bereinigung...")
            print("=" * 60)

            # Zähle Einträge vor dem Löschen
            print("\n📊 Aktuelle Einträge:")
            print(f"   - Kunden: {Customer.query.count()}")
            print(f"   - Rechnungen: {Invoice.query.count()}")
            print(f"   - Rechnungspositionen: {LineItem.query.count()}")
            print(f"   - Produkte: {Product.query.count()}")
            print(f"   - Lieferscheine: {DeliveryNote.query.count()}")
            print(f"   - Kommissionslager: {ConsignmentStock.query.count()}")
            print(f"   - Status-Historie: {InvoiceStatusLog.query.count()}")
            print(f"   - PDF-Archive: {InvoicePdfArchive.query.count()}")

            # Sicherheitsabfrage
            print("\n⚠️  WARNUNG: Diese Aktion löscht ALLE Daten außer Kundendaten!")
            print("   Folgende Tabellen werden geleert:")
            print("   - invoices (inkl. Status-Historie und PDF-Archive)")
            print("   - line_items")
            print("   - products")
            print("   - delivery_notes & delivery_note_items")
            print("   - consignment_stock")
            print("   - payment_checks")
            print("   - reminders")
            print()

            confirm = input("Möchten Sie fortfahren? (Tippen Sie 'JA' zum Bestätigen): ")

            if confirm != "JA":
                print("❌ Abgebrochen.")
                return

            print("\n🔧 Lösche Daten...")

            # Reihenfolge wichtig wegen Foreign Keys!

            # 1. Mahnungen (falls Tabelle existiert)
            try:
                count = Reminder.query.delete()
                print(f"   ✓ {count} Mahnungen gelöscht")
            except Exception:
                print("   ℹ️  Mahnungen übersprungen (Tabelle existiert nicht)")

            # 2. Zahlungsprüfungen (falls Tabelle existiert)
            try:
                count = PaymentCheck.query.delete()
                print(f"   ✓ {count} Zahlungsprüfungen gelöscht")
            except Exception:
                print("   ℹ️  Zahlungsprüfungen übersprungen (Tabelle existiert nicht)")

            # 3. Status-Historie (Foreign Key zu invoices)
            count = InvoiceStatusLog.query.delete()
            print(f"   ✓ {count} Status-Historie-Einträge gelöscht")

            # 4. PDF-Archive (Foreign Key zu invoices)
            count = InvoicePdfArchive.query.delete()
            print(f"   ✓ {count} PDF-Archive gelöscht")

            # 5. Rechnungspositionen (Foreign Key zu invoices)
            count = LineItem.query.delete()
            print(f"   ✓ {count} Rechnungspositionen gelöscht")

            # 6. Rechnungen
            count = Invoice.query.delete()
            print(f"   ✓ {count} Rechnungen gelöscht")

            # 7. Kommissionslager (Foreign Key zu customers, products UND delivery_notes!)
            # MUSS VOR Lieferscheinen gelöscht werden!
            count = ConsignmentStock.query.delete()
            print(f"   ✓ {count} Kommissionslager-Einträge gelöscht")

            # 8. Lieferschein-Items (Foreign Key zu delivery_notes)
            count = DeliveryNoteItem.query.delete()
            print(f"   ✓ {count} Lieferschein-Positionen gelöscht")

            # 9. Lieferscheine
            count = DeliveryNote.query.delete()
            print(f"   ✓ {count} Lieferscheine gelöscht")

            # 10. Produkte
            count = Product.query.delete()
            print(f"   ✓ {count} Produkte gelöscht")

            # Auto-Increment Sequenzen zurücksetzen
            print("\n🔄 Setze Auto-Increment Sequenzen zurück...")
            tables = [
                "invoices",
                "line_items",
                "products",
                "delivery_notes",
                "delivery_note_items",
                "consignment_stock",
                "payment_checks",
                "reminders",
                "invoice_status_log",
                "invoice_pdf_archive",
            ]

            for table in tables:
                try:
                    db.session.execute(text(f"ALTER SEQUENCE {table}_id_seq RESTART WITH 1;"))
                    print(f"   ✓ {table}_id_seq zurückgesetzt")
                except Exception:
                    print(f"   ℹ️  {table}: Sequenz nicht gefunden (ok wenn Tabelle leer war)")

            db.session.commit()

            # Zähle nach dem Löschen
            print("\n📊 Verbleibende Einträge:")
            print(f"   - Kunden: {Customer.query.count()}")
            print(f"   - Rechnungen: {Invoice.query.count()}")
            print(f"   - Produkte: {Product.query.count()}")

            print("\n" + "=" * 60)
            print("✅ Datenbank erfolgreich bereinigt!")
            print("💾 Kundendaten wurden beibehalten.")
            print("🔄 Sie können nun mit frischen Daten beginnen.")

        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Fehler bei Bereinigung: {e}")
            import traceback

            traceback.print_exc()
            raise


if __name__ == "__main__":
    cleanup_database()
