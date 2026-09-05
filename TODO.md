# TODO.md

Offene Punkte, die noch nicht erledigt sind. Items nach Erledigung hier
entfernen (nicht abhaken stehen lassen).

## Phase 1: Aufraeumen

Alle bekannten Aufraeumpunkte sind erledigt (siehe "Erledigt" unten). Neue
Punkte hier ergaenzen, sobald sie auffallen.

## Honig-Rueckverfolgbarkeit -- Phase 1b und Phase 2

**Phase 1 (Eimer/Charge/Abfuellung fuer Honig): erledigt** (2026-09-05, siehe
Plan-Datei `enumerated-honking-otter.md`). Neue Modelle `HonigEimer`,
`HonigCharge`, `AbfuellCharge`, `AbfuellungQuelle`, `AbfuellErgebnis`, neues
Blueprint `blueprints/production.py`, 21 neue Tests in
`tests/production_test.py`. Details: AGENTS.md Abschnitt
"Honig-Rueckverfolgbarkeit".

Folgende zwei Ausbaustufen sind bewusst noch keine Aufgaben, sondern mit dem
Nutzer abgestimmte Designentscheidungen, die bei spaeterer Umsetzung nicht neu
verhandelt werden muessen (Details in `enumerated-honking-otter.md`):

- **Phase 1b -- Wachs/Propolis/Pollen-Rueckverfolgbarkeit**: analoges
  Behaelter+Charge-Modell wie bei Honig, aber mit eigenen Feldern (z.B.
  Einschmelzdatum statt Schleudertag bei Wachs). Noch nicht spezifiziert, vor
  Umsetzung mit dem Nutzer klaeren, welche Felder pro Rohstoffart tatsaechlich
  gebraucht werden.
- **Phase 2 -- Verkauf chargenbewusst machen**: `LineItem`/`DeliveryNoteItem`
  bekommen zwei nullable FKs (`abfuell_ergebnis_id`, `honig_charge_id` fuer den
  Rohware-Ausnahmefall), `ConsignmentStock` wird chargengenau (Unique-
  Constraint erweitert um `abfuell_ergebnis_id`, betrifft 6 Stellen in
  `delivery_notes.py`/`pos.py`/`invoices.py`), `Product.number` wird aus Chargen
  abgeleitet statt inkrementell gepflegt (braucht eine synthetische
  "Bestandsuebernahme"-Charge fuer bestehenden Bestand in der Migration),
  `Invoice.generate_hash()` bekommt ein versioniertes Hash-Format
  (`hash_version`, alte Rechnungen bleiben unter dem alten Format pruefbar --
  kein Rehash bestehender Daten). Vorab zu klaeren/verifizieren:
  `api_pos_complete_sale()` (`blueprints/api.py:225-313`) hat denselben
  float/Decimal-Bugtyp wie das ehemals kaputte `create_invoice()`, ist aber
  bisher ungetestet -- Regressionstest schreiben, bevor dort LineItem-Code fuer
  Charge-Referenzen angefasst wird.

## Phase 2: Refaktorisieren

**Tests einfuehren: erledigt** (2026-09-05, siehe Plan-Datei
`joyful-swinging-forest.md`). 76 Tests in `tests/` (Modell-Logik, Route-Tests,
GoBD-kritische End-to-End-Pfade), `pytest`-Hook in `.pre-commit-config.yaml`
aktiviert. Beim Schreiben 4 Bugs gefunden und behoben (siehe "Erledigt" unten
und AGENTS.md). E-Mail-Parser-Tests (`email_parser.py` mit IMAP-Mocking) sind
noch NICHT geschrieben -- optionale Ergaenzung, kein Blocker fuer Phase-2-Rest.

Folgende Punkte sind weiterhin bewusst noch keine Aufgaben, sondern Vorschlaege.
Vor Umsetzung jeweils einzeln besprechen:

- **Steuerberechnung, PDF-Erzeugung weiter aus den Blueprints extrahieren**:
  Rechnungsnummern-Generierung ist bereits in `invoice_numbering.py`
  ausgelagert. Steuerberechnungslogik und PDF-Erzeugungsaufrufe liegen aber
  weiterhin direkt in den jeweiligen Blueprint-Routen (`blueprints/invoices.py`,
  `blueprints/delivery_notes.py`). Eine weitere Extraktion in eigene
  Service-Module (aehnlich `delivery_note_service.py`) waere jetzt, nach dem
  abgeschlossenen Blueprint-Split, risikoarm moeglich, ist aber weiterhin nur
  ein Vorschlag, keine Aufgabe.

## Erledigt (zur Referenz, aus vorherigen Sessions)

- [x] Cloudflare durch http.net als DNS-Challenge-Provider ersetzt
- [x] `/health`-Endpoint SQLAlchemy-2.x-Bug behoben (`text("SELECT 1")`)
- [x] `docker-compose.test.yml` fuer LAN-Probelauf ohne Traefik erstellt
- [x] `.instructions.md` und `.copilot-instructions.md` in AGENTS.md
  eingearbeitet und geloescht
- [x] PRE_COMMIT_SETUP.md und SETUP_INTEGRATED.md korrigiert (veraltete Angaben,
  nicht-existente Befehle)
- [x] Postgres/MariaDB-Altlasten entfernt: `psycopg2-binary` aus
  requirements.txt, `config.py`-Defaults auf MariaDB umgestellt,
  SQLFluff-Dialekt auf `mysql`, `fix_permissions.sql` geloescht
- [x] Verwaistes `migrations/`-Verzeichnis geloescht (`migrations_archive/`
  bleibt bewusst erhalten, siehe MIGRATIONS.md)
- [x] `debug_hash.py` und `regenerate_hashes.py` geloescht. Befund:
  `regenerate_hashes.py` haette bei erneutem Lauf den Manipulationsschutz
  bestehender Rechnungen rueckwirkend ausgehebelt (ueberschrieb `data_hash` per
  Commit); `debug_hash.py` war zudem bereits mit einem veralteten Hash-Schema
  inkonsistent. Details/Lehre daraus: AGENTS.md Abschnitt "Dead Ends".
- [x] Tote Umgebungsvariablen `SESSION_TYPE`/`SESSION_FILE_DIR`/
  `SESSION_REDIS`/`JWT_SECRET_KEY` komplett entfernt (Entscheidung: entfernen
  statt aktivieren) -- aus docker-compose.yml, docker-compose.test.yml,
  docker-compose.integrated.yml, .env.docker, README.md und SETUP_INTEGRATED.md.
  App nutzt weiterhin Standard-Client-Cookie-Sessions, JWT nutzt weiterhin
  `SECRET_KEY`.
- [x] `add_fold_and_punch_marks()` (DIN-5008-Faltmarken) war dreifach dupliziert
  (`pdf_service.py`, `delivery_note_service.py`, `reminder_service.py`) -- in
  `pdf_utils.py` zusammengefuehrt, alle drei Module importieren jetzt von dort.
- [x] Dockerfile: `postgresql-client`/`libpq-dev` entfernt (Ueberrest von
  `psycopg2-binary`, das bereits vorher entfernt wurde).
- [x] **KRITISCHER BUG behoben**: manuelle Rechnungserstellung (`/invoices/new`)
  konnte NIE erfolgreich eine Rechnung anlegen
  (`TypeError: unsupported operand type(s) for *: 'float' and     'decimal.Decimal'`)
  -- `create_invoice()` konstruierte
  `tax_rate`/`LineItem.quantity`/`LineItem.unit_price` mit rohem `float()` statt
  `Decimal()`. Fix live gegen die echte MariaDB- Instanz auf dem Testcontainer
  verifiziert (2026-09-05), nicht nur in Tests. Details/Ursache: AGENTS.md.
- [x] Bug behoben: `stock.quantity_remaining` (nicht existierendes Feld) ->
  `stock.quantity` in `delete_invoice()` -- verhinderte die
  Kommissionsbestand-Rueckbuchung beim Loeschen von Reseller-Entwuerfen mit
  einem `AttributeError`.
- [x] Testsuite aufgebaut (76 Tests: Modell-Logik, Routen, GoBD-Workflows),
  `pytest` in requirements.txt und `.pre-commit-config.yaml` aktiviert,
  `tests/conftest.py` funktioniert ohne manuelle ENV-Variablen.
- [x] Bug behoben: Dashboard (`/`) stuerzte mit
  `TypeError: 'datetime.datetime'     object is not callable` ab, sobald eine
  `sent`-Rechnung >10 Tage ueberfaellig war (`now` im Template-Context war ein
  bereits ausgewertetes `datetime`-Objekt statt einer Funktionsreferenz).
- [x] Bug behoben: Storno einer `paid`-Rechnung protokollierte im
  `InvoiceStatusLog` faelschlich `old_status="sent"` statt `"paid"` (Status
  wurde vor der `old_status`-Berechnung bereits mutiert). GoBD-relevant:
  Audit-Trail war dadurch falsch. Details: AGENTS.md.
- [x] **app.py aufteilen** (2026-09-05, siehe Plan-Datei
  `joyful-swinging-forest.md`, Teil B): `app.py` von 3335 auf ~190 Zeilen
  reduziert (nur noch App-Factory, Blueprint-Registrierung, `/health`,
  CLI-Commands). Alle ~65 Routen in 10 Flask-Blueprints unter `blueprints/`
  verschoben (main, auth, api, products, customers, pos, reports, users,
  delivery_notes, invoices). `role_required`-Decorator nach `auth_utils.py`,
  `generate_invoice_number()` nach `invoice_numbering.py` ausgelagert. Alle ~183
  `url_for()`-Aufrufe in app.py und Templates auf
  `<blueprint>.<funktion>`-Endpoints umgestellt. Neuer Test
  `tests/endpoints_test.py` als Sicherheitsnetz gegen falsche/vergessene
  Endpoint-Praefixe. 80 Tests gruen (vorher 76). Details: AGENTS.md Abschnitt
  "Blueprint-Struktur".
