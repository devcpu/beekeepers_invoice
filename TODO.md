# TODO.md

Offene Punkte, die noch nicht erledigt sind. Items nach Erledigung hier
entfernen (nicht abhaken stehen lassen).

## Phase 1: Aufraeumen

Alle bekannten Aufraeumpunkte sind erledigt (siehe "Erledigt" unten).
Neue Punkte hier ergaenzen, sobald sie auffallen.

## Phase 2: Refaktorisieren

**Tests einfuehren: erledigt** (2026-09-05, siehe Plan-Datei
`joyful-swinging-forest.md`). 76 Tests in `tests/` (Modell-Logik,
Route-Tests, GoBD-kritische End-to-End-Pfade), `pytest`-Hook in
`.pre-commit-config.yaml` aktiviert. Beim Schreiben 4 Bugs gefunden und
behoben (siehe "Erledigt" unten und AGENTS.md). E-Mail-Parser-Tests
(`email_parser.py` mit IMAP-Mocking) sind noch NICHT geschrieben --
optionale Ergaenzung, kein Blocker fuer Phase-2-Rest.

Folgende Punkte sind weiterhin bewusst noch keine Aufgaben, sondern
Vorschlaege. Vor Umsetzung jeweils einzeln besprechen:

- **app.py aufteilen**: 3335 Zeilen, praktisch alle ~65 Routen als
  verschachtelte Funktionen in `create_app()`. Ein Split in
  Flask-Blueprints (z.B. nach Domaene: invoices, customers, products,
  delivery_notes, auth, pos, api) wuerde Navigierbarkeit und Testbarkeit
  verbessern. Mit der jetzt vorhandenen Testsuite als Sicherheitsnetz
  risikoaermer als zuvor -- aber `url_for()`/Template-Referenzen muessen
  bei einem Blueprint-Praefix konsequent mitgeaendert werden (siehe
  Plan-Datei, Abschnitt "Bekannte Unbekannte & Risiken").
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
- [x] Testsuite aufgebaut (76 Tests: Modell-Logik, Routen, GoBD-Workflows),
      `pytest` in requirements.txt und `.pre-commit-config.yaml` aktiviert,
      `tests/conftest.py` funktioniert ohne manuelle ENV-Variablen.
- [x] Bug behoben: Dashboard (`/`) stuerzte mit `TypeError: 'datetime.datetime'
      object is not callable` ab, sobald eine `sent`-Rechnung >10 Tage
      ueberfaellig war (`now` im Template-Context war ein bereits
      ausgewertetes `datetime`-Objekt statt einer Funktionsreferenz).
- [x] Bug behoben: Storno einer `paid`-Rechnung protokollierte im
      `InvoiceStatusLog` faelschlich `old_status="sent"` statt `"paid"`
      (Status wurde vor der `old_status`-Berechnung bereits mutiert).
      GoBD-relevant: Audit-Trail war dadurch falsch. Details: AGENTS.md.
