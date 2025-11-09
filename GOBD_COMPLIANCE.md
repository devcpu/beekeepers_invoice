# GoBD-Konformität - Rechnungsverwaltungssystem

## Übersicht

Dieses System erfüllt die Anforderungen der **GoBD (Grundsätze zur
ordnungsmäßigen Führung und Aufbewahrung von Büchern, Aufzeichnungen und
Unterlagen in elektronischer Form sowie zum Datenzugriff)** für die
elektronische Rechnungsstellung und -verwaltung.

**Implementierungsdatum:** Dezember 2024 **Version:** 1.1 **Rechtsgrundlage:**
BMF-Schreiben vom 28.11.2019

**Erfasste Geschäftsvorfälle:**

- Rechnungen (Verkauf an Kunden)
- Stornorechnungen (Korrekturbelege)
- BAR-Rechnungen (Direktverkauf/Kasse)
- Bestandsanpassungen (Eigenentnahme, Inventur, Verderb, etc.)

______________________________________________________________________

## Inhaltsverzeichnis

1. [Unveränderbarkeit von Belegen](#1-unver%C3%A4nderbarkeit-von-belegen-immutability)
1. [Vollständiger Audit Trail](#2-vollst%C3%A4ndiger-audit-trail)
1. [Stornierung durch Korrekturbeleg](#3-stornierung-durch-korrekturbeleg)
1. [PDF-Archivierung mit Hash-Verifizierung](#4-pdf-archivierung-mit-hash-verifizierung)
1. [Datenbankstruktur](#5-datenbankstruktur)
1. [Migration bestehender Daten](#6-migration-bestehender-daten)
1. [Verfahrensdokumentation](#7-verfahrensdokumentation)
1. [Bestandsanpassungen (Eigenentnahme, Inventur)](#8-bestandsanpassungen-eigenentnahme-inventur)
1. [Datenschutz (DSGVO) & Anonymisierung](#9-datenschutz-dsgvo--anonymisierung)
1. [Backup-Strategie](#10-backup-strategie)
1. [Betriebsprüfung (Finanzamt)](#11-betriebspr%C3%BCfung-finanzamt)
1. [Checkliste: GoBD-Konformität](#12-checkliste-gobd-konformit%C3%A4t)

______________________________________________________________________

## 1. Unveränderbarkeit von Belegen (Immutability)

### Anforderung

Versendete Rechnungen dürfen nicht mehr nachträglich verändert werden können.

### Implementierung

#### Status-Workflow

```
draft → sent → paid
   ↓          ↓
DELETE    cancelled
```

**Regeln:**

- ✅ `draft` → `sent`: Erlaubt
- ✅ `draft` → **LÖSCHEN**: Erlaubt (nicht buchungsrelevant)
- ✅ `sent` → `paid`: Erlaubt
- ✅ `sent` → `cancelled`: Erlaubt (nur über Stornorechnung)
- ✅ `paid` → `cancelled`: Erlaubt (nur über Stornorechnung)
- ❌ `sent` → `draft`: **VERBOTEN**
- ❌ `sent` → **LÖSCHEN**: **VERBOTEN** (nur Stornierung)
- ❌ `paid` → `draft`: **VERBOTEN**
- ❌ `paid` → `sent`: **VERBOTEN**
- ❌ `paid` → **LÖSCHEN**: **VERBOTEN** (nur Stornierung)

#### Löschung von Entwürfen (GoBD-konform)

**Wichtig:** Entwürfe sind noch nicht geschäftsrelevant und unterliegen
**nicht** der Aufbewahrungspflicht.

**Route:** `/invoices/<id>/delete` (POST) **Datei:** `app.py` - Funktion
`delete_invoice()`

```python
# GoBD: Nur Entwürfe dürfen gelöscht werden
if invoice.status != 'draft':
    flash('Fehler: Nur Entwürfe können gelöscht werden. Versendete Rechnungen müssen storniert werden (GoBD-Konformität).', 'error')
    return redirect(url_for('view_invoice', invoice_id=invoice_id))
```

**Was wird gelöscht:**

- ✅ Rechnung selbst
- ✅ Alle Rechnungspositionen (LineItems)
- ✅ Status-Log-Einträge (wenn vorhanden)
- ❌ **NICHT** gelöscht: Kundendaten (werden wiederverwendet)

**Rechtfertigung:** Ein Entwurf ist noch keine Rechnung im steuerrechtlichen
Sinne. Die Aufbewahrungspflicht beginnt erst mit der Versendung an den Kunden
(Status `sent`).

#### Status-Übergang zu 'sent' als kritischer Punkt

Ab dem Moment, in dem eine Rechnung als "versendet" markiert wird:

- Wird der **SHA-256 Hash** gespeichert
- Greift die **Unveränderbarkeit**
- Beginnt die **10-jährige Aufbewahrungspflicht**
- Sind **keine Löschungen** mehr erlaubt

#### Code-Implementierung

**Datei:** `app.py` - Funktion `update_invoice_status()`

```python
# Verhindere unzulässige Status-Änderungen (GoBD)
if invoice.status == 'sent':
    if new_status == 'draft':
        flash('Fehler: Versendete Rechnungen können nicht zurück zu Entwurf gesetzt werden (GoBD).', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
```

#### Datenbank-Integritätsprüfung

Jede Rechnung hat einen **SHA-256 Hash** über alle Rechnungsdaten:

- Gespeichert in: `Invoice.data_hash`
- Berechnet bei Erstellung
- Verifiziert bei Anzeige
- Bei Manipulation wird Warnung angezeigt

______________________________________________________________________

## 2. Vollständiger Audit Trail

### Anforderung

Alle Änderungen an Rechnungen müssen nachvollziehbar protokolliert werden.

### Implementierung

#### Datenbank-Modell: `InvoiceStatusLog`

**Datei:** `models.py`

```sql
CREATE TABLE invoice_status_log (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    old_status VARCHAR(20),
    new_status VARCHAR(20) NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    changed_by VARCHAR(100) NOT NULL,
    reason TEXT
);
```

**Erfasste Informationen:**

- **invoice_id**: Referenz zur Rechnung
- **old_status**: Status vor Änderung (NULL bei Erstellung)
- **new_status**: Neuer Status
- **changed_at**: Zeitstempel der Änderung (Mikrosekunden-genau)
- **changed_by**: Benutzer (aktuell "System", erweiterbar)
- **reason**: Optionaler Grund für die Änderung

#### Automatische Protokollierung

Jede Status-Änderung wird automatisch protokolliert:

```python
log_entry = InvoiceStatusLog(
    invoice_id=invoice.id,
    old_status=invoice.status,
    new_status=new_status,
    changed_by='System',  # TODO: Aktuellen User integrieren
    reason=reason
)
db.session.add(log_entry)
```

#### Anzeige im Frontend

**Datei:** `templates/invoices/view.html`

Die Status-Historie wird in jedem Rechnungsdetail angezeigt:

- Chronologische Auflistung aller Status-Änderungen
- Zeitstempel
- Grund der Änderung
- Benutzer

______________________________________________________________________

## 3. Stornierung durch Korrekturbeleg

### Anforderung

Rechnungen dürfen nicht gelöscht werden. Stornierungen müssen durch
Gegenbuchungen erfolgen.

### Implementierung

#### Stornorechnung-Workflow

**Route:** `/invoices/<id>/cancel` (GET + POST) **Datei:** `app.py` - Funktion
`create_cancellation_invoice()`

**Ablauf:**

1. **Validierung**

   - Nur für Status `sent` oder `paid`
   - Rechnung darf nicht bereits storniert sein

1. **Neue Rechnung erstellen**

   - Rechnungsnummer: `STORNO-{YYYYMMDD}-{laufende Nummer}`
   - Alle Beträge: **Negativ**
   - Gleiche Positionen wie Original
   - Referenz auf Original-Rechnung in Notizen

1. **Positionen übernehmen**

   ```python
   for item in original_invoice.line_items:
       storno_item = LineItem(
           description=item.description,
           quantity=-item.quantity,  # NEGATIV!
           unit_price=item.unit_price,
           total=-item.total,  # NEGATIV!
           tax_rate=item.tax_rate,
           product_id=item.product_id
       )
   ```

1. **Bestandsrückbuchung**

   - Produkte: `product.number += quantity`
   - Kommissionsware: `consignment_item.quantity_remaining += quantity`

1. **Status-Updates**

   - Original-Rechnung: Status → `cancelled`
   - Stornorechnung: Status → `draft`
   - Beide Status-Änderungen werden protokolliert

1. **Hash-Generierung**

   - Stornorechnung erhält eigenen SHA-256 Hash

#### Benutzeroberfläche

**Template:** `templates/invoices/create_cancellation.html`

- Anzeige der Original-Rechnungsdaten
- Eingabefeld für Stornierungsgrund (Pflichtfeld)
- Übersicht der zu stornierenden Positionen
- Warnung über Unumkehrbarkeit
- Bestätigung erforderlich

______________________________________________________________________

## 4. PDF-Archivierung mit Hash-Verifizierung

### Anforderung

PDFs müssen unveränderbar archiviert und ihre Integrität prüfbar sein.

### Implementierung

#### Datenbank-Modell: `InvoicePdfArchive`

**Datei:** `models.py`

```sql
CREATE TABLE invoice_pdf_archive (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    pdf_filename VARCHAR(255) NOT NULL,
    pdf_hash VARCHAR(64) NOT NULL,
    file_size INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archived_by VARCHAR(100) NOT NULL,
    UNIQUE (invoice_id, pdf_filename)
);
```

**Erfasste Informationen:**

- **pdf_filename**: Name der PDF-Datei
- **pdf_hash**: SHA-256 Hash des PDF-Inhalts
- **file_size**: Dateigröße in Bytes
- **created_at**: Zeitpunkt der Archivierung
- **archived_by**: Benutzer

#### Automatische Archivierung beim Download

**Route:** `/invoices/<id>/pdf` **Datei:** `app.py` - Funktion
`download_invoice_pdf()`

**Ablauf:**

1. PDF wird generiert
1. **Beim ersten Download** (wenn Status = `sent`):
   - SHA-256 Hash wird berechnet
   - Archive-Eintrag wird erstellt
   - PDF wird ausgeliefert
1. Bei weiteren Downloads wird der Hash nicht neu berechnet

```python
# Hash berechnen
pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()

# Archiv-Eintrag erstellen
archive = InvoicePdfArchive(
    invoice_id=invoice.id,
    pdf_filename=pdf_filename,
    pdf_hash=pdf_hash,
    file_size=len(pdf_bytes),
    archived_by='System'
)
```

#### PDF-Verifizierung

**Datei:** `models.py` - Methode `InvoicePdfArchive.verify_pdf()`

```python
def verify_pdf(self, pdf_path: str) -> bool:
    """Verifiziert die Integrität einer PDF-Datei"""
    with open(pdf_path, 'rb') as f:
        current_hash = hashlib.sha256(f.read()).hexdigest()
    return current_hash == self.pdf_hash
```

#### Anzeige im Frontend

**Template:** `templates/invoices/view.html`

- Liste aller archivierten PDFs
- Dateiname, Größe, Archivierungszeitpunkt
- Vollständiger SHA-256 Hash zur Verifizierung
- Hinweis auf GoBD-Konformität

______________________________________________________________________

## 5. Datenbankstruktur

### Entity-Relationship

```
Invoice (1) ←→ (N) InvoiceStatusLog
Invoice (1) ←→ (N) InvoicePdfArchive
Invoice (1) ←→ (N) LineItem
```

### Indizes für Performance

```sql
-- Status-Historie
CREATE INDEX idx_invoice_status_log_invoice_id ON invoice_status_log(invoice_id);
CREATE INDEX idx_invoice_status_log_changed_at ON invoice_status_log(changed_at);

-- PDF-Archiv
CREATE INDEX idx_invoice_pdf_archive_invoice_id ON invoice_pdf_archive(invoice_id);
CREATE INDEX idx_invoice_pdf_archive_pdf_hash ON invoice_pdf_archive(pdf_hash);
```

______________________________________________________________________

## 6. Migration bestehender Daten

### Migrations-Skript

**Datei:** `migrate_add_gobd_tables.py`

**Was wurde migriert:**

1. Erstellung der neuen Tabellen
1. Indizes erstellt
1. Für alle bestehenden Rechnungen wurde ein initialer Status-Log-Eintrag
   erstellt:
   - `old_status = NULL`
   - `new_status = <aktueller Status>`
   - `reason = 'Initial migration - existing invoice'`

**Ausführung:**

```bash
python migrate_add_gobd_tables.py
```

**Ergebnis:**

- ✅ 2 neue Tabellen erstellt
- ✅ 4 Indizes angelegt
- ✅ 9 bestehende Rechnungen migriert

______________________________________________________________________

## 7. Verfahrensdokumentation

### 7.1 Prozess: Rechnung erstellen

1. **Entwurf erstellen** (Status: `draft`)

   - Kundendaten eingeben
   - Positionen hinzufügen
   - Rechnung kann noch bearbeitet oder gelöscht werden

1. **Optional: Entwurf löschen**

   - ℹ️ Solange Status `draft`, kann die Rechnung gelöscht werden
   - Button "Entwurf löschen" in Rechnungsansicht
   - Bestätigung erforderlich
   - ➜ Rechnung wird komplett aus der Datenbank entfernt
   - **Wichtig:** Nach Versendung (Status `sent`) ist Löschung nicht mehr
     möglich!

1. **PDF generieren und prüfen**

   - Vorschau erstellen
   - Auf Fehler prüfen

1. **Als "Versendet" markieren** (Status: `sent`)

   - ⚠️ **Ab jetzt GoBD-relevant!**
   - ➜ Status-Log-Eintrag wird erstellt
   - ➜ Aufbewahrungspflicht beginnt (10 Jahre)
   - ➜ Unveränderbarkeit greift
   - ➜ Löschung nicht mehr möglich

1. **PDF herunterladen**

   - ➜ Beim ersten Download: PDF-Hash wird berechnet und archiviert

1. **Als "Bezahlt" markieren** (Status: `paid`)

   - ➜ Status-Log-Eintrag wird erstellt

### 7.2 Prozess: Rechnung stornieren

**Nur für Status `sent` oder `paid`!**

1. Rechnung öffnen (muss Status `sent` oder `paid` haben)
1. Klick auf "Stornorechnung erstellen"
1. Grund für Stornierung eingeben (Pflichtfeld)
1. Bestätigen
   - ➜ Neue Rechnung mit negativen Beträgen wird erstellt
   - ➜ Bestand wird zurückgebucht
   - ➜ Original-Rechnung erhält Status `cancelled`
   - ➜ Beide Status-Änderungen werden protokolliert
1. Stornorechnung versenden (wie normale Rechnung)

**Wichtig für Entwürfe:** Entwürfe (Status `draft`) können nicht storniert
werden, sondern müssen gelöscht werden!

### 7.3 Prozess: Integrität prüfen

#### Rechnungsdaten

- Hash wird automatisch bei jedem Aufruf geprüft
- Bei Manipulation: Rote Warnung wird angezeigt

#### PDF-Dateien

```python
# Manuell (Python):
from models import InvoicePdfArchive
archive = InvoicePdfArchive.query.filter_by(invoice_id=123).first()
is_valid = archive.verify_pdf('/path/to/invoice.pdf')
```

______________________________________________________________________

## 8. Bestandsanpassungen (Eigenentnahme, Inventur)

### Anforderung und Abgrenzung

Bestandsveränderungen ohne Verkauf (Eigenentnahme, Verderb, Inventur) müssen
GoBD-konform dokumentiert werden, auch wenn keine Rechnung erstellt wird.

**Wichtig:** Nicht alle Bestandsbewegungen erfordern GoBD-Dokumentation!

#### ✅ Normale Geschäftsvorfälle (KEINE GoBD-Dokumentation erforderlich)

Diese Vorgänge haben bereits ausreichende Belege und benötigen **keine**
separate GoBD-Bestandsanpassung:

1. **Produktion/Abfüllen**

   - API: `POST /api/products/lot/<lot>/stock/add`
   - **Grund:** Noch nicht verkauft, keine Steuerrelevanz
   - **Beleg:** Produktionsprotokoll (optional)

1. **Verkauf über Kasse/Rechnung**

   - Automatischer Bestandsabzug
   - **Grund:** Vollständiger Beleg vorhanden (Rechnung/Kassenbon)
   - **Beleg:** RE-/BAR-Nummer (bereits GoBD-konform)

1. **Kommissionsware-Lieferung**

   - Lieferschein-System
   - **Grund:** Lieferschein ist vollständiger Beleg
   - **Beleg:** LS-Nummer

#### 📝 Steuerrelevante Anpassungen (GoBD-Dokumentation ERFORDERLICH)

Nur diese Vorgänge nutzen das Bestandsanpassungs-System mit Belegnummern:

1. **Eigenentnahme** (§ 3 Abs. 1b Nr. 1 UStG)

   - Privater Verbrauch von Geschäftsware
   - **Steuerrelevant:** Umsatzsteuer auf Entnahme
   - **Beispiel:** 5 Gläser Honig für privaten Haushalt

1. **Geschenke**

   - Unentgeltliche Zuwendungen
   - **Steuerrelevant:** § 4 Abs. 5 Satz 1 Nr. 1 EStG (bei >50€)
   - **Beispiel:** Präsentkorb an Geschäftspartner

1. **Verderb/Bruch**

   - Ware nicht mehr verkäuflich
   - **Steuerrelevant:** Betriebsausgabe ohne Gegenwert
   - **Beispiel:** Kristallisierter Honig

1. **Inventurkorrekturen**

   - Differenzen zwischen Soll und Ist
   - **Steuerrelevant:** Buchwert-Anpassung
   - **Beispiel:** 10 Gläser mehr/weniger als erwartet

**Warum diese Unterscheidung?**

- GoBD-Dokumentation ist nur für **Geschäftsvorfälle ohne ausreichenden Beleg**
  erforderlich
- API-Endpoints für Produktion haben **keinen steuerlichen Vorgang** (noch nicht
  verkauft)
- Verkäufe haben bereits **vollständige Belege** (Rechnungen erfüllen GoBD)
- Eigenentnahmen/Verderb haben **keinen externen Beleg** → System muss
  dokumentieren

### Implementierung

#### Datenbank-Modell: `StockAdjustment`

**Datei:** `models.py`

```sql
CREATE TABLE stock_adjustments (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,              -- Positiv = Zugang, Negativ = Abgang
    old_stock INTEGER NOT NULL,             -- Bestand vor Anpassung
    new_stock INTEGER NOT NULL,             -- Bestand nach Anpassung
    adjustment_type adjustment_type_enum NOT NULL,
    reason TEXT NOT NULL,                   -- Pflichtfeld für GoBD
    adjusted_by INTEGER NOT NULL REFERENCES users(id),
    adjusted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    document_number VARCHAR(50) UNIQUE      -- Beleg-Nummer für Eigenentnahmen
);
```

**Anpassungstypen:**

- `eigenentnahme` - Privater Verbrauch (§ 3 Abs. 1b Nr. 1 UStG)
- `geschenk` - Unentgeltliche Zuwendung
- `verderb` - Verdorbene/unverkäufliche Ware
- `bruch` - Beschädigte Ware
- `inventur_plus` - Inventur-Mehrbestand
- `inventur_minus` - Inventur-Minderbestand
- `korrektur` - Fehlerkorrektur
- `sonstiges` - Andere Gründe

#### Beleg-Nummern für Eigenentnahmen

**Format:** `ENT-YYYYMMDD-####`

Beispiel: `ENT-20251108-0001`

**Generierung:**

```python
today = datetime.now().date()
prefix = f"ENT-{today.strftime('%Y%m%d')}"
# Finde letzte Nummer des Tages
last_doc = StockAdjustment.query.filter(
    StockAdjustment.document_number.like(f"{prefix}%")
).order_by(StockAdjustment.document_number.desc()).first()
# Inkrementiere
next_num = (int(last_doc.document_number.split('-')[-1]) + 1) if last_doc else 1
document_number = f"{prefix}-{next_num:04d}"
```

**Wann wird Beleg-Nummer erstellt:**

- ✅ Bei `eigenentnahme` (privater Verbrauch)
- ✅ Bei `geschenk` (unentgeltliche Zuwendung)
- ❌ **Nicht** bei Inventur-Korrekturen (interne Buchung)
- ❌ **Nicht** bei Verderb/Bruch (nur Dokumentation)

#### Unveränderbarkeit

- **Keine Löschung** - Bestandsanpassungen können nicht gelöscht werden
- **Keine Änderung** - Einträge sind unveränderbar
- **Vollständige Historie** - Alle Anpassungen bleiben dauerhaft gespeichert

#### Route-Implementierung

**Datei:** `app.py`

**Neue Anpassung erstellen:**

```python
@app.route('/stock-adjustments/create', methods=['GET', 'POST'])
@login_required
def create_stock_adjustment():
    # Validierung
    if new_stock < 0:
        flash('Bestand würde negativ werden!', 'error')
        return redirect(...)

    # Erstelle Anpassung
    adjustment = StockAdjustment(
        product_id=product.id,
        quantity=quantity,
        old_stock=old_stock,
        new_stock=new_stock,
        adjustment_type=adjustment_type,
        reason=reason,
        adjusted_by=current_user.id,
        document_number=document_number  # Falls eigenentnahme/geschenk
    )

    # Bestand aktualisieren
    product.number = new_stock
    db.session.commit()
```

#### PDF-Export (GoBD Z2-Datenzugriff)

**Route:** `/stock-adjustments/export-pdf`

Exportiert alle Bestandsanpassungen als PDF-Übersicht:

- Datum, Produkt, Typ, Menge, Bestand vorher/nachher
- Grund, Benutzer, Beleg-Nummer
- Zeitraum-Filter möglich
- Landschaftsformat (A4 quer)

**Verwendung bei Betriebsprüfung:**

```bash
# Export für Zeitraum
GET /stock-adjustments/export-pdf?start_date=2024-01-01&end_date=2024-12-31

# Export nur Eigenentnahmen
GET /stock-adjustments/export-pdf?adjustment_type=eigenentnahme
```

### Steuerliche Relevanz

#### Eigenentnahme (§ 3 Abs. 1b Nr. 1 UStG)

Entnahme von Gegenständen für private Zwecke ist **umsatzsteuerpflichtig**.

**Bewertung:**

- Kleinunternehmer (§ 19 UStG): Keine USt-Pflicht
- Regelbesteuerung: USt auf Einkaufspreis/Herstellungskosten
- Landwirt (§ 24 UStG): Durchschnittssatz

**Dokumentation erforderlich:**

- ✅ Datum der Entnahme
- ✅ Menge und Bezeichnung
- ✅ Grund ("privater Verbrauch")
- ✅ Beleg-Nummer

#### Geschenke

Unentgeltliche Zuwendungen > 35 EUR sind USt-pflichtig.

**Dokumentation erforderlich:**

- ✅ Empfänger (im Feld "Grund" vermerken)
- ✅ Anlass
- ✅ Wert

#### Verderb/Bruch

Keine steuerliche Relevanz, aber Dokumentation notwendig:

- Nachweis für Bestandsminderung
- Plausibilität für Inventur
- Betriebsprüfung

### Verfahrensdokumentation

**Prozess: Eigenentnahme dokumentieren**

1. Navigation: **📝 Anpassungen** → "Neue Anpassung"
1. Produkt auswählen
1. Typ: "🏠 Eigenentnahme"
1. Menge: Negativ (z.B. `-5`)
1. Grund: "5 Gläser Honig für privaten Verbrauch entnommen"
1. Speichern
   - ➜ Beleg-Nummer wird generiert: `ENT-20251108-0001`
   - ➜ Bestand wird automatisch reduziert
   - ➜ Eintrag ist unveränderbar

**Prozess: PDF-Export für Steuerberater**

1. Navigation: **📝 Anpassungen**
1. Klick auf "PDF exportieren"
1. Optional: Filter setzen (Zeitraum, Typ)
1. PDF wird generiert und heruntergeladen

### Beispiel-Einträge

| Datum | Produkt | Typ | Menge | Alt → Neu | Grund | Beleg-Nr. |
|-------|---------|-----|-------|-----------|-------|-----------| | 08.11.2024 |
Waldhonig 500g | Eigenentnahme | -5 | 100 → 95 | 5 Gläser für privaten Verbrauch
| ENT-20241108-0001 | | 08.11.2024 | Blütenhonig 500g | Geschenk | -2 | 150 →
148 | Geschenk an Nachbarn (Weihnachten) | ENT-20241108-0002 | | 08.11.2024 |
Rapshonig 500g | Inventur + | +10 | 80 → 90 | Inventur: 10 Gläser mehr gefunden
| - | | 08.11.2024 | Akazienhonig 500g | Verderb | -3 | 50 → 47 |
Kristallisiert, nicht mehr verkaufbar | - |

______________________________________________________________________

## 9. Datenschutz (DSGVO) & Anonymisierung

### 9.1 Der Konflikt: GoBD vs. DSGVO

Die Datenschutz-Grundverordnung (DSGVO) und die GoBD-Aufbewahrungspflichten
stehen in einem scheinbaren Widerspruch:

- **DSGVO Art. 17**: Recht auf Löschung personenbezogener Daten
- **§ 147 AO**: 10 Jahre Aufbewahrungspflicht für Rechnungen
- **GoBD**: Unveränderbarkeit steuerrelevanter Belege

**Lösung:** Anonymisierung statt Löschung

### 9.2 Rechtliche Grundlage

**DSGVO Art. 17 Abs. 3 Buchstabe b:**

> Das Recht auf Löschung gilt nicht, soweit die Verarbeitung erforderlich ist
> zur Erfüllung einer rechtlichen Verpflichtung [...], der der Verantwortliche
> unterliegt.

**Interpretation:**

- Rechnungen müssen 10 Jahre aufbewahrt werden (§ 147 AO)
- Dies ist eine **rechtliche Verpflichtung**
- **Kundenstammdaten** können anonymisiert werden
- **Rechnungsdaten** müssen unverändert bleiben (GoBD-Hash!)

### 9.3 Implementierung: Denormalisierte Datenstruktur

Das System verwendet eine **denormalisierte Speicherung** der Kundendaten in
Rechnungen:

```sql
-- Kunde (kann anonymisiert werden)
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(200),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    email VARCHAR(120),
    phone VARCHAR(50),
    address TEXT,
    tax_id VARCHAR(50)
);

-- Rechnung (speichert Kundendaten redundant)
CREATE TABLE invoices (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    -- Denormalisiert: Kundendaten werden KOPIERT
    customer_company VARCHAR(200),
    customer_name VARCHAR(200),
    customer_address TEXT,
    customer_email VARCHAR(120),
    customer_phone VARCHAR(50),
    customer_tax_id VARCHAR(50),
    -- ... weitere Felder
    data_hash VARCHAR(64) NOT NULL  -- SHA-256 Hash ALLER Daten
);
```

**Vorteil dieser Struktur:**

- ✅ Kundenstamm kann anonymisiert werden
- ✅ Rechnungen bleiben unverändert (Hash bleibt gültig)
- ✅ GoBD-Konformität erhalten
- ✅ DSGVO-Konformität erfüllt

### 9.4 Anonymisierungs-Funktion

**Datei:** `models.py` - Klasse `Customer`

```python
def anonymize_gdpr(self):
    """
    Anonymisiert Kundendaten gemäß DSGVO Art. 17.

    WICHTIG: Bestehende Rechnungen bleiben unverändert (GoBD-konform).
    Die denormalisierten Kundendaten in den Rechnungen (customer_company,
    customer_name, etc.) werden NICHT verändert, um die Manipulationssicherheit
    (data_hash) zu erhalten und die steuerrechtlichen Aufbewahrungspflichten
    (§147 AO - 10 Jahre) zu erfüllen.

    DSGVO Art. 17 Abs. 3 Buchstabe b: Das Recht auf Löschung gilt nicht,
    wenn die Verarbeitung zur Erfüllung einer rechtlichen Verpflichtung
    erforderlich ist.
    """
    self.first_name = "Anonymisiert"
    self.last_name = f"Kunde #{self.id}"
    self.email = f"deleted_{self.id}@anonymized.local"
    self.phone = None
    self.address = None
    self.tax_id = None
    self.company_name = f"Gelöschter Kunde #{self.id}"

@property
def is_anonymized(self):
    """Prüft ob Kunde anonymisiert wurde"""
    return self.email and self.email.startswith('deleted_') and '@anonymized.local' in self.email
```

### 9.5 Route-Implementierung

**Datei:** `app.py`

**Route:** `POST /customers/<id>/anonymize`

```python
@app.route('/customers/<int:customer_id>/anonymize', methods=['POST'])
@login_required
def anonymize_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    # Bereits anonymisiert?
    if customer.is_anonymized:
        flash('Dieser Kunde wurde bereits anonymisiert.', 'warning')
        return redirect(url_for('list_customers'))

    # Anzahl verknüpfter Rechnungen ermitteln
    invoice_count = Invoice.query.filter_by(customer_id=customer_id).count()

    # Audit-Log
    app.logger.info(
        f"DSGVO-Anonymisierung durchgeführt | "
        f"Kunde ID: {customer_id} | "
        f"Original: {customer.display_name} ({customer.email}) | "
        f"Benutzer: {current_user.username} | "
        f"Verknüpfte Rechnungen: {invoice_count} (bleiben unverändert gemäß §147 AO)"
    )

    # Anonymisierung durchführen
    customer.anonymize_gdpr()
    db.session.commit()

    if invoice_count > 0:
        flash(
            f'Kunde erfolgreich anonymisiert. '
            f'{invoice_count} bestehende Rechnung(en) bleiben aus steuerrechtlichen Gründen '
            f'(§147 AO - 10 Jahre Aufbewahrungspflicht) unverändert und zeigen weiterhin die Originaldaten. '
            f'Dies ist DSGVO-konform gemäß Art. 17 Abs. 3 Buchstabe b.',
            'success'
        )
```

### 9.6 Benutzeroberfläche

#### Kundenliste

**Datei:** `templates/customers/list.html`

Anonymisierte Kunden werden markiert:

```html
<td>
    <strong>{{ customer.display_name }}</strong>
    {% if customer.is_anonymized %}
    <span style="color: #95a5a6; font-size: 0.85rem; margin-left: 0.5rem;"
          title="DSGVO-anonymisiert">
        🔒 Anonymisiert
    </span>
    {% endif %}
</td>
```

#### Kundendetails

**Datei:** `templates/customers/view.html`

**Anonymisierungs-Button:**

```html
{% if not customer.is_anonymized %}
<button type="button" class="btn" style="background: #e74c3c; color: white;"
        onclick="document.getElementById('anonymize-modal').style.display='block'">
    DSGVO Anonymisieren
</button>
{% endif %}
```

**Warnung nach Anonymisierung:**

```html
{% if customer.is_anonymized %}
<div class="alert alert-warning">
    <strong>⚠️ Anonymisiert:</strong> Dieser Kunde wurde gemäß DSGVO anonymisiert.
    Die personenbezogenen Daten wurden gelöscht.
</div>
{% endif %}
```

**Bestätigungs-Modal:**

- Zeigt Anzahl verknüpfter Rechnungen
- Erklärt, was anonymisiert wird
- Erklärt, was unverändert bleibt
- Rechtliche Grundlage (DSGVO Art. 17 Abs. 3b)
- Warnung vor Unumkehrbarkeit
- Bestätigung erforderlich

### 9.7 Verfahrensdokumentation

#### Prozess: DSGVO-Löschantrag bearbeiten

1. **Anfrage erhalten**

   - Kunde stellt Löschantrag gemäß DSGVO Art. 17

1. **Prüfung**

   - Bestehen Rechnungen für diesen Kunden?
   - Sind diese noch innerhalb der 10-Jahres-Frist?

1. **Anonymisierung durchführen**

   - Navigation: **Kunden** → Kunde auswählen → "DSGVO Anonymisieren"
   - Modal erscheint mit Informationen
   - Bestätigung klicken
   - ➜ Kundenstammdaten werden anonymisiert
   - ➜ Rechnungen bleiben unverändert

1. **Bestätigung an Kunde**

   - E-Mail: "Ihre personenbezogenen Daten wurden aus unserem Kundenstamm
     gelöscht."
   - **Wichtig:** Erklären, dass Rechnungen aus steuerrechtlichen Gründen
     aufbewahrt werden müssen

1. **Audit-Log-Eintrag**

   - Wird automatisch erstellt
   - Enthält: Original-Daten (Hash), Datum, Benutzer, Anzahl Rechnungen

#### Beispiel-E-Mail an Kunden

```
Betreff: Ihre DSGVO-Löschungsanfrage

Sehr geehrte/r [Kunde],

wir haben Ihre Löschungsanfrage vom [Datum] erhalten und bearbeitet.

✅ GELÖSCHT:
- Ihre Kontaktdaten (Name, Adresse, E-Mail, Telefon)
- Ihr Kundenprofil wurde anonymisiert

ℹ️ AUFBEWAHRUNGSPFLICHT:
Gemäß § 147 AO (Abgabenordnung) sind wir verpflichtet, Rechnungen
10 Jahre lang aufzubewahren. Diese enthalten weiterhin Ihre Daten
zum Zeitpunkt der Rechnungsstellung.

RECHTLICHE GRUNDLAGE:
DSGVO Art. 17 Abs. 3 Buchstabe b: Das Recht auf Löschung gilt nicht,
wenn die Verarbeitung zur Erfüllung einer rechtlichen Verpflichtung
erforderlich ist.

Bei Fragen stehen wir Ihnen gerne zur Verfügung.

Mit freundlichen Grüßen
[Ihre Firma]
```

### 9.8 Was wird anonymisiert?

#### ✅ Kundenstammdaten (Tabelle `customers`)

| Feld | Vorher | Nachher | |------|--------|---------| | `first_name` | "Hans"
| "Anonymisiert" | | `last_name` | "Müller" | "Kunde #123" | | `email` |
"hans@example.com" | "deleted_123@anonymized.local" | | `phone` | "+49 123
456789" | `NULL` | | `address` | "Musterstr. 1, ..." | `NULL` | | `tax_id` |
"DE123456789" | `NULL` | | `company_name` | "Müller GmbH" | "Gelöschter Kunde
#123" |

#### ❌ NICHT anonymisiert (bleiben unverändert)

- **Rechnungen** (Tabelle `invoices`)

  - `customer_company` - Originalwert
  - `customer_name` - Originalwert
  - `customer_address` - Originalwert
  - `customer_email` - Originalwert
  - `customer_phone` - Originalwert
  - `customer_tax_id` - Originalwert
  - **`data_hash`** - Bleibt gültig! ✅

- **Rechnungs-PDFs**

  - Zeigen Originaldaten
  - PDF-Hash bleibt gültig

- **Status-Logs**

  - Keine personenbezogenen Daten enthalten

- **Bestandsanpassungen**

  - User-ID bleibt (technische Zuordnung)

### 9.9 Hash-Integrität nach Anonymisierung

**Kritischer Punkt:** Der `data_hash` darf NICHT brechen!

**Warum funktioniert es:**

1. **Hash wird aus Rechnungsdaten berechnet**

   ```python
   # models.py - Invoice.calculate_hash()
   hash_data = {
       'invoice_number': self.invoice_number,
       'customer_company': self.customer_company,  # Denormalisiert!
       'customer_name': self.customer_name,        # Denormalisiert!
       'customer_address': self.customer_address,  # Denormalisiert!
       # ... weitere Felder
   }
   ```

1. **Kundenstamm wird NICHT verwendet**

   - Hash referenziert NICHT `customers.first_name`
   - Hash referenziert NUR `invoices.customer_name`
   - Diese Felder werden bei Anonymisierung NICHT geändert

1. **Ergebnis:**

   - ✅ Kundenstamm: Anonymisiert
   - ✅ Rechnung: Unverändert
   - ✅ Hash: Gültig
   - ✅ GoBD: Erfüllt
   - ✅ DSGVO: Erfüllt

### 9.10 Betriebsprüfung & Datenschutz

**Frage des Finanzamts:** "Warum sind hier anonymisierte Kunden?"

**Antwort:**

> "Wir haben DSGVO-Löschanträge erhalten. Die Kundenstammdaten wurden
> anonymisiert, aber alle steuerrelevanten Rechnungen sind vollständig erhalten
> und durch SHA-256 Hashes geschützt. Die Rechnungen zeigen weiterhin die
> korrekten Kundendaten zum Zeitpunkt der Rechnungsstellung."

**Frage der Datenschutzbehörde:** "Warum speichern Sie noch Kundendaten in
Rechnungen?"

**Antwort:**

> "Diese Daten unterliegen der 10-jährigen Aufbewahrungspflicht gemäß § 147 AO.
> DSGVO Art. 17 Abs. 3 Buchstabe b erlaubt die Speicherung zur Erfüllung
> rechtlicher Verpflichtungen. Personenbezogene Daten im Kundenstamm wurden
> gelöscht."

### 9.11 Weitere personenbezogene Daten im System

| Daten | Speicherort | DSGVO-Behandlung |
|-------|-------------|------------------| | Benutzerdaten (Mitarbeiter) |
`users` | Anonymisierung bei Kündigung möglich | | IP-Adressen (Login-Logs) |
`security.log` | Automatische Löschung nach 90 Tagen (empfohlen) | |
E-Mail-Archiv | `email_archive` | Automatische Löschung nach 30 Tagen
(empfohlen) | | PDF-Archiv-Metadaten | `invoice_pdf_archive` | Keine
personenbezogenen Daten (nur Hashes) |

### 9.12 Checkliste: DSGVO-Konformität

| Anforderung | Status | Implementierung |
|-------------|--------|-----------------| | ✅ Recht auf Auskunft (Art. 15) |
Erfüllt | Kundendetails exportierbar | | ✅ Recht auf Berichtigung (Art. 16) |
Erfüllt | Kunde bearbeiten (Stammdaten) | | ✅ Recht auf Löschung (Art. 17) |
Erfüllt | Anonymisierungsfunktion | | ✅ Aufbewahrungspflicht (§ 147 AO) |
Erfüllt | Rechnungen unverändert | | ✅ Hash-Integrität | Erfüllt |
Denormalisierte Struktur | | ✅ Audit-Trail | Erfüllt | Anonymisierung wird
protokolliert | | ✅ Rechtsgrundlage dokumentiert | Erfüllt | DSGVO Art. 17 Abs.
3b |

______________________________________________________________________

## 10. Backup-Strategie

### Empfohlene Maßnahmen

1. **Datenbank-Backup**

   - Täglich vollständig sichern
   - Transaktionslogs archivieren
   - Aufbewahrung: **10 Jahre** (gesetzliche Frist)

1. **PDF-Dateien**

   - Separate Sicherung aller PDFs
   - Aufbewahrung: **10 Jahre**
   - Optional: Zusätzliche Hash-Datei erstellen

1. **Beispiel-Backup-Skript:**

   ```bash
   #!/bin/bash
   # Datenbank
   pg_dump -U user rechnungen > backup_$(date +%Y%m%d).sql

   # PDFs
   tar -czf pdfs_$(date +%Y%m%d).tar.gz invoices/pdfs/

   # Hashes exportieren
   psql -U user -d rechnungen -c "COPY invoice_pdf_archive TO '/backups/hashes_$(date +%Y%m%d).csv' CSV HEADER;"
   ```

______________________________________________________________________

## 9. Datenschutz (DSGVO)

### Personenbezogene Daten

**Gespeichert in:**

- `customers`: Name, E-Mail, Adresse, Telefon
- `invoices`: Kundenbezug
- `invoice_status_log`: Benutzer (bei Implementierung)

### Löschung

**Problem:** GoBD verbietet Löschung, DSGVO fordert Löschung

**Lösung:**

- Anonymisierung statt Löschung:
  ```sql
  UPDATE customers
  SET first_name = 'ANONYMISIERT',
      last_name = 'ANONYMISIERT',
      email = 'deleted@example.com',
      phone = NULL,
      address = NULL
  WHERE id = ?;
  ```
- Rechnungen bleiben bestehen (10 Jahre Aufbewahrungspflicht)
- Hash-Werte bleiben unverändert (keine personenbezogenen Daten)

______________________________________________________________________

## 11. Betriebsprüfung (Finanzamt)

### Z1 - Datenzugriff

Das System ermöglicht den gesetzlich geforderten Datenzugriff:

1. **Z1 (Nur-Lesezugriff)**

   - Rechnung-Detailansicht
   - Status-Historie-Anzeige
   - PDF-Download mit Hash-Verifizierung

1. **Z2 (Maschinell auswertbare Datenträger)**

   ```bash
   # Rechnungen exportieren (CSV)
   psql -U user -d rechnungen -c "COPY (
       SELECT i.*, c.company_name, c.first_name, c.last_name
       FROM invoices i
       LEFT JOIN customers c ON i.customer_id = c.id
   ) TO '/export/invoices.csv' CSV HEADER;"

   # Status-Historie exportieren
   psql -U user -d rechnungen -c "COPY invoice_status_log TO '/export/audit_trail.csv' CSV HEADER;"

   # PDF-Hashes exportieren
   psql -U user -d rechnungen -c "COPY invoice_pdf_archive TO '/export/pdf_hashes.csv' CSV HEADER;"

   # Bestandsanpassungen exportieren (NEU)
   psql -U user -d rechnungen -c "COPY stock_adjustments TO '/export/stock_adjustments.csv' CSV HEADER;"

   # Oder: PDF-Export über Weboberfläche
   # → Navigation: 📝 Anpassungen → "PDF exportieren"
   ```

1. **Z3 (Unmittelbarer Datenzugriff)**

   - Finanzamt erhält Datenbank-Lesezugriff
   - Oder: Read-Only-Benutzer anlegen

### Verfahrensdokumentation für Betriebsprüfung

**Dieses Dokument (`GOBD_COMPLIANCE.md`) dient als Verfahrensdokumentation!**

Zusätzlich bereithalten:

- Systembeschreibung (diese Datei)
- Installationsanleitung
- Backup-Konzept
- Benutzerhandbuch
- Migrationsprotokoll

______________________________________________________________________

## 12. Checkliste: GoBD-Konformität

| Anforderung | Status | Implementierung |
|-------------|--------|-----------------| | ✅ Unveränderbarkeit | Erfüllt |
Status-Workflow-Validierung, Entwürfe löschbar | | ✅ Nachvollziehbarkeit |
Erfüllt | `InvoiceStatusLog` + `StockAdjustment` (Audit Trail) | | ✅
Vollständigkeit | Erfüllt | Keine Löschung ab Status `sent`, nur Stornierung | |
✅ Richtigkeit | Erfüllt | SHA-256 Hash-Prüfung | | ✅ Zeitgerechte Buchung |
Erfüllt | Automatische Timestamps (Mikrosekunden-genau) | | ✅ Ordnung | Erfüllt
| Fortlaufende Rechnungsnummern + Beleg-Nummern | | ✅ Sicherheit | Erfüllt |
PDF-Hashes, Datenbankindizes | | ✅ Verfügbarkeit | Erfüllt | Backup-Konzept | |
✅ Datenzugriff | Erfüllt | Export-Funktionen (PDF, SQL) | | ✅ Prüfbarkeit |
Erfüllt | Vollständige Dokumentation | | ✅ Entwurfsverwaltung | Erfüllt |
Löschung nur bei Status `draft` | | ✅ Bestandsanpassungen | Erfüllt |
Eigenentnahme mit Beleg-Nummern, PDF-Export | | ✅ DSGVO-Konformität | Erfüllt |
Anonymisierung ohne Hash-Verletzung | | ✅ Datenschutz-Dokumentation | Erfüllt |
Art. 17 Abs. 3b dokumentiert |

______________________________________________________________________

## 13. Technische Details

### Verwendete Hash-Algorithmen

- **SHA-256** für Rechnungsdaten und PDFs
- Kodierung: Hexadezimal (64 Zeichen)

### Zeitstempel

- Format: `TIMESTAMP` (Mikrosekunden-genau)
- Zeitzone: UTC (empfohlen) oder Serverzeit
- **Wichtig:** Keine nachträgliche Änderung!

### Software-Versionen

- Python: 3.8+
- Flask: 3.0+
- SQLAlchemy: 2.0+
- PostgreSQL: 12+
- ReportLab: 4.0+ (PDF-Generierung)

______________________________________________________________________

## 14. Erweiterungsmöglichkeiten

### Zukünftige Verbesserungen

1. **Benutzer-Authentifizierung**

   - Ersetze `"System"` durch echte Benutzernamen
   - Implementiere Login/Logout
   - Erfasse IP-Adressen bei Änderungen

1. **Digitale Signatur**

   - PDF-Signierung mit Zertifikat
   - Langzeit-Archivierung (PAdES)

1. **Automatische Backups**

   - Cron-Job für tägliche Backups
   - Cloud-Synchronisation
   - Integritätsprüfung der Backups

1. **API-Endpunkt für Verifizierung**

   ```python
   @app.route('/api/verify/<invoice_id>')
   def verify_invoice_api(invoice_id):
       # Prüfe Hash, PDF-Hash
       # Gebe JSON zurück
   ```

1. **Erweiterte Audit-Logs**

   - IP-Adresse
   - User-Agent
   - Geänderte Felder (vor/nach)

______________________________________________________________________

## 15. Häufige Fragen (FAQ)

**Q: Kann ich eine Rechnung löschen?** A: **Entwürfe (Status `draft`) JA** -
Diese sind noch nicht geschäftsrelevant und können gelöscht werden.
**Versendete/Bezahlte Rechnungen NEIN** - Diese müssen 10 Jahre aufbewahrt
werden. Verwenden Sie stattdessen die Stornorechnung.

**Q: Warum kann ich einen Entwurf löschen, aber eine versendete Rechnung
nicht?** A: Ein Entwurf ist noch keine Rechnung im steuerrechtlichen Sinne. Die
GoBD-Aufbewahrungspflicht beginnt erst mit der Versendung (Status `sent`). Ab
diesem Zeitpunkt ist die Rechnung unveränderbar und muss 10 Jahre aufbewahrt
werden.

**Q: Was ist der Unterschied zwischen Löschen und Stornieren?** A:

- **Löschen** (nur Entwürfe): Rechnung wird komplett aus der Datenbank entfernt
- **Stornieren** (versendete/bezahlte): Originalrechnung bleibt bestehen, neue
  Stornorechnung mit negativen Beträgen wird erstellt

**Q: Was passiert, wenn der Hash nicht übereinstimmt?** A: Das System zeigt eine
Warnung an. Die Daten wurden möglicherweise manipuliert oder die
Datenbankintegrität ist beschädigt.

**Q: Muss ich PDFs archivieren?** A: Ja. Das System speichert automatisch einen
Hash beim ersten Download. Die PDF-Dateien selbst sollten in einem separaten
Backup gesichert werden.

**Q: Was ist, wenn ein Kunde Löschung seiner Daten fordert (DSGVO)?** A:
Anonymisieren Sie die Kundendaten. Die Rechnung selbst muss 10 Jahre aufbewahrt
werden (GoBD hat Vorrang).

**Q: Wie kann ich die Integrität einer PDF-Datei prüfen?** A: Verwenden Sie die
`verify_pdf()` Methode oder berechnen Sie den SHA-256 Hash manuell und
vergleichen Sie ihn mit dem gespeicherten Hash.

______________________________________________________________________

## 16. Kontakt & Support

**Entwickler:** [Ihr Name] **Version:** 1.0 **Letzte Aktualisierung:** Dezember
2024

**Bei Fragen zur GoBD-Konformität:**

- Steuerberater konsultieren
- Fachliteratur: BMF-Schreiben vom 28.11.2019
- IHK-Beratung

______________________________________________________________________

## 17. Lizenz & Haftungsausschluss

Dieses System wurde nach bestem Wissen und Gewissen entwickelt, um die
GoBD-Anforderungen zu erfüllen. Eine rechtliche Prüfung durch einen
Steuerberater wird empfohlen.

**Keine Gewährleistung:** Die korrekte Implementierung und Anwendung der GoBD
liegt in der Verantwortung des Anwenders.

______________________________________________________________________

**Ende der Verfahrensdokumentation**
