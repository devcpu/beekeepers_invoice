"""Einstellungen, Benutzerverwaltung und E-Mail-Konfigurationstest."""

import base64
import imaplib
import json
import secrets
import smtplib
import socket
from io import BytesIO

import qrcode
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from auth_utils import role_required
from models import Customer, DeviceToken, User, db

users_bp = Blueprint("users", __name__)


@users_bp.route("/settings")
@login_required
@role_required("admin")
def settings():
    """Einstellungen - Firmendaten anzeigen"""
    company_data = {
        "name": current_app.config.get("COMPANY_NAME"),
        "holder": current_app.config.get("COMPANY_HOLDER"),
        "street": current_app.config.get("COMPANY_STREET"),
        "zip": current_app.config.get("COMPANY_ZIP"),
        "city": current_app.config.get("COMPANY_CITY"),
        "country": current_app.config.get("COMPANY_COUNTRY"),
        "email": current_app.config.get("COMPANY_EMAIL"),
        "phone": current_app.config.get("COMPANY_PHONE"),
        "tax_id": current_app.config.get("COMPANY_TAX_ID"),
        "website": current_app.config.get("COMPANY_WEBSITE"),
    }
    bank_data = {
        "name": current_app.config.get("BANK_NAME"),
        "iban": current_app.config.get("BANK_IBAN"),
        "bic": current_app.config.get("BANK_BIC"),
    }
    return render_template("settings.html", company=company_data, bank=bank_data, config=current_app.config)


@users_bp.route("/settings/users")
@login_required
@role_required("admin")
def list_users():
    """User-Verwaltung - Liste aller Benutzer"""
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("users/list.html", users=users)


@users_bp.route("/settings/users/new", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_user():
    """Neuen Benutzer erstellen"""
    if request.method == "POST":
        try:
            username = request.form.get("username")
            email = request.form.get("email")
            password = request.form.get("password")
            role = request.form.get("role", "cashier")

            if User.query.filter_by(username=username).first():
                flash("Benutzername bereits vergeben.", "danger")
                return render_template("users/create.html")

            if User.query.filter_by(email=email).first():
                flash("E-Mail-Adresse bereits vergeben.", "danger")
                return render_template("users/create.html")

            user = User(username=username, email=email, role=role, is_active=True)
            user.set_password(password)

            if role == "reseller":
                customer_id = request.form.get("reseller_customer_id")
                if customer_id:
                    user.reseller_customer_id = int(customer_id)

            db.session.add(user)
            db.session.commit()

            flash(f'Benutzer "{username}" wurde erfolgreich erstellt.', "success")
            return redirect(url_for("users.list_users"))

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Erstellen des Benutzers: {str(e)}", "danger")

    customers = Customer.query.order_by(Customer.company_name).all()
    return render_template("users/create.html", customers=customers)


@users_bp.route("/settings/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit_user(user_id):
    """Benutzer bearbeiten"""
    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        try:
            new_email = request.form.get("email")
            if new_email != user.email:
                if User.query.filter_by(email=new_email).first():
                    flash("E-Mail-Adresse bereits vergeben.", "danger")
                    return render_template("users/edit.html", user=user, customers=Customer.query.all())
                user.email = new_email

            user.role = request.form.get("role", user.role)

            if user.role == "reseller":
                customer_id = request.form.get("reseller_customer_id")
                user.reseller_customer_id = int(customer_id) if customer_id else None
            else:
                user.reseller_customer_id = None

            user.is_active = request.form.get("is_active") == "on"

            user.totp_required = request.form.get("totp_required") == "on"

            new_password = request.form.get("new_password")
            if new_password:
                user.set_password(new_password)

            db.session.commit()
            flash(f'Benutzer "{user.username}" wurde aktualisiert.', "success")
            return redirect(url_for("users.list_users"))

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Aktualisieren des Benutzers: {str(e)}", "danger")

    customers = Customer.query.order_by(Customer.company_name).all()
    return render_template("users/edit.html", user=user, customers=customers)


@users_bp.route("/settings/users/<int:user_id>/toggle-active", methods=["POST"])
@login_required
@role_required("admin")
def toggle_user_active(user_id):
    """Benutzer aktivieren/deaktivieren"""
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("Sie können sich nicht selbst deaktivieren.", "danger")
        return redirect(url_for("users.list_users"))

    user.is_active = not user.is_active
    db.session.commit()

    status = "aktiviert" if user.is_active else "deaktiviert"
    flash(f'Benutzer "{user.username}" wurde {status}.', "success")
    return redirect(url_for("users.list_users"))


@users_bp.route("/settings/users/<int:user_id>/reset-2fa", methods=["POST"])
@login_required
@role_required("admin")
def reset_user_2fa(user_id):
    """2FA für Benutzer zurücksetzen"""
    user = User.query.get_or_404(user_id)

    user.totp_enabled = False
    user.totp_secret = None
    user.backup_codes = None
    db.session.commit()

    flash(f'2FA für "{user.username}" wurde zurückgesetzt.', "warning")
    return redirect(url_for("users.list_users"))


@users_bp.route("/settings/users/<int:user_id>/toggle-2fa-required", methods=["POST"])
@login_required
@role_required("admin")
def toggle_user_2fa_required(user_id):
    """2FA-Pflicht für Benutzer umschalten"""
    user = User.query.get_or_404(user_id)

    user.totp_required = not user.totp_required
    db.session.commit()

    if user.totp_required:
        flash(
            f'2FA ist jetzt Pflicht für "{user.username}". Der Benutzer muss 2FA beim nächsten Login einrichten.',
            "success",
        )
    else:
        flash(f'2FA-Pflicht für "{user.username}" wurde aufgehoben.', "info")

    return redirect(url_for("users.list_users"))


@users_bp.route("/settings/users/<int:user_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_user(user_id):
    """Benutzer löschen"""
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("Sie können sich nicht selbst löschen.", "danger")
        return redirect(url_for("users.list_users"))

    username = user.username
    db.session.delete(user)
    db.session.commit()

    flash(f'Benutzer "{username}" wurde gelöscht.', "success")
    return redirect(url_for("users.list_users"))


@users_bp.route("/settings/test-email", methods=["POST"])
@login_required
@role_required("admin")
def test_email_settings():
    """E-Mail-Einstellungen (SMTP und IMAP) testen"""
    results = {"smtp": {"success": False, "message": ""}, "imap": {"success": False, "message": ""}}

    try:
        smtp_server = current_app.config.get("MAIL_SERVER")
        smtp_port = current_app.config.get("MAIL_PORT")
        smtp_username = current_app.config.get("MAIL_USERNAME")
        smtp_password = current_app.config.get("MAIL_PASSWORD")
        smtp_use_ssl = current_app.config.get("MAIL_USE_SSL")

        if not smtp_server or not smtp_username or not smtp_password:
            results["smtp"]["message"] = "SMTP-Konfiguration unvollständig (Server, Username oder Passwort fehlt)"
        else:
            if smtp_use_ssl:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
                if current_app.config.get("MAIL_USE_TLS"):
                    server.starttls()

            server.login(smtp_username, smtp_password)
            server.quit()

            results["smtp"]["success"] = True
            results["smtp"]["message"] = f"Verbindung erfolgreich zu {smtp_server}:{smtp_port}"

    except smtplib.SMTPAuthenticationError:
        results["smtp"]["message"] = "Authentifizierung fehlgeschlagen - Benutzername oder Passwort falsch"
    except smtplib.SMTPException as e:
        results["smtp"]["message"] = f"SMTP-Fehler: {str(e)}"
    except socket.gaierror:
        results["smtp"]["message"] = f"Server {smtp_server} nicht erreichbar - DNS-Fehler"
    except socket.timeout:
        results["smtp"]["message"] = f"Zeitüberschreitung bei Verbindung zu {smtp_server}:{smtp_port}"
    except Exception as e:
        results["smtp"]["message"] = f"Unerwarteter Fehler: {str(e)}"

    try:
        imap_server = current_app.config.get("IMAP_SERVER")
        imap_port = current_app.config.get("IMAP_PORT")
        imap_username = current_app.config.get("IMAP_USERNAME")
        imap_password = current_app.config.get("IMAP_PASSWORD")
        imap_use_ssl = current_app.config.get("IMAP_USE_SSL")

        if not imap_server or not imap_username or not imap_password:
            results["imap"]["message"] = "IMAP-Konfiguration unvollständig (Server, Username oder Passwort fehlt)"
        else:
            if imap_use_ssl:
                mail = imaplib.IMAP4_SSL(imap_server, imap_port)
            else:
                mail = imaplib.IMAP4(imap_server, imap_port)

            mail.login(imap_username, imap_password)

            status, folders = mail.list()  # pylint: disable=unused-variable
            folder_count = len(folders) if folders else 0

            mail.logout()

            results["imap"]["success"] = True
            results["imap"]["message"] = f"Verbindung erfolgreich zu {imap_server}:{imap_port} ({folder_count} Ordner gefunden)"

    except imaplib.IMAP4.error as e:
        error_msg = str(e)
        if "authentication failed" in error_msg.lower():
            results["imap"]["message"] = "Authentifizierung fehlgeschlagen - Benutzername oder Passwort falsch"
        else:
            results["imap"]["message"] = f"IMAP-Fehler: {error_msg}"
    except socket.gaierror:
        results["imap"]["message"] = f"Server {imap_server} nicht erreichbar - DNS-Fehler"
    except socket.timeout:
        results["imap"]["message"] = f"Zeitüberschreitung bei Verbindung zu {imap_server}:{imap_port}"
    except Exception as e:
        results["imap"]["message"] = f"Unerwarteter Fehler: {str(e)}"

    if results["smtp"]["success"]:
        flash(f'✓ SMTP: {results["smtp"]["message"]}', "success")
    else:
        flash(f'✗ SMTP: {results["smtp"]["message"]}', "error")

    if results["imap"]["success"]:
        flash(f'✓ IMAP: {results["imap"]["message"]}', "success")
    else:
        flash(f'✗ IMAP: {results["imap"]["message"]}', "error")


def _build_device_token_qr(server_url, token):
    """Erzeugt den QR-Code fuer die Geraete-Kopplung als Base64-Data-URI.

    Payload ist bewusst JSON ({"server": ..., "token": ...}), nicht nur der
    nackte Token, damit eine Android-App die Server-URL nicht manuell
    braucht. Analog zum QR-Erzeugungsmuster in pdf_service.py:38-53, hier
    aber als Data-URI fuer die direkte Web-Anzeige statt als ReportLab-Image.
    """
    payload = json.dumps({"server": server_url, "token": token})
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


@users_bp.route("/settings/device-tokens")
@login_required
def list_device_tokens():
    """Liste der eigenen Geraete-Tokens (mehrere Geraete pro User moeglich)."""
    zugang = request.args.get("zugang", "local")
    if zugang not in ("local", "remote"):
        zugang = "local"

    server_url = current_app.config.get("APP_URL_LOCAL") if zugang == "local" else current_app.config.get("APP_URL_REMOTE")

    tokens = DeviceToken.query.filter_by(user_id=current_user.id).order_by(DeviceToken.created_at.desc()).all()

    neuer_token = None
    new_token_value = request.args.get("neuer_token")
    if new_token_value:
        neuer_token = next((t for t in tokens if t.token == new_token_value), None)

    qr_data_uri = _build_device_token_qr(server_url, neuer_token.token) if neuer_token and server_url else None

    return render_template(
        "users/device_tokens.html",
        tokens=tokens,
        zugang=zugang,
        app_url_local=current_app.config.get("APP_URL_LOCAL"),
        app_url_remote=current_app.config.get("APP_URL_REMOTE"),
        neuer_token=neuer_token,
        qr_data_uri=qr_data_uri,
    )


@users_bp.route("/settings/device-tokens/create", methods=["POST"])
@login_required
def create_device_token():
    """Neues Geraete-Token erzeugen (Label ist Pflicht, zur Unterscheidung mehrerer Geraete)."""
    label = request.form.get("label", "").strip()
    if not label:
        flash("Bitte eine Bezeichnung fuer das Geraet angeben.", "error")
        return redirect(url_for("users.list_device_tokens"))

    device_token = DeviceToken(user_id=current_user.id, label=label, token=secrets.token_urlsafe(32))
    db.session.add(device_token)
    db.session.commit()

    flash(f'Geraet "{label}" gekoppelt. Token/QR-Code jetzt notieren -- er wird danach nicht erneut angezeigt.', "success")
    return redirect(url_for("users.list_device_tokens", neuer_token=device_token.token, zugang=request.form.get("zugang", "local")))


@users_bp.route("/settings/device-tokens/<int:token_id>/revoke", methods=["POST"])
@login_required
def revoke_device_token(token_id):
    """Widerruft ein eigenes Geraete-Token. Auf user_id=current_user.id
    scopen (nicht get_or_404) -- sonst koennte ein Nutzer per erratener ID
    das Geraet eines anderen Users widerrufen (IDOR)."""
    device_token = DeviceToken.query.filter_by(id=token_id, user_id=current_user.id).first_or_404()

    label = device_token.label
    db.session.delete(device_token)
    db.session.commit()

    flash(f'Geraet "{label}" widerrufen.', "success")
    return redirect(url_for("users.list_device_tokens"))
