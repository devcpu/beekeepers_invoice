# Historische Migrationen (Archiv)

Diese Migrations-Dateien wurden für schrittweise Schema-Updates während der Entwicklung verwendet.

## Status

**Nicht mehr benötigt** – Alle Schema-Änderungen sind bereits in `models.py` integriert.

Bei Neuinstallationen wird `flask init-db` verwendet, das alle Tabellen direkt aus den aktuellen Models erstellt.

## Archivierte Migrationen

- `migrate_add_products.py` - Produktverwaltung
- `migrate_add_tax_model.py` - Steuersätze
- `migrate_email_optional.py` - E-Mail optional
- `migrate_add_reseller_price.py` - Wiederverkäuferpreise
- `migrate_protect_hash.py` - Hash-Schutz
- `migrate_add_payment_checks.py` - Zahlungsprüfungen
- `migrate_add_product_tax_rate.py` - Produkt-Steuersätze
- `migrate_add_lineitem_tax_rate.py` - Positionssteuersätze
- `migrate_add_reminders.py` - Mahnwesen
- `migrate_add_consignment.py` - Kommissionsware
- `migrate_add_gobd_tables.py` - GoBD-Konformität
- `migrate_add_password_reset.py` - Passwort-Reset

## Für Produktivdatenbanken

Falls eine bestehende Produktivdatenbank aktualisiert werden muss, können diese Skripte als Referenz dienen.
