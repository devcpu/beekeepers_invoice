"""Authentifizierung, 2FA und Passwort-Reset."""

import base64
import io
import json
from datetime import datetime

import qrcode
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from models import ConsignmentStock, User, db

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Login-Seite"""
    from crowdsec_app import crowdsec_app

    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        remember = request.form.get("remember", False) == "on"

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_active:
                crowdsec_app.log_failed_login(username, reason="account_disabled")
                flash("Ihr Account wurde deaktiviert.", "danger")
                return redirect(url_for("auth.login"))

            if user.totp_required and not user.totp_enabled:
                login_user(user, remember=remember)
                user.last_login = datetime.utcnow()
                user.last_login_ip = request.remote_addr
                db.session.commit()

                flash(
                    "Ihr Administrator hat 2FA für Ihren Account verpflichtend gemacht. Bitte richten Sie 2FA jetzt ein.",
                    "warning",
                )
                return redirect(url_for("auth.setup_2fa"))

            if user.totp_enabled:
                session["pending_user_id"] = user.id
                session["remember_me"] = remember
                return redirect(url_for("auth.verify_2fa"))

            login_user(user, remember=remember)
            user.last_login = datetime.utcnow()
            user.last_login_ip = request.remote_addr
            db.session.commit()

            flash(f"Willkommen zurück, {user.username}!", "success")
            next_page = request.args.get("next")
            return redirect(next_page) if next_page else redirect(url_for("main.index"))
        else:
            crowdsec_app.log_failed_login(username or "unknown", reason="invalid_credentials")
            flash("Ungültiger Benutzername oder Passwort.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/verify-2fa", methods=["GET", "POST"])
def verify_2fa():
    """2FA-Verifizierung"""
    if "pending_user_id" not in session:
        return redirect(url_for("auth.login"))

    user = User.query.get(session["pending_user_id"])
    if not user:
        session.pop("pending_user_id", None)
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        token = request.form.get("token", "").replace(" ", "")

        if user.verify_totp(token):
            login_user(user, remember=session.get("remember_me", False))
            user.last_login = datetime.utcnow()
            user.last_login_ip = request.remote_addr
            db.session.commit()

            session.pop("pending_user_id", None)
            session.pop("remember_me", None)

            flash(f"Willkommen zurück, {user.username}!", "success")
            return redirect(url_for("main.index"))

        elif user.verify_backup_code(token):
            db.session.commit()

            login_user(user, remember=session.get("remember_me", False))
            user.last_login = datetime.utcnow()
            user.last_login_ip = request.remote_addr
            db.session.commit()

            session.pop("pending_user_id", None)
            session.pop("remember_me", None)

            flash(
                f"Login mit Backup-Code erfolgreich. Noch {len(json.loads(user.backup_codes)) if user.backup_codes else 0} Backup-Codes verfügbar.",
                "warning",
            )
            return redirect(url_for("main.index"))
        else:
            flash("Ungültiger 2FA-Code.", "danger")

    return render_template("auth/verify_2fa.html", user=user)


@auth_bp.route("/logout")
@login_required
def logout():
    """Logout"""
    logout_user()
    flash("Sie wurden erfolgreich abgemeldet.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/select-stock-source", methods=["GET", "POST"])
@login_required
def select_stock_source():
    """Bestandsquelle auswählen (Hauptbestand oder Marktbestand)"""
    if request.method == "POST":
        stock_source = request.form.get("stock_source")
        if stock_source in ["main", "market"]:
            session["stock_source"] = stock_source
            flash(
                f'Bestandsquelle gewählt: {"Hauptbestand (Zuhause)" if stock_source == "main" else "Marktbestand (Markt)"}',
                "success",
            )
            return redirect(url_for("main.index"))
        else:
            flash("Ungültige Auswahl.", "error")

    has_market_stock = False
    if current_user.reseller_customer_id:
        has_market_stock = ConsignmentStock.query.filter_by(customer_id=current_user.reseller_customer_id).first() is not None

    return render_template("select_stock_source.html", has_market_stock=has_market_stock)


@auth_bp.route("/offline")
def offline():
    """PWA Offline-Fallback Seite"""
    return render_template("offline.html")


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Passwort vergessen - E-Mail-Anfrage"""
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        email = request.form.get("email")
        user = User.query.filter_by(email=email).first()

        if user and user.is_active:
            from email_service import mail
            from password_reset import PasswordResetToken, send_password_reset_email

            token = PasswordResetToken.create_reset_token(user)

            try:
                send_password_reset_email(user, token, mail)
                flash("Eine E-Mail mit Anweisungen zum Zurücksetzen des Passworts wurde gesendet.", "success")
            except Exception as e:
                current_app.logger.error("Fehler beim Senden der Reset-E-Mail: %s", str(e))
                flash("Fehler beim Senden der E-Mail. Bitte kontaktieren Sie den Administrator.", "danger")
        else:
            flash("Eine E-Mail mit Anweisungen zum Zurücksetzen des Passworts wurde gesendet.", "success")

        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Passwort zurücksetzen mit Token"""
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    from password_reset import PasswordResetToken

    user = PasswordResetToken.verify_token(token)

    if not user:
        flash("Ungültiger oder abgelaufener Reset-Link.", "danger")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = request.form.get("password")
        password_confirm = request.form.get("password_confirm")

        if password != password_confirm:
            flash("Die Passwörter stimmen nicht überein.", "danger")
            return render_template("auth/reset_password.html", token=token)

        if len(password) < 8:
            flash("Das Passwort muss mindestens 8 Zeichen lang sein.", "danger")
            return render_template("auth/reset_password.html", token=token)

        user.set_password(password)
        PasswordResetToken.invalidate_token(user)

        flash("Ihr Passwort wurde erfolgreich zurückgesetzt. Sie können sich jetzt anmelden.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)


@auth_bp.route("/settings/2fa-setup", methods=["GET", "POST"])
@login_required
def setup_2fa():
    """2FA aktivieren"""
    if current_user.totp_enabled:
        flash("2FA ist bereits aktiviert.", "info")
        return redirect(url_for("users.settings"))

    if request.method == "POST":
        token = request.form.get("token", "").replace(" ", "")

        if current_user.verify_totp(token):
            current_user.totp_enabled = True

            backup_codes = current_user.generate_backup_codes()
            db.session.commit()

            flash("2FA wurde erfolgreich aktiviert! Bewahren Sie Ihre Backup-Codes sicher auf.", "success")
            return render_template("auth/2fa_backup_codes.html", backup_codes=backup_codes)
        else:
            flash("Ungültiger Code. Bitte versuchen Sie es erneut.", "danger")

    if not current_user.totp_secret:
        current_user.generate_totp_secret()
        db.session.commit()

    totp_uri = current_user.get_totp_uri()
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(totp_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()

    return render_template("auth/2fa_setup.html", qr_code=qr_code_base64, totp_secret=current_user.totp_secret)


@auth_bp.route("/settings/2fa-disable", methods=["POST"])
@login_required
def disable_2fa():
    """2FA deaktivieren"""
    if current_user.totp_required:
        flash("2FA ist für Ihren Account verpflichtend und kann nicht deaktiviert werden.", "danger")
        return redirect(url_for("users.settings"))

    password = request.form.get("password")

    if not current_user.check_password(password):
        flash("Falsches Passwort.", "danger")
        return redirect(url_for("users.settings"))

    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.backup_codes = None
    db.session.commit()

    flash("2FA wurde deaktiviert.", "warning")
    return redirect(url_for("users.settings"))


@auth_bp.route("/settings/2fa-regenerate-codes", methods=["POST"])
@login_required
def regenerate_backup_codes():
    """Backup-Codes neu generieren"""
    if not current_user.totp_enabled:
        flash("2FA ist nicht aktiviert.", "danger")
        return redirect(url_for("users.settings"))

    password = request.form.get("password")
    if not current_user.check_password(password):
        flash("Falsches Passwort.", "danger")
        return redirect(url_for("users.settings"))

    backup_codes = current_user.generate_backup_codes()
    db.session.commit()

    flash("Neue Backup-Codes wurden generiert. Die alten Codes sind ungültig.", "warning")
    return render_template("auth/2fa_backup_codes.html", backup_codes=backup_codes)
