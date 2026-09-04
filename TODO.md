# TODO.md

Offene Punkte, die noch nicht erledigt sind. Items nach Erledigung hier
entfernen (nicht abhaken stehen lassen).

## Phase 1: Aufraeumen

### Tote Umgebungsvariablen entfernen oder tatsaechlich aktivieren

Verifizierte Fallen (Details: AGENTS.md "Gesetzt, aber wirkungslos"):

- [ ] `SESSION_TYPE` / `SESSION_FILE_DIR`: `flask-session` ist nicht
      installiert, die Variablen wirken nicht. Entscheidung noetig:
      **(a)** Variablen aus docker-compose.yml, docker-compose.test.yml
      und .env.docker entfernen (App nutzt ohnehin Client-Cookie-Sessions),
      oder **(b)** `flask-session` in requirements.txt aufnehmen und in
      app.py per `Session(app)` tatsaechlich aktivieren.
- [ ] `JWT_SECRET_KEY` in docker-compose.integrated.yml: wird von
      jwt_api.py nicht gelesen (nutzt `SECRET_KEY`). Entscheidung noetig:
      **(a)** Variable entfernen, oder **(b)** jwt_api.py auf einen
      separaten Key umstellen (staerkere Trennung von Session- und
      API-Secrets).

### Doppelten Code zusammenfuehren

- [ ] `add_fold_and_punch_marks()` (DIN-5008-Faltmarken) ist identisch in
      `delivery_note_service.py` und `reminder_service.py` dupliziert.
      In ein gemeinsames Modul auslagern (z.B. `pdf_utils.py`).

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
