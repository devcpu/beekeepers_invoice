# AGENTS.md

Technische Referenz fuer die Arbeit am Code. Zielgruppe: KI-Agenten und
Entwickler, die aendern statt nur lesen.

## Coding-Style

- **Naming (PEP 8)**: `PascalCase` fuer Klassen, `snake_case` fuer
  Funktionen/Variablen/Datenbankspalten, `ALL_CAPS` fuer Konstanten,
  `_leading_underscore` fuer private Members. Datenbanktabellen: `snake_case`
  Plural. Flask-Routen: kebab-case URLs (`/invoice/create`,
  `/api/customer-list`).
- **Boolean-Praefixe**: `is_` fuer Zustandsabfragen, `has_` fuer Vorhandensein,
  `can_` fuer Faehigkeiten/Rechte, `should_` fuer Empfehlungen, `needs_` fuer
  Anforderungen. Keine doppelten Verneinungen (`is_deleted = False` statt
  `is_not_deleted = True`). Kein `_flag`-Suffix (das Praefix macht es bereits
  eindeutig).
- **Formatierung**: Zeilenlaenge 160 (black/flake8/isort-Konfiguration), 4
  Leerzeichen Einrueckung, Imports per isort sortiert (stdlib -> third-party ->
  lokal), f-strings fuer Formatierung. Ausnahme: nie f-strings in
  Logging-Aufrufen (`logging-fstring-interpolation` vermeiden) --
  `logger.error("...%s...", value)` statt `logger.error(f"...{value}...")`.
- **Fehlerbehandlung**: try/except um DB-Operationen und externe Services, immer
  `logger.error(...)` mit Kontext, Rollback bei DB-Fehlern. `except Exception`
  ist fuer Flask-Routen akzeptiert (bewusste Team-Entscheidung, siehe
  Pylint-Disable-Liste in .pre-commit-config.yaml).
- **Flask-Konventionen**: `@login_required`/`@role_required` fuer geschuetzte
  Routen (siehe Abschnitt "Rollen & Autorisierung" unten), `flash()` fuer
  Nutzer-Feedback, `db.session.commit()` explizit mit Rollback-Pfad, CSRF-Schutz
  fuer Formulare.
- **Commits**: Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`,
  `style:`, `refactor:`), Commit-Nachrichten auf Deutsch, atomar und fokussiert.
  Pre-commit-Hooks formatieren automatisch nach.
- **Markdown-Dokumentation**: Praesens statt Vergangenheit, aktive Stimme,
  direkte Ansprache in der zweiten Person ("du"/"Sie" je nach Zieldatei), Fakten
  und direkte Anweisungen statt Konjunktiv ("koennte"/"wuerde" vermeiden).

## Ueberblick

Flask-3.0-App (App-Factory-Pattern, `create_app()`), SQLAlchemy-ORM,
Jinja2-Templates. Geschaeftsmodell und "warum existiert das" stehen in
PROJECT.md -- hier das Datenmodell und die Code-Patterns, die beim Aendern zu
beachten sind.

## Kern-Entitaeten (models.py)

- **User**: Auth + Rollen (`role`: `admin`, `cashier`, `reseller`),
  TOTP-2FA-Felder, API-Token fuer die PWA, optionale FK `reseller_customer_id`
  fuer Reseller-Self-Service-Logins.
- **Customer**: Kunden, inkl. DSGVO-Anonymisierung (`anonymize_gdpr()`);
  Rechnungsdaten selbst bleiben unveraendert (Aufbewahrungspflicht §147 AO
  ueberwiegt Loeschanspruch).
- **Product**: `price` (Endkunde) und `reseller_price` getrennt,
  produktspezifisches `tax_rate`, `lot_number` (Charge), `number`
  (Hauptbestand).
- **Invoice** + **LineItem** -- siehe eigener Abschnitt unten, GoBD-kritisch.
- **InvoiceStatusLog**, **InvoicePdfArchive**: Audit-Trail, siehe
  GoBD-Abschnitt.
- **DeliveryNote**, **DeliveryNoteItem**, **ConsignmentStock**: Lieferschein-
  und Kommissionslager-Fluss fuer Reseller, siehe eigener Abschnitt unten.
- **PaymentCheck**: Protokoll des automatischen Zahlungsabgleichs.
- **Reminder**: Mahnstufen fuer ueberfaellige Rechnungen.
- **StockAdjustment**: GoBD-dokumentierte Eigenentnahme/Inventur/Verderb/Bruch,
  Begruendung ist Pflichtfeld.

## Steuerberechnung (`Invoice.calculate_totals()`, models.py:338)

Drei `tax_model`-Werte, unterschiedliche Formeln:

- **`standard`**: MwSt. wird auf Netto aufgeschlagen --
  `tax_amount = subtotal * (tax_rate / 100)`, `total = subtotal + tax_amount`.
- **`kleinunternehmer`** (§19 UStG): keine MwSt. -- `tax_amount = 0`,
  `total = subtotal`.
- **`landwirtschaft`** (§24 UStG Durchschnittssatz, z.B. Honig): Brutto = Netto,
  die MwSt. wird pro LineItem aus dem Bruttobetrag zurueckgerechnet --
  `item_tax = item.total * (tax_rate / (100 + tax_rate))`, `total = subtotal`.
  Nutzt dabei die **produktspezifische** `LineItem.tax_rate`, nicht pauschal
  `Invoice.tax_rate` -- wichtig bei gemischten Warenkoerben.

## Rechnungsnummern-Schema

Prefix zeigt die Art des Belegs, Zaehler ist pro Prefix+Tag eigenstaendig:

- `RE-...` normale Rechnung
- `STORNO-YYYYMMDD-####` Stornorechnung (negative Betraege, siehe unten)
- `BAR-YYYYMMDD-####` POS-/Kassenverkauf (sofort `status='paid'`)

## Hash-Generierung -- Reihenfolge ist zwingend

`Invoice.data_hash` ist `nullable=False` (models.py:326) -- das ist ein
DB-Constraint, kein Trigger. `generate_hash()` (models.py:374) haengt aber von
bereits gesetzten `line_items` ab. Zwingende Reihenfolge:

```python
invoice.line_items = line_items_list   # 1. Positionen zuweisen
invoice.calculate_totals()             # 2. Summen berechnen
invoice.generate_hash()                # 3. Hash ueber die fertigen Daten
db.session.add(invoice)                # 4. erst jetzt zur Session
db.session.commit()
```

Hash NACH `add()`/`commit()` neu generieren aendert `data_hash` nicht mehr
sinnvoll nachtraeglich, da der Hash exakt den Stand zum Zeitpunkt der Erstellung
abbilden soll (Manipulationsschutz) -- bei jeder Aenderung an dieser Reihenfolge
das GoBD-Kapitel unten beachten.

## KRITISCHER BUG: `float`/`Decimal`-Mischung in `calculate_totals()`

`Invoice`/`LineItem`-Spalten sind `db.Numeric` (werden zu `Decimal` konvertiert
-- aber erst beim naechsten DB-Flush, nicht bei reiner Python-Zuweisung).
`Invoice.calculate_totals()` (models.py:369) multipliziert `item.total` mit
einem `Decimal`-Ausdruck (`Decimal(...) / Decimal("100")`). Werden
`LineItem`-Objekte VOR dem ersten Flush mit rohen `float`-Werten konstruiert,
bleibt `item.total` nach `calculate_total()` (models.py:481-484) ein `float`.
`float * Decimal` wirft
`TypeError: unsupported operand type(s) for *: 'float' and 'decimal.Decimal'`.

**War in der urspruenglichen Codebasis ein echter Bug** (live gegen MariaDB
verifiziert, 2026-09-05): `create_invoice()` konstruierte `LineItem`-Objekte mit
rohem `float()` statt `Decimal()`, wodurch das manuelle Rechnungsformular
`/invoices/new` niemals erfolgreich eine Rechnung anlegen konnte. **Behoben** --
`create_invoice()` (`blueprints/invoices.py`) konstruiert
`quantity`/`unit_price` jetzt explizit als `Decimal(...)`.

`create_invoice_from_consignment()` (`blueprints/delivery_notes.py`) und der
POS-Flow (`blueprints/pos.py`) waren nie betroffen, da sie Betraege bereits
explizit als `Decimal(...)` konstruieren, bevor `calculate_totals()` laeuft.

**Lehre fuer neuen Code:** Wird ein SQLAlchemy-Model-Objekt mit
`db.Numeric`-Spalten konstruiert und VOR dem ersten `flush()`/`commit()` in
einer eigenen Berechnung weiterverwendet (wie hier `calculate_totals()`),
muessen alle daran beteiligten Werte bereits explizit `Decimal` sein -- sich auf
die implizite Typkonvertierung durch SQLAlchemy zu verlassen funktioniert nur
nach einem Flush.

## Behobene Bugs aus der Testsuite-Einfuehrung (2026-09-05)

Beim Schreiben von `tests/invoice_workflow_test.py` (GoBD-kritische
End-to-End-Pfade) zwei weitere Bugs gefunden und behoben:

- **Dashboard-Absturz bei ueberfaelligen Rechnungen**: `utility_processor()`
  (`app.py`, Context-Processor in `create_app()`) lieferte `now=datetime.now()`
  (bereits ausgewertetes Objekt) in den Jinja2-Kontext, aber
  `templates/index.html:75` ruft `now()` als **Funktion** auf (`now().date()`).
  Sobald mindestens eine `sent`-Rechnung mehr als 10 Tage ueberfaellig war,
  crashte die Startseite `/` mit
  `TypeError: 'datetime.datetime' object is not callable`. Fix:
  `now=datetime.now` (Funktionsreferenz statt Aufruf) in den Context-Processor.
- **Falscher Audit-Trail-Eintrag bei Storno einer `paid`-Rechnung**:
  `create_cancellation_invoice()` (`blueprints/invoices.py`) setzte
  `original_invoice.status = "cancelled"` **vor** der Berechnung von
  `old_status` fuer den `InvoiceStatusLog`-Eintrag --
  `original_invoice.status != "paid"` war zu diesem Zeitpunkt immer `True`
  (Status ist ja bereits `"cancelled"`), wodurch `old_status` faelschlich immer
  `"sent"` protokolliert wurde, selbst wenn die Original-Rechnung tatsaechlich
  `"paid"` war. GoBD-relevant, da der Audit-Trail dadurch falsch wurde. Fix:
  Ist-Status VOR der Mutation in einer lokalen Variable festhalten (analog zum
  bereits korrekten Pattern in `update_invoice_status()`, ebenfalls
  `blueprints/invoices.py`).

**Bekannter, aber harmloser Code-Smell (nicht gefixt):** In
`create_cancellation_invoice()` fuehrt der erste Guard
(`status not in ["sent", "paid"]`) dazu, dass eine bereits stornierte Rechnung
(`status == "cancelled"`) schon dort abgefangen wird -- der zweite,
spezifischere Guard ("Diese Rechnung wurde bereits storniert.") ist dadurch
unerreichbarer Code. Beide Zweige lehnen korrekt ab, nur die Fehlermeldung ist
ungenau. Kein funktionaler Schaden, daher nicht als Bug behoben, nur vermerkt.

## Reseller-/Kommissionslager-Fluss

1. Lieferschein anlegen (`DeliveryNote`, Status `delivered`) -- Hauptbestand
   (`Product.number`) sinkt, Kommissionsbestand (`ConsignmentStock.quantity`)
   beim Reseller steigt (eindeutig pro `customer_id`+`product_id`).
1. Abrechnung: Rechnung aus dem Lieferschein erzeugen, nur die tatsaechlich
   verkaufte Menge wird abgerechnet -- Lieferschein-Status wechselt zu
   `partially_billed` oder `billed`.
1. Ruecknahme/Storno: Hauptbestand UND Kommissionsbestand beide zurueckbuchen
   (`product.increase_stock(...)` plus `consignment_item.quantity += ...`) --
   eines von beiden zu vergessen ist der haeufigste Fehler in diesem Bereich.

**Ehemaliger Bug, bereits behoben:** `delete_invoice()`
(`blueprints/invoices.py`) griff zuvor faelschlich auf
`stock.quantity_remaining` zu -- dieses Feld existiert nicht in
`ConsignmentStock` (nur `quantity`/`quantity_sold`). Fix: `stock.quantity`,
analog zum bereits korrekten `update_invoice_status()` (Storno-Pfad).

## Honig-Rueckverfolgbarkeit (Eimer/Charge/Abfuellung)

Bildet den Produktionsprozess ab: Ernte -> Eimer -> Abfuellsitzung ->
Chargennummer (= Mindesthaltbarkeitsdatum), rueckverfolgbar bis zum fertigen
Glas. Aktuell nur fuer Honig implementiert (Wachs/Propolis/Pollen sind ein
spaeteres, analoges Behaelter+Charge-Modell mit eigenen Feldern, siehe TODO.md).
Fuenf Modelle in `models.py`, ein eigenes Blueprint `blueprints/production.py`
(`production_bp`, kein URL-Praefix ausser `/production`).

**Datenmodell:**

- **`HonigEimer`**: physischer Behaelter (10-25kg), feste, wiederverwendete
  `eimer_nummer`. Wird NICHT pro Befuellung neu nummeriert -- der Inhalt
  wechselt ueber die `HonigCharge`-Historie, der Eimer selbst bleibt.
  `aktuelle_charge`-Property liefert die aktuell offene Fuellung (falls
  vorhanden, sonst `None`) -- ein Eimer hat immer hoechstens eine offene
  `HonigCharge` gleichzeitig (vom Blueprint erzwungen, nicht per DB-Constraint).
- **`HonigCharge`**: eine Befuellung eines Eimers (Sorte, Schleudertag,
  urspruengliches Gewicht, `restmenge_kg`). `status` ist eine **abgeleitete
  Property** (`voll`/`teilweise_abgefuellt`/`leer`, aus `restmenge_kg` vs.
  `gewicht_kg` berechnet) -- KEINE DB-Spalte, daher kein `filter_by(status=...)`
  moeglich. Offene Chargen werden ueber
  `HonigCharge.query.filter(HonigCharge.restmenge_kg > 0)` abgefragt.
- **`AbfuellCharge`**: Kopf einer Abfuellsitzung. Traegt die Chargennummer (=
  MHD, **global eindeutig**, `unique=True`) und die Quellen -- NICHT
  `product_id`/Glasanzahl direkt, siehe naechster Punkt. Eine Chargennummer
  identifiziert eine Sitzung (gleiche Eimer, gleicher Zeitpunkt), nicht ein
  einzelnes Produkt: eine Sitzung aus denselben Eimern kann mehrere Glasgroessen
  gleichzeitig erzeugen (z.B. 30x 500g + 20x 250g), die sich alle dieselbe
  Chargennummer teilen.
- **`AbfuellungQuelle`**: Assoziationsmodell (Kopf `AbfuellCharge` \<->
  Rohmaterial `HonigCharge`), mit `entnommene_menge_kg` je Quelle -- als eigenes
  Modell mit `id`, NICHT als `db.Table(secondary=...)`, weil eine reine
  `secondary=`- Relation die Zusatzspalte `entnommene_menge_kg` nicht ueber den
  ORM-Zugriff liefern wuerde (noetig fuer die Verlust-Erfassung: entnommene
  Rohmenge kann groesser sein als die erzeugte Glasmenge, das ist normal).
- **`AbfuellErgebnis`**: Positionszeile einer Abfuellsitzung (welches Produkt,
  wie viele Glaeser) -- Kopf/Positionen-Muster analog zu `Invoice`/`LineItem`.
  Erhoeht beim Anlegen sofort `Product.number` um `anzahl_glaeser` (kein
  separater manueller Buchungsschritt in `/stock` noetig).

**Korrektur bei Fehleingaben:** `/production/abfuellungen/<id>/delete` (POST)
bucht `Product.number` je `AbfuellErgebnis`-Zeile und `restmenge_kg` je Quelle
zurueck, loescht dann kaskadierend (`cascade="all, delete-orphan"` auf
`AbfuellCharge.quellen`/`.ergebnisse`). Uneingeschraenkt erlaubt, solange aus
einer Charge noch nichts verkauft wurde -- was Stand jetzt immer zutrifft, da
Verkauf/Rechnung noch nicht chargenbewusst ist (siehe naechster Absatz).

**Bewusst noch nicht umgesetzt (Phase 2, siehe TODO.md):**
`LineItem`/`DeliveryNoteItem`/`ConsignmentStock` haben noch keinen Charge-Bezug
-- ein Verkauf bucht weiterhin nur `Product.number` global ab, ohne zu wissen,
aus welcher `AbfuellErgebnis`-Zeile die verkaufte Ware kam. Rueckverfolgbarkeit
endet aktuell an der Grenze "Abfuellung -> Verkauf", nicht weil das fachlich
gewollt ist, sondern weil dieser Teil bewusst zurueckgestellt wurde (beruehrt
GoBD-kritischen Code: Invoice-Hash, Storno-Pfad,
Kommissionslager-Unique-Constraint).

## Blueprint-Struktur -- so navigierst du durch die Routen

`app.py` war bis 2026-09-05 ein 3335-Zeilen-Monolith mit praktisch allen ~65
Routen als verschachtelte Funktionen in `create_app()`. Seitdem ist `app.py` auf
die App-Factory selbst reduziert (App-/DB-/Mail-/CrowdSec-/ LoginManager-Init,
Blueprint-Registrierung, `utility_processor`-Context- Processor, der
`/health`-Endpoint, sowie die zwei CLI-Commands `init_db`/`seed_db`). Alle
Domaenen-Routen liegen in eigenstaendigen Flask-Blueprints unter `blueprints/`:

| Blueprint (`blueprints/*.py`) | Praefix | Enthaelt | |---|---|---| | `main.py`
(`main_bp`) | `/` | Nur die Dashboard-Route `index` | | `auth.py` (`auth_bp`) |
-- | Login, 2FA (Setup/Verify/Disable/Backup-Codes), Logout, Bestandsquelle
waehlen, Passwort-Reset | | `api.py` (`api_bp`) | `/api` |
JWT-Login/Verify/Refresh + Invoices/Customers/POS ueber Token, plus die
`@login_required`-Autocomplete-/Bestandsaenderungs-Endpoints der Web-UI | |
`products.py` (`products_bp`) | -- | `/products*`, `/stock` | | `customers.py`
(`customers_bp`) | -- | `/customers*`, DSGVO-Anonymisierung | | `pos.py`
(`pos_bp`) | -- | `/pos`, `/pos/complete-sale` (Kasse) | | `reports.py`
(`reports_bp`) | `/reports` | Jahresuebersicht Einnahmen (Web + PDF) | |
`users.py` (`users_bp`) | -- | `/settings*` (Firmendaten, Benutzerverwaltung,
SMTP/IMAP-Verbindungstest) | | `delivery_notes.py` (`delivery_notes_bp`) | -- |
`/delivery-notes*`, `/consignment/*`, `/payments/*` | | `invoices.py`
(`invoices_bp`) | -- | `/invoices*` (CRUD, Storno, PDF, E-Mail, Mahnwesen),
`/stock-adjustments*` -- groesster Blueprint | | `production.py`
(`production_bp`) | -- | `/production/eimer*`, `/production/abfuellungen*` --
Honig-Rueckverfolgbarkeit |

Alle Blueprints sind mit explizitem Namen registriert (z.B.
`main_bp = Blueprint("main", __name__)`), daher heissen Endpoints
`<blueprintname>.<funktionsname>` -- z.B. `url_for("main.index")`,
`url_for("invoices.view_invoice", invoice_id=...)`. Das gilt fuer JEDEN
`url_for()`-Aufruf, auch in Templates. Beim Hinzufuegen einer neuen Route:

- Passt sie zu einer bestehenden Domaene? In das entsprechende `blueprints/*.py`
  einfuegen.
- Passt sie zu keiner? Neues `blueprints/<name>.py` anlegen (Muster:
  `<name>_bp = Blueprint("<name>", __name__)`, in `create_app()` importieren und
  mit `app.register_blueprint(<name>_bp)` registrieren).
- Innerhalb eines Blueprint-Moduls gibt es kein `app`-Objekt mehr im Scope --
  `current_app` (aus `flask`) statt `app` fuer Config-Zugriffe
  (`current_app.config[...]`) und Logging (`current_app.logger`).
- `tests/endpoints_test.py` scannt `app.py`, `blueprints/*.py` UND
  `templates/*.html` auf `url_for("...")`-Aufrufe und prueft, dass jeder
  Endpoint tatsaechlich registriert ist -- Sicherheitsnetz gegen falsche oder
  vergessene Blueprint-Praefixe. Bei jeder Aenderung an Endpoint-Namen oder
  neuen Blueprints diesen Test mitlaufen lassen.
- `auth_utils.py` enthaelt den `role_required(*roles)`-Decorator
  (eigenstaendiges Modul, nicht mehr in `create_app()` verschachtelt) -- siehe
  Abschnitt "Rollen & Autorisierung" unten.
- `invoice_numbering.py` enthaelt `generate_invoice_number()`, genutzt von
  `app.py` (CLI `seed_db`) und `blueprints/api.py` (POS-Verkauf via API) --
  eigenstaendiges Modul, um einen Zirkelimport zwischen `app.py` und den
  Blueprints zu vermeiden.
- CLI-Commands (`flask init-db`, `flask seed-db`) liegen weiterhin in `app.py`,
  innerhalb von `create_app()`.
- Flask registriert `@app.cli.command()`-Funktionsnamen mit Unterstrichen
  automatisch als Bindestrich-Commands: `init_db` im Code heisst auf der
  Kommandozeile `flask init-db`, nicht `flask init_db`.

## Modulkarte

| Datei | Zweck | |---|---| | `app.py` | App-Factory, Blueprint-Registrierung,
`/health`, CLI-Commands | | `blueprints/main.py` | Dashboard-Route `/` | |
`blueprints/auth.py` | Login, 2FA, Logout, Bestandsquelle, Passwort-Reset | |
`blueprints/api.py` | JWT-API fuer die PWA +
Web-UI-Autocomplete-/Bestandsendpoints unter `/api` | | `blueprints/products.py`
| Produktverwaltung, Bestandsuebersicht (`/products*`, `/stock`) | |
`blueprints/customers.py` | Kundenverwaltung, DSGVO-Anonymisierung | |
`blueprints/pos.py` | Kasse/Direktverkauf (`/pos*`) | | `blueprints/reports.py`
| Jahresuebersicht Einnahmen (Web + PDF) unter `/reports` | |
`blueprints/users.py` | Einstellungen, Benutzerverwaltung,
E-Mail-Verbindungstest | | `blueprints/delivery_notes.py` | Lieferscheine,
Kommissionslager, Zahlungsabgleich | | `blueprints/invoices.py` |
Rechnungs-CRUD/Storno/PDF/E-Mail/Mahnwesen, Bestandsanpassungen | |
`blueprints/production.py` | Honig-Rueckverfolgbarkeit: Eimer anlegen/befuellen,
Abfuellungen anlegen/stornieren | | `auth_utils.py` |
`role_required(*roles)`-Decorator fuer rollenbasierte Zugriffskontrolle | |
`invoice_numbering.py` | `generate_invoice_number()`, gemeinsam genutzt von
`app.py` und `blueprints/api.py` | | `models.py` | 18 SQLAlchemy-Modelle, mit
GoBD-Hinweisen im Docstring | | `config.py` | Config-Klassen
(Development/Production/Testing), liest alle ENV-Variablen | |
`delivery_note_service.py` | PDF-Erzeugung Lieferscheine (ReportLab) | |
`reminder_service.py` | PDF-Erzeugung Mahnungen (ReportLab) | | `pdf_service.py`
| Rechnungs-PDF + EPC-QR-Code fuer SEPA-Ueberweisung | | `pdf_utils.py` |
Gemeinsame ReportLab-Hilfsfunktion `add_fold_and_punch_marks()`
(DIN-5008-Faltmarken), genutzt von allen drei PDF-Modulen oben | |
`email_service.py` | Rechnungsversand + genereller Mailversand via Flask-Mail |
| `email_parser.py` | IMAP-Client, liest Shop-Bestellmails ein | | `jwt_api.py`
| JWT-Erzeugung/-Pruefung + Decorators fuer die PWA-API, unabhaengig von
Flask-Login | | `password_reset.py` | Token-basierter Passwort-Reset-Flow | |
`crowdsec_app.py` | Middleware, loggt 4xx/5xx/Failed-Logins nach
`logs/security.log` fuer CrowdSec | | `cleanup_database.py` | Wartungsskript zur
Datenbereinigung | | `migrate.py` | Alembic-Wrapper, liest `DATABASE_URL` aus
`.env` | | `seed_reseller_test_data.py` | Testdaten-Generator fuer
Reseller-Szenarien | | `generate_icons.py` | Generiert PWA-Icons in versch.
Groessen aus einer Quellgrafik |

## Datenbank & Migrationen

Aktuell und gewollt: **Alembic** (`alembic.ini`, `alembic/versions/`). Enthaelt
aktuell eine konsolidierte Migration
(`352cafa6cd86_initial_schema_from_models.py`), aus dem Ist-Stand der Models
generiert. Details und der Umstieg von `flask init-db` per `alembic stamp head`
stehen in MIGRATIONS.md.

`flask init-db` legt weiterhin Tabellen an (fuer Frischinstallationen) sowie
einen Standard-Admin `admin`/`admin` und den internen "Marktstand"-Systemkunden.
Es ersetzt Alembic nicht fuer Schema-Aenderungen an einer bestehenden Datenbank
-- fuer die nutzt du `alembic revision` / `alembic upgrade head`.

### Dead Ends (nicht anfassen, nicht als aktuell missverstehen)

- **`migrations_archive/`** (12 Dateien + eigenes README): das alte,
  handgeschriebene Ad-hoc-Migrationssystem vor Alembic. In MIGRATIONS.md
  explizit als archiviert bezeichnet. Kein Code liest daraus.
- **`migrations/`** (ein noch aelterer, undokumentierter Zwischenstand) wurde
  geloescht (2026-09-05) -- tauchte in MIGRATIONS.md nicht auf, kein Code las
  daraus. Falls ein aehnliches Verzeichnis wieder auftaucht: gleiche Pruefung
  wie hier (MIGRATIONS.md durchsuchen, Code-Referenzen grep'en) vor dem
  Anfassen.
- **`regenerate_hashes.py`** (geloescht 2026-09-05) rief `generate_hash()` auf
  saemtliche bestehenden Invoices auf und ueberschrieb `data_hash` per Commit.
  Ein erneuter Lauf eines solchen Skripts wuerde den Manipulationsschutz
  bestehender Rechnungen rueckwirkend aushebeln -- `data_hash` soll den Stand
  zum Erstellzeitpunkt fixieren, nicht nachtraeglich neu berechnet werden. Bei
  einem kuenftigen Hash-Format-Wechsel stattdessen einen versionierten Hash
  (z.B. Format-Marker im gespeicherten Wert) einfuehren, statt Bestandsdaten neu
  zu hashen. `debug_hash.py` (ebenfalls geloescht) war ein reines
  Lese-Debug-Skript ohne dieses Risiko, aber bereits mit einem veralteten
  Hash-Schema (fehlten `product_id`/`tax_rate` je LineItem).

## Konfiguration & Umgebungsvariablen

### Von der App tatsaechlich gelesen (config.py)

`SECRET_KEY`, `DATABASE_URL`, `UPLOAD_FOLDER`, `PDF_FOLDER`, `MAIL_SERVER`,
`MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_USE_SSL`, `MAIL_USE_TLS`,
`MAIL_DEFAULT_SENDER`, `IMAP_SERVER`, `IMAP_PORT`, `IMAP_USERNAME`,
`IMAP_PASSWORD`, `IMAP_USE_SSL`, `API_TOKEN_EXPIRY_DAYS`, `TOTP_ISSUER_NAME`,
`COMPANY_NAME`, `COMPANY_HOLDER`, `COMPANY_STREET`, `COMPANY_ZIP`,
`COMPANY_CITY`, `COMPANY_COUNTRY`, `COMPANY_EMAIL`, `COMPANY_PHONE`,
`COMPANY_TAX_ID`, `COMPANY_WEBSITE`, `BANK_NAME`, `BANK_IBAN`, `BANK_BIC`,
`PAYPAL`, `DEFAULT_TAX_RATE`, `LANDWIRTSCHAFTLICHE_URPRODUKTION_TAX_RATE`

Die App nutzt Standard-Flask-Client-Cookie-Sessions; `flask-session` ist nicht
installiert. `jwt_api.py` signiert/verifiziert JWT-Tokens mit
`current_app.config["SECRET_KEY"]` (jwt_api.py:30 und :46) -- es gibt keinen
separaten JWT-Key. Die zuvor gesetzten, wirkungslosen Variablen
`SESSION_TYPE`/`SESSION_FILE_DIR`/`SESSION_REDIS`/`JWT_SECRET_KEY` wurden am
2026-09-05 aus allen docker-compose-Dateien, `.env.docker` und der Dokumentation
entfernt (siehe TODO.md "Erledigt"). Wer server-seitige Sessions oder einen
separaten JWT-Key will, muss das als eigenes Feature einbauen (`flask-session`
in requirements.txt + `Session(app)` in app.py bzw. `jwt_api.py` auf einen
zweiten Key umstellen), nicht nur ENV-Werte setzen.

### Deployment-spezifisch (nicht von der App selbst gelesen)

`DOMAIN`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_ROOT_PASSWORD`,
`HTTPNET_API_KEY` (Traefik DNS-Challenge, siehe DOCKER_DEPLOYMENT.md).

## Datenbank-Dialekt: MariaDB

Produktiv laeuft **MariaDB** (docker-compose.yml, `pymysql`-Treiber). PostgreSQL
wird nicht mehr genutzt und nicht mehr unterstuetzt -- die frueheren
Postgres-Ueberreste (`psycopg2-binary` in requirements.txt, Postgres-Default in
config.py, `dialect = postgres` in setup.cfg, `fix_permissions.sql`,
`postgresql-client`/`libpq-dev` im Dockerfile) wurden am 2026-09-05 entfernt,
nachdem verifiziert wurde, dass kein Deployment mehr PostgreSQL nutzt.

## PDF-Hilfsfunktionen

`add_fold_and_punch_marks()` (DIN-5008-Faltmarken/Lochmarke fuer den PDF-Druck)
lag urspruenglich dreifach dupliziert in `pdf_service.py`,
`delivery_note_service.py` und `reminder_service.py`. Seit 2026-09-05 liegt sie
zentral in `pdf_utils.py`, alle drei Module importieren von dort. Neue
PDF-Erzeugungslogik, die dieselbe Faltmarken-Konvention braucht, importiert
ebenfalls aus `pdf_utils.py`, statt erneut zu duplizieren.

## Health-Check & SQLAlchemy 2.x

SQLAlchemy 2.x fuehrt rohe SQL-Strings nicht mehr direkt aus. Der
`/health`-Endpoint nutzte `db.session.execute("SELECT 1")` und schlug deshalb
dauerhaft fehl (`ObjectNotExecutableError`) -- behoben durch
`db.session.execute(text("SELECT 1"))` (app.py, `from sqlalchemy import text`).
Falls neuer Code rohes SQL ausfuehrt, immer `sqlalchemy.text(...)` verwenden,
nie einen nackten String an `.execute()` uebergeben.

## Tests

101 Tests in `tests/` (pytest, In-Memory-SQLite via `TestingConfig`):

- `conftest.py`: Fixtures (`app`, `client`, `db_session`, `admin_user`/
  `cashier_user`/`reseller_user`, `customer`, `product`) und Helper- Funktionen
  (`make_user`, `make_customer`, `make_product`, `make_invoice`,
  `make_line_item`, `login(client, username, password)`). Setzt `SECRET_KEY` und
  den Projekt-Root in `sys.path` selbst, laeuft also ohne manuell gesetzte
  ENV-Variablen.
- `invoice_model_test.py`: Charakterisierungstests fuer Modell-Logik --
  `calculate_totals()` (alle drei `tax_model`-Werte inkl. gemischtem Warenkorb),
  `generate_hash()`/`verify_hash()`, `reduce_stock()`/ `increase_stock()`,
  `anonymize_gdpr()`, User-Passwort/Backup-Codes/Rollen.
- `routes_smoke_test.py`: Login-Flow, oeffentliche Routen, Rollen-
  Autorisierung, CRUD-Grundpfade fuer Invoices/Customers/Products/POS.
- `invoice_workflow_test.py`: GoBD-kritische End-to-End-Pfade -- Lebenszyklus
  draft->sent->paid, verbotene Statusuebergaenge, Storno-Flow (inkl.
  Audit-Trail), Kommissionsbestand-Rueckbuchung, POS-Verkauf, PDF-Archivierung,
  Mahnwesen.
- `endpoints_test.py`: Sicherheitsnetz fuer den Blueprint-Split -- prueft, dass
  jeder statische `url_for("...")`-Aufruf in `app.py`, `blueprints/*.py` und
  `templates/*.html` auf einen tatsaechlich registrierten Endpoint zeigt, sowie
  dass `login_manager.login_view` aufloesbar ist.
- `production_test.py`: Honig-Rueckverfolgbarkeit -- `HonigCharge.status`-
  Property-Uebergaenge, Eimer-Befuellungs-Guard, Abfuellung aus mehreren Eimern
  (m:n), Abfuellsitzung mit mehreren Produkt-Ergebnissen (teilt sich eine
  Chargennummer), Validierung (doppelte Chargennummer, leere Quellen/
  Ergebnisse, Entnahme > Restmenge), Storno-Route mit Rueckbuchung.

`pytest` ist in requirements.txt, der `pytest`-Hook in `.pre-commit-config.yaml`
ist aktiv. `setup.cfg` hat eine `[tool:pytest]`-Sektion mit
`python_files = *_test.py` -- unueblich, Testdateien muessen auf `_test.py`
enden, nicht mit `test_` beginnen.

**Noch nicht geschrieben, optionale Ergaenzung:** Tests fuer `email_parser.py`
(IMAP-Client) mit IMAP-Mocking.

## Linting & pre-commit

Aktive Hooks (siehe `.pre-commit-config.yaml`, Details in PRE_COMMIT_SETUP.md):
Black, Flake8, isort (alle line-length 160), djLint (Jinja2), curlylint, ESLint
(JS), Bandit (Security), SQLFluff (lint+fix), Pylint, py-compile, Safety
(Dependency-Check). Auskommentiert: `pytest`, `make_html_doc`.

## GoBD-Konformitaet -- beim Aendern beachten

Rechnungen, Zahlungen und Bestandsanpassungen unterliegen expliziten
Unveraenderbarkeits- und Nachvollziehbarkeitsanforderungen (volle Details in
GOBD_COMPLIANCE.md). Vor Aenderungen an `Invoice`, `InvoiceStatusLog`,
`InvoicePdfArchive`, `StockAdjustment` oder der Storno-Logik GOBD_COMPLIANCE.md
lesen -- diese Anforderungen sind fachlich vorgegeben, nicht optional
refaktorierbar. Kernregeln:

- Status-Workflow nur vorwaerts: `draft` -> `sent` -> `paid`. Ein Zuruecksetzen
  von `sent` auf `draft` (oder generell rueckwaerts) ist verboten und wird an
  Stellen im Code explizit abgefangen.
- Nur `draft`-Rechnungen duerfen geloescht werden (kein abgeschlossener
  Geschaeftsvorfall). `sent`/`paid` NIE loeschen -- stattdessen eine
  Stornorechnung erzeugen (negative Betraege, `STORNO-`-Prefix, Bestand wird
  zurueckgebucht, Original-Status wechselt auf `cancelled`).
- Jede Statusaenderung erzeugt einen `InvoiceStatusLog`-Eintrag mit
  `changed_by=current_user.username` -- niemals ein Literal wie `"System"`
  eintragen, auch nicht bei automatisierten/Batch-Aenderungen.
- Beim ersten PDF-Download einer `sent`-Rechnung wird ein
  `InvoicePdfArchive`-Eintrag mit SHA-256-Hash des PDFs angelegt.

## Rollen & Autorisierung

Drei Rollen (`User.role`): `admin` (voller Zugriff), `cashier` (Kasse +
Rechnungen ansehen), `reseller` (eigener Bestand/Preise, ueber
`reseller_customer_id` verknuepft). Routen werden mit `@role_required(*roles)`
geschuetzt (`auth_utils.py`, eigenstaendiges Modul seit dem Blueprint-Split),
die API-Variante fuer JWT-Routen ist `@role_required_api(*roles)`
(`jwt_api.py`). Ungeschuetzte Routen ohne `@login_required` sind auf die
erwartbaren Faelle beschraenkt (`/login`, `/verify-2fa`, `/forgot-password`,
`/reset-password/<token>`, `/health`, `/offline`, `/api/auth/login`) -- bei
einer neuen Route immer explizit entscheiden und mit
`@login_required`/`@role_required` versehen, statt sich auf einen impliziten
Default zu verlassen.
