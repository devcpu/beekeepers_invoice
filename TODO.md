# TODO.md

Offene Punkte, die noch nicht erledigt sind. Items nach Erledigung hier
entfernen (nicht abhaken stehen lassen).

## Phase 1: Aufraeumen

### 1. Postgres/MariaDB-Altlasten entfernen

**Offene Vorfrage, bevor dieser Punkt angegangen wird: Laeuft irgendwo
noch eine PostgreSQL-Installation dieser App (z.B. eine sehr alte, nicht
migrierte Instanz)?** Falls nein, sind folgende vier Stellen sichere
Aufraeum-Kandidaten (Details: AGENTS.md "Postgres/MariaDB-Inkonsistenz"):

- [ ] `psycopg2-binary` aus requirements.txt entfernen
- [ ] `config.py`-Default fuer `DATABASE_URL` von
      `postgresql://localhost/rechnungen` auf einen MariaDB-Connection-String
      umstellen
- [ ] `dialect = postgres` in setup.cfg (SQLFluff) auf den tatsaechlich
      genutzten Dialekt (MariaDB/MySQL) umstellen
- [ ] `fix_permissions.sql` loeschen (Postgres-`GRANT`-Syntax, keine
      Referenzen im Code gefunden)

### 2. Verwaistes Migrationsverzeichnis loeschen

- [ ] `migrations/` (nur `add_totp_required.py`, `create_users_table.py`)
      loeschen. Undokumentiert (taucht in MIGRATIONS.md nicht auf), kein
      Code liest daraus, Alembic ist der aktuelle Migrationsweg.

**Nicht anfassen:** `migrations_archive/` bleibt bewusst liegen -- in
MIGRATIONS.md (Zeile 277-281) explizit als Referenz/Dokumentation der
Schema-Evolution begruendet, nicht dieselbe Kategorie wie `migrations/`.

### 3. Verwaiste Einmal-Skripte pruefen und ggf. loeschen

- [ ] `debug_hash.py` -- keine externen Referenzen gefunden. Loeste einen
      konkreten, laengst behobenen Hash-Verifikations-Bug. Vor dem
      Loeschen kurz pruefen, ob der Debugging-Ansatz als Beispiel-Pattern
      erhaltenswert ist (z.B. als Kommentar/Snippet in AGENTS.md), sonst
      loeschen.
- [ ] `regenerate_hashes.py` -- nur Selbstaufruf (Zeile 38), keine externen
      Referenzen. War ein einmaliges Migrationsskript fuer einen
      Hash-Format-Wechsel. Gleiches Vorgehen wie oben.

### 4. Tote Umgebungsvariablen entfernen oder tatsaechlich aktivieren

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

### 5. Doppelten Code zusammenfuehren

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
