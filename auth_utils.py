"""Rollen-basierte Zugriffskontrolle fuer Flask-Routen (siehe AGENTS.md, Abschnitt "Rollen & Autorisierung")."""

from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user, login_required


def role_required(*roles):
    """Decorator fuer Rollen-basierte Zugriffskontrolle."""

    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if not any(current_user.has_role(role) for role in roles):
                flash("Sie haben keine Berechtigung für diese Aktion.", "danger")
                return redirect(url_for("main.index"))
            return f(*args, **kwargs)

        return decorated_function

    return decorator
