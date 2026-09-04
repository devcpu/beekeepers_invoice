# AGENTS.md

Technische Referenz fuer die Arbeit am Code. Zielgruppe: KI-Agenten und
Entwickler, die aendern statt nur lesen. Coding-Style-Regeln (Naming,
Formatierung, Commits) stehen in `.instructions.md` -- hier nur, was
`.instructions.md` nicht abdeckt: Struktur, Fallen, Dead Ends.

`.copilot-instructions.md` ist eine aeltere Momentaufnahme (Postgres als
Primaer-DB, andere Migrations-Struktur) -- bei Widerspruch gilt
`.instructions.md` und dieses Dokument.

## Ueberblick

Flask-3.0-App (App-Factory-Pattern, `create_app()`), SQLAlchemy-ORM,
Jinja2-Templates. Fachlicher Zweck und Domaenenmodell stehen in
PROJECT.md -- hier nur Technisches.

## app.py ist ein Monolith -- so navigierst du darin

`app.py` hat 3335 Zeilen und enthaelt praktisch alle ~65 Routen als
verschachtelte Funktionen innerhalb von `create_app()`. Das ist bekannt
und bewusst in Kauf genommen (`# pylint: disable=too-many-lines` steht
am Dateikopf).

- Lies die Datei NIE komplett. Grep nach Abschnittsmarkern
  (`# ===`, z.B. `# ========== HAUPTSEITEN-ROUTEN ==========`) oder nach
  `@app.route`, um die Stelle zu finden, die du brauchst.
- CLI-Commands (`flask init-db`, `flask seed-db`) liegen ganz am Ende der
  Datei, ebenfalls innerhalb von `create_app()`.
- Flask registriert `@app.cli.command()`-Funktionsnamen mit Unterstrichen
  automatisch als Bindestrich-Commands: `init_db` im Code heisst auf der
  Kommandozeile `flask init-db`, nicht `flask init_db`.

## Modulkarte

| Datei | Zweck |
|---|---|
| `app.py` | App-Factory, alle Routen, CLI-Commands |
| `models.py` | 13 SQLAlchemy-Modelle, mit GoBD-Hinweisen im Docstring |
| `config.py` | Config-Klassen (Development/Production/Testing), liest alle ENV-Variablen |
| `delivery_note_service.py` | PDF-Erzeugung Lieferscheine (ReportLab, DIN-5008-Faltmarken) |
| `reminder_service.py` | PDF-Erzeugung Mahnungen (eigene Kopie der Faltmarken-Logik, siehe Dead Ends) |
| `pdf_service.py` | Rechnungs-PDF + EPC-QR-Code fuer SEPA-Ueberweisung |
| `email_service.py` | Rechnungsversand + genereller Mailversand via Flask-Mail |
| `email_parser.py` | IMAP-Client, liest Shop-Bestellmails ein |
| `jwt_api.py` | JWT-Erzeugung/-Pruefung + Decorators fuer die PWA-API, unabhaengig von Flask-Login |
| `password_reset.py` | Token-basierter Passwort-Reset-Flow |
| `crowdsec_app.py` | Middleware, loggt 4xx/5xx/Failed-Logins nach `logs/security.log` fuer CrowdSec |
| `cleanup_database.py` | Wartungsskript zur Datenbereinigung |
| `migrate.py` | Alembic-Wrapper, liest `DATABASE_URL` aus `.env` |
| `seed_reseller_test_data.py` | Testdaten-Generator fuer Reseller-Szenarien |
| `debug_hash.py` | Einmalig genutztes Debug-Skript zu einem behobenen Hash-Verifikations-Bug |
| `regenerate_hashes.py` | Einmaliges Migrationsskript, hat alle Invoice-Hashes neu berechnet |
| `fix_permissions.sql` | Postgres-GRANT-Fix -- nur relevant bei PostgreSQL-Betrieb, nicht bei MariaDB |
| `generate_icons.py` | Generiert PWA-Icons in versch. Groessen aus einer Quellgrafik |

`debug_hash.py` und `regenerate_hashes.py` loesten einen konkreten,
bereits behobenen Bug (Hash-Format-Aenderung). Sie laufen nicht
automatisiert und sind primaer als Beispiel-Pattern interessant, falls
ein aehnlicher Migrations-/Hash-Bug erneut auftritt.

## Datenbank & Migrationen

Aktuell und gewollt: **Alembic** (`alembic.ini`, `alembic/versions/`).
Enthaelt aktuell eine konsolidierte Migration
(`352cafa6cd86_initial_schema_from_models.py`), aus dem Ist-Stand der
Models generiert. Details und der Umstieg von `flask init-db` per
`alembic stamp head` stehen in MIGRATIONS.md.

`flask init-db` legt weiterhin Tabellen an (fuer Frischinstallationen)
sowie einen Standard-Admin `admin`/`admin` und den internen
"Marktstand"-Systemkunden. Es ersetzt Alembic nicht fuer
Schema-Aenderungen an einer bestehenden Datenbank -- fuer die nutzt du
`alembic revision` / `alembic upgrade head`.

### Dead Ends (nicht anfassen, nicht als aktuell missverstehen)

- **`migrations_archive/`** (12 Dateien + eigenes README): das alte,
  handgeschriebene Ad-hoc-Migrationssystem vor Alembic. In MIGRATIONS.md
  explizit als archiviert bezeichnet. Kein Code liest daraus.
- **`migrations/`** (nur `add_totp_required.py`, `create_users_table.py`):
  ein noch aelterer, undokumentierter Zwischenstand -- taucht in
  MIGRATIONS.md gar nicht auf. Nicht der aktuelle Migrationsweg. Wirkt
  auf den ersten Blick wie ein aktives Verzeichnis, ist es aber nicht --
  bei Schema-Aenderungen ausschliesslich Alembic verwenden.

## Konfiguration & Umgebungsvariablen

### Von der App tatsaechlich gelesen (config.py)

`SECRET_KEY`, `DATABASE_URL`, `UPLOAD_FOLDER`, `PDF_FOLDER`,
`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`,
`MAIL_USE_SSL`, `MAIL_USE_TLS`, `MAIL_DEFAULT_SENDER`, `IMAP_SERVER`,
`IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`, `IMAP_USE_SSL`,
`API_TOKEN_EXPIRY_DAYS`, `TOTP_ISSUER_NAME`, `COMPANY_NAME`,
`COMPANY_HOLDER`, `COMPANY_STREET`, `COMPANY_ZIP`, `COMPANY_CITY`,
`COMPANY_COUNTRY`, `COMPANY_EMAIL`, `COMPANY_PHONE`, `COMPANY_TAX_ID`,
`COMPANY_WEBSITE`, `BANK_NAME`, `BANK_IBAN`, `BANK_BIC`, `PAYPAL`,
`DEFAULT_TAX_RATE`, `LANDWIRTSCHAFTLICHE_URPRODUKTION_TAX_RATE`

### Gesetzt, aber wirkungslos -- Falle

- `SESSION_TYPE` / `SESSION_FILE_DIR`: werden in docker-compose.yml
  gesetzt, aber `flask-session` ist nicht in requirements.txt und wird
  im Code nicht importiert. Flask nutzt tatsaechlich Standard-
  Client-Cookie-Sessions. Wer Redis-Sessions einschalten will, muss
  `flask-session` zuerst tatsaechlich einbauen (Import + `Session(app)`),
  nicht nur die ENV-Variable setzen.
- `JWT_SECRET_KEY`: wird in docker-compose.integrated.yml gesetzt, aber
  `jwt_api.py` signiert/verifiziert Tokens mit `current_app.config["SECRET_KEY"]`
  (siehe jwt_api.py:30 und :46) -- derselbe Key wie die Flask-Session,
  nicht der separate JWT-Key.

### Deployment-spezifisch (nicht von der App selbst gelesen)

`DOMAIN`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_ROOT_PASSWORD`,
`HTTPNET_API_KEY` (Traefik DNS-Challenge, siehe DOCKER_DEPLOYMENT.md).

## Postgres/MariaDB-Inkonsistenz

Produktiv laeuft **MariaDB** (docker-compose.yml, `pymysql`-Treiber).
Mehrere Stellen zeigen aber noch auf PostgreSQL und sind nicht
nachgezogen:

- `config.py`-Default fuer `DATABASE_URL` ist `postgresql://localhost/rechnungen`
- `psycopg2-binary` steht weiterhin in requirements.txt
- SQLFluff-Konfiguration in setup.cfg hat `dialect = postgres`
- `fix_permissions.sql` enthaelt Postgres-`GRANT`-Syntax

Vor dem Bereinigen pruefen, ob noch irgendein Deployment tatsaechlich
PostgreSQL nutzt (z.B. eine sehr alte Installation) -- sonst sind das
sichere Aufraeum-Kandidaten.

## Doppelter Code

`add_fold_and_punch_marks()` (DIN-5008-Faltmarken fuer den PDF-Druck)
ist identisch in `delivery_note_service.py` und `reminder_service.py`
dupliziert statt in ein gemeinsames Modul ausgelagert. Bei Aenderungen
an der Faltmarken-Logik beide Stellen pruefen.

## Health-Check & SQLAlchemy 2.x

SQLAlchemy 2.x fuehrt rohe SQL-Strings nicht mehr direkt aus. Der
`/health`-Endpoint nutzte `db.session.execute("SELECT 1")` und schlug
deshalb dauerhaft fehl (`ObjectNotExecutableError`) -- behoben durch
`db.session.execute(text("SELECT 1"))` (app.py, `from sqlalchemy import text`).
Falls neuer Code rohes SQL ausfuehrt, immer `sqlalchemy.text(...)` verwenden,
nie einen nackten String an `.execute()` uebergeben.

## Tests

Es existiert kein einziger Test. `setup.cfg` hat zwar eine
`[tool:pytest]`-Sektion (`testpaths = tests`, `python_files = *_test.py`
-- unueblich, Standard waere `test_*.py`), aber:

- Verzeichnis `tests/` existiert nicht
- `pytest` fehlt in requirements.txt
- Der `pytest`-Hook in `.pre-commit-config.yaml` ist auskommentiert

Neue Business-Logik (Steuerberechnung, GoBD-Storno-Flow, Reseller-
Kommissionslogik) sollte nicht ungetestet bleiben -- vor einer groesseren
Aenderung an diesen Bereichen zumindest ein minimales `tests/`-Setup
(pytest + Fixtures) anlegen, statt manuell durchzuklicken.

## Linting & pre-commit

Aktive Hooks (siehe `.pre-commit-config.yaml`, Details in
PRE_COMMIT_SETUP.md): Black, Flake8, isort (alle line-length 160),
djLint (Jinja2), curlylint, ESLint (JS), Bandit (Security), SQLFluff
(lint+fix), Pylint, py-compile, Safety (Dependency-Check).
Auskommentiert: `pytest`, `make_html_doc`.

Coding-Konventionen (Naming, Boolean-Praefixe, Error-Handling,
Commit-Format) stehen vollstaendig in `.instructions.md` -- nicht hier
duplizieren, dort pflegen.

## GoBD-Konformitaet -- beim Aendern beachten

Rechnungen, Zahlungen und Bestandsanpassungen unterliegen expliziten
Unveraenderbarkeits- und Nachvollziehbarkeitsanforderungen (Details in
GOBD_COMPLIANCE.md). Vor Aenderungen an `Invoice`, `InvoiceStatusLog`,
`InvoicePdfArchive`, `StockAdjustment` oder der Storno-Logik
(Korrekturbeleg statt Loeschung) GOBD_COMPLIANCE.md lesen -- diese
Anforderungen sind fachlich vorgegeben, nicht optional refaktorierbar.
