# Pre-commit Setup für Rechnungs-System

## Installation

```bash
# Pre-commit installieren
pip install pre-commit

# Hooks installieren
pre-commit install

# Optional: Pre-commit auch für push und commit-msg
pre-commit install --hook-type pre-push
pre-commit install --hook-type commit-msg
```

## Manuelle Ausführung

```bash
# Alle Hooks auf allen Dateien ausführen
pre-commit run --all-files

# Nur auf geänderten Dateien
pre-commit run

# Nur bestimmten Hook ausführen
pre-commit run black --all-files
pre-commit run curlylint --all-files
pre-commit run jinjalint --all-files
```

## Was wird geprüft?

### Python Code

- **black**: Code-Formatierung (120 Zeichen/Zeile)
- **flake8**: Linting & Style-Guide (PEP8)
- **isort**: Import-Sortierung
- **bandit**: Security-Checks

### HTML & Jinja2 Templates

- **jinjalint**: Jinja2-Syntax-Validierung
- **curlylint**: HTML + Jinja2 Best Practices
  - Alt-Texte für Bilder
  - ARIA-Rollen
  - HTML lang-Attribut
  - Einrückung

### SQL

- **sqlfluff**: PostgreSQL SQL-Linting

### Allgemein

- Trailing Whitespace entfernen
- End-of-File Newline
- YAML/JSON Syntax
- Keine großen Dateien (>1MB)
- Merge-Konflikte erkennen
- Private Keys erkennen

## Häufige Probleme

### Jinjalint: Syntax-Fehler

```bash
# Nur Syntax-Check, findet Fehler wie doppelte {% endblock %}
pre-commit run jinjalint --all-files
```

### Curlylint: Template-Warnings

```bash
# Kann automatisch fixen
curlylint --fix templates/
```

### Black: Code neu formatiert

Black formatiert automatisch - einfach committen:

```bash
git add -u
git commit -m "style: black auto-format"
```

## Hooks überspringen (Notfall)

```bash
# Alle Hooks überspringen
git commit --no-verify -m "..."

# Einzelne Hooks deaktivieren
SKIP=flake8,black git commit -m "..."
```

## CI Integration

Die Config ist bereits für pre-commit.ci vorbereitet:

- Wöchentliche automatische Updates
- Auto-fix für Pull Requests
- Security-Checks können langsam sein → Skip in CI

## Anpassungen

Alle Konfigurationsdateien:

- `.pre-commit-config.yaml` - Hauptkonfiguration
- `.curlylintrc.yaml` - HTML/Jinja2 Rules
- `.jinjalintrc` - Jinja2 Syntax
- `pyproject.toml` - Python Tools (black, isort, bandit)
