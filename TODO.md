# TODO.md

Offene Punkte, die noch nicht erledigt sind. Items nach Erledigung hier
entfernen (nicht abhaken stehen lassen).

## Phase 1: Aufraeumen

### KRITISCHER BUG: Manuelle Rechnungserstellung funktioniert nie (TypeError)

Gefunden 2026-09-05 beim Schreiben der Testsuite, **live gegen die echte
MariaDB-Instanz auf dem Testcontainer verifiziert** (kein SQLite-
Artefakt): Jede Rechnung, die ueber das manuelle Formular `/invoices/new`
erstellt wird, schlaegt beim Speichern fehl mit
`TypeError: unsupported operand type(s) for *: 'float' and 'decimal.Decimal'`.

**Ursache:** `create_invoice()` (app.py:847-853) erzeugt `LineItem`-
Objekte mit `quantity=float(qty)`/`unit_price=float(price)` (reine
Python-`float`, keine `Decimal`). `LineItem.calculate_total()`
(models.py:481-484) setzt darauf `self.total = self.quantity * self.unit_price`
-- `total` wird dadurch ebenfalls `float`, weil SQLAlchemy die
`db.Numeric`-Spaltenkonvertierung zu `Decimal` erst beim naechsten
DB-Flush vornimmt (der hier noch nicht stattgefunden hat -- `calculate_totals()`
und `generate_hash()` laufen VOR `db.session.add(invoice)`, app.py:858-862).
`Invoice.calculate_totals()` (models.py:369) rechnet dann
`item.total * (Decimal(...) / Decimal("100"))` -- `float * Decimal` wirft
den `TypeError`. Der Fehler wird vom generischen `except Exception`
(app.py:868) abgefangen: Nutzer sieht nur "Fehler beim Erstellen der
Rechnung: unsupported operand type(s)...", keine Rechnung wird angelegt.

**Warum es niemandem aufgefallen sein muss:** `create_invoice_from_consignment()`
(app.py:2726-2738, Lieferschein-Abrechnung) und der POS-Flow uebergeben
Betraege bereits als `Decimal`, sind also nicht betroffen -- nur der
Weg ueber das manuelle Rechnungsformular ist kaputt.

- [ ] `app.py:850-851`: `float(qty)`/`float(price)` durch
      `Decimal(qty)`/`Decimal(price)` ersetzen (`from decimal import Decimal`
      ist in app.py bereits importiert)
- [ ] `app.py:814`: `tax_rate = float(request.form.get("tax_rate", ...))`
      hat dieselbe Falle -- ebenfalls auf `Decimal` umstellen
- [ ] Nach dem Fix: Regressionstest in `tests/routes_smoke_test.py`
      (`test_create_invoice_post_creates_invoice_and_customer`) muss
      dann gruen laufen -- aktuell rot (Ist-Zustand dokumentiert im Test)
- [ ] `app.py:1674`/`app.py:1713` (`Product.price = float(...)`) geprueft:
      unkritisch, da `Product` direkt committed wird ohne Zwischenrechnung
      mit `Decimal`-Werten vor dem Flush -- kein Fix noetig, nur vermerkt

### Bug: Kommissionsbestand-Rueckbuchung schlaegt fehl (AttributeError)

Gefunden 2026-09-05 beim Schreiben der Testsuite (siehe TODO.md
"Testsuite bauen" unten), noch NICHT gefixt (Characterization Tests
schreiben Ist-Verhalten fest, aendern es nicht):

`app.py:1003` (`delete_invoice`) greift auf `stock.quantity_remaining`
zu -- dieses Feld existiert nicht in `ConsignmentStock` (models.py:665ff
hat nur `quantity` und `quantity_sold`). Reproduzierbar: eine Rechnung
mit `customer_type="reseller"` entsteht real ueber
`create_invoice_from_consignment()` (app.py:2732, Lieferschein-
Abrechnung) -- wird ein solcher `draft` geloescht, wirft die
Bestandsrueckbuchung einen `AttributeError`, der vom umschliessenden
`except Exception` abgefangen wird: die gesamte Loeschung wird
zurueckgerollt (`db.session.rollback()`), Nutzer sieht nur eine generische
Fehlermeldung, keine Rechnung wird geloescht -- kein stiller
Datenverlust, aber eine irrefuehrende Fehlermeldung und eine kaputte
Funktion.

Vermutlich derselbe Bug betrifft NICHT `update_invoice_status()`
(app.py:938, Storno-Pfad) -- dort wird korrekt `stock.quantity`
verwendet. Nur die Entwurfs-Loeschung ist betroffen.

- [ ] `app.py:1003`: `stock.quantity_remaining` -> `stock.quantity`
- [ ] Pruefen, ob es weitere Stellen mit `quantity_remaining` gibt
      (`grep -rn quantity_remaining`)
- [ ] Nach dem Fix: Regressionstest ergaenzen (Entwurf mit
      `customer_type="reseller"` + Kommissionsbestand loeschen, Bestand
      muss korrekt zurueckgebucht werden)

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
