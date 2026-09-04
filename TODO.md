# TODO.md

Offene Punkte, die noch nicht erledigt sind. Items nach Erledigung hier
entfernen (nicht abhaken stehen lassen).

## Phase 1: Aufraeumen

Alle bekannten Aufraeumpunkte sind erledigt (siehe "Erledigt" unten).
Neue Punkte hier ergaenzen, sobald sie auffallen.

## Phase 2: Refaktorisieren (noch nicht beschlossen -- Optionen, keine Auftraege)

Diese Punkte sind bewusst noch keine Aufgaben, sondern Vorschlaege fuer
nach Phase 1. Vor Umsetzung jeweils einzeln besprechen.

- **Tests einfuehren**: Aktuell existiert kein einziger Test, obwohl
  `setup.cfg` bereits eine `[tool:pytest]`-Sektion hat. `pytest` fehlt in
  requirements.txt, der pytest-Hook in `.pre-commit-config.yaml` ist
  auskommentiert. Aufwand: mittel (Grundgeruest) bis hoch (Abdeckung der
  GoBD-kritischen Pfade: Steuerberechnung, Storno-Flow, Hash-Generierung,
  Reseller-Kommissionslogik).
- **app.py aufteilen**: 3335 Zeilen, praktisch alle ~65 Routen als
  verschachtelte Funktionen in `create_app()`. Ein Split in
  Flask-Blueprints (z.B. nach Domaene: invoices, customers, products,
  delivery_notes, auth, pos, api) wuerde Navigierbarkeit und Testbarkeit
  verbessern. Aufwand: hoch, hohes Regressionsrisiko ohne Tests --
  deshalb sinnvollerweise NACH Einfuehrung von Tests angehen.
- **Rechnungsnummern-Generierung, Steuerberechnung, PDF-Erzeugung**:
  ggf. aus app.py in eigene Service-Module extrahieren (aehnlich
  `delivery_note_service.py`), sobald ein Blueprint-Split ansteht.

## Erledigt (zur Referenz, aus vorherigen Sessions)

- [x] Cloudflare durch http.net als DNS-Challenge-Provider ersetzt
- [x] `/health`-Endpoint SQLAlchemy-2.x-Bug behoben (`text("SELECT 1")`)
- [x] `docker-compose.test.yml` fuer LAN-Probelauf ohne Traefik erstellt
- [x] `.instructions.md` und `.copilot-instructions.md` in AGENTS.md
      eingearbeitet und geloescht
- [x] PRE_COMMIT_SETUP.md und SETUP_INTEGRATED.md korrigiert (veraltete
      Angaben, nicht-existente Befehle)
- [x] Postgres/MariaDB-Altlasten entfernt: `psycopg2-binary` aus
      requirements.txt, `config.py`-Defaults auf MariaDB umgestellt,
      SQLFluff-Dialekt auf `mysql`, `fix_permissions.sql` geloescht
- [x] Verwaistes `migrations/`-Verzeichnis geloescht (`migrations_archive/`
      bleibt bewusst erhalten, siehe MIGRATIONS.md)
- [x] `debug_hash.py` und `regenerate_hashes.py` geloescht. Befund:
      `regenerate_hashes.py` haette bei erneutem Lauf den
      Manipulationsschutz bestehender Rechnungen rueckwirkend
      ausgehebelt (ueberschrieb `data_hash` per Commit); `debug_hash.py`
      war zudem bereits mit einem veralteten Hash-Schema inkonsistent.
      Details/Lehre daraus: AGENTS.md Abschnitt "Dead Ends".
- [x] Tote Umgebungsvariablen `SESSION_TYPE`/`SESSION_FILE_DIR`/
      `SESSION_REDIS`/`JWT_SECRET_KEY` komplett entfernt (Entscheidung:
      entfernen statt aktivieren) -- aus docker-compose.yml,
      docker-compose.test.yml, docker-compose.integrated.yml,
      .env.docker, README.md und SETUP_INTEGRATED.md. App nutzt weiterhin
      Standard-Client-Cookie-Sessions, JWT nutzt weiterhin `SECRET_KEY`.
- [x] `add_fold_and_punch_marks()` (DIN-5008-Faltmarken) war dreifach
      dupliziert (`pdf_service.py`, `delivery_note_service.py`,
      `reminder_service.py`) -- in `pdf_utils.py` zusammengefuehrt, alle
      drei Module importieren jetzt von dort.
- [x] Dockerfile: `postgresql-client`/`libpq-dev` entfernt (Ueberrest
      von `psycopg2-binary`, das bereits vorher entfernt wurde).
- [x] **KRITISCHER BUG behoben**: manuelle Rechnungserstellung
      (`/invoices/new`) konnte NIE erfolgreich eine Rechnung anlegen
      (`TypeError: unsupported operand type(s) for *: 'float' and
      'decimal.Decimal'`) -- `create_invoice()` konstruierte
      `tax_rate`/`LineItem.quantity`/`LineItem.unit_price` mit rohem
      `float()` statt `Decimal()`. Fix live gegen die echte MariaDB-
      Instanz auf dem Testcontainer verifiziert (2026-09-05), nicht nur
      in Tests. Details/Ursache: AGENTS.md.
- [x] Bug behoben: `stock.quantity_remaining` (nicht existierendes Feld)
      -> `stock.quantity` in `delete_invoice()` -- verhinderte die
      Kommissionsbestand-Rueckbuchung beim Loeschen von
      Reseller-Entwuerfen mit einem `AttributeError`.
