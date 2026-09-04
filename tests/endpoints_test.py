"""Sicherheitsnetz fuer den Blueprint-Split: jeder statische url_for()-Aufruf in
app.py, blueprints/ und templates/ muss auf einen tatsaechlich registrierten
Endpoint zeigen.

Deckt genau die Fehlerklasse ab, die ein Blueprint-Split produziert (falscher
oder vergessener Praefix), inkl. Templates ohne eigenen Route-Test
(delivery_notes/, consignment/, payments/, reports/, stock_adjustments/).
Findet nur statische Endpoint-Strings (url_for("name", ...)) -- dynamische
Aufrufe (url_for(variable)) gibt es aktuell weder in app.py noch in templates/
(verifiziert per grep vor Erstellung dieses Tests).
"""

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENDPOINT_PATTERN = re.compile(r"""url_for\(\s*['"]([a-zA-Z0-9_.]+)['"]""")


def _find_static_endpoint_refs(path):
    refs = {}
    for match in _ENDPOINT_PATTERN.finditer(path.read_text(encoding="utf-8")):
        refs.setdefault(match.group(1), []).append(path)
    return refs


def test_all_template_endpoints_resolve(app):
    missing = []
    for template_file in sorted((_PROJECT_ROOT / "templates").rglob("*.html")):
        for endpoint in _find_static_endpoint_refs(template_file):
            if endpoint not in app.view_functions:
                missing.append(f"{template_file.relative_to(_PROJECT_ROOT)}: {endpoint}")
    assert not missing, "Unbekannte Endpoints in Templates:\n" + "\n".join(missing)


def test_all_app_py_endpoints_resolve(app):
    missing = []
    app_py = _PROJECT_ROOT / "app.py"
    for endpoint in _find_static_endpoint_refs(app_py):
        if endpoint not in app.view_functions:
            missing.append(endpoint)
    assert not missing, "Unbekannte Endpoints in app.py:\n" + "\n".join(missing)


def test_all_blueprint_endpoints_resolve(app):
    missing = []
    for py_file in sorted((_PROJECT_ROOT / "blueprints").glob("*.py")):
        for endpoint in _find_static_endpoint_refs(py_file):
            if endpoint not in app.view_functions:
                missing.append(f"{py_file.relative_to(_PROJECT_ROOT)}: {endpoint}")
    assert not missing, "Unbekannte Endpoints in blueprints/:\n" + "\n".join(missing)


def test_login_manager_login_view_resolves(app):
    assert app.login_manager.login_view in app.view_functions
