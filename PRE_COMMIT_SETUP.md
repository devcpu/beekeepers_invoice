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
pre-commit run djlint-reformat-jinja --all-files
```

## Was wird geprüft?

### Python Code

- **black**: Code-Formatierung (160 Zeichen/Zeile)
- **flake8**: Linting & Style-Guide (PEP8)
- **isort**: Import-Sortierung
- **pylint**: zusätzliches Linting (mit projektspezifischen Disables)
- **bandit**: Security-Checks
- **py-compile**: Syntax-Check
- **safety**: Dependency-Sicherheitscheck

### HTML & Jinja2 Templates

- **djlint**: Jinja2-Reformatierung (Ersatz für das früher genutzte jinjalint)
- **curlylint**: HTML + Jinja2 Best Practices
  - Alt-Texte für Bilder
  - ARIA-Rollen
  - HTML lang-Attribut
  - Einrückung

### SQL

- **sqlfluff**: SQL-Linting (lint + fix)

### Allgemein

- Trailing Whitespace entfernen
- End-of-File Newline
- YAML/JSON Syntax
- Keine großen Dateien (>1MB)
- Merge-Konflikte erkennen
- Private Keys erkennen

## Häufige Probleme

### djlint: Reformatierung schlägt fehl

```bash
# Findet Syntax-Fehler wie doppelte {% endblock %}
pre-commit run djlint-reformat-jinja --all-files
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
- `.jinjalintrc` - djlint-Konfiguration
- `setup.cfg` - Python Tools (black, flake8, isort, pylint, pytest)
