# Passwort-Reset Funktionalität
import datetime
import secrets

from flask import url_for
from flask_mail import Message

from models import User, db


class PasswordResetToken:
    """Verwaltung von Passwort-Reset-Tokens"""

    @staticmethod
    def generate_token():
        """Generiert einen sicheren Reset-Token"""
        return secrets.token_urlsafe(32)

    @staticmethod
    def create_reset_token(user):
        """
        Erstellt einen Reset-Token für einen User

        Args:
            user: User object

        Returns:
            Token string
        """
        token = PasswordResetToken.generate_token()

        # Token in User speichern
        user.reset_token = token
        user.reset_token_expires = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        db.session.commit()

        return token

    @staticmethod
    def verify_token(token):
        """
        Verifiziert einen Reset-Token

        Args:
            token: Token string

        Returns:
            User object oder None
        """
        user = User.query.filter_by(reset_token=token).first()

        if not user:
            return None

        # Token abgelaufen?
        if user.reset_token_expires < datetime.datetime.utcnow():
            return None

        return user

    @staticmethod
    def invalidate_token(user):
        """Macht einen Token ungültig"""
        user.reset_token = None
        user.reset_token_expires = None
        db.session.commit()


def send_password_reset_email(user, token, mail):
    """
    Sendet Passwort-Reset-E-Mail

    Args:
        user: User object
        token: Reset token
        mail: Flask-Mail instance
    """
    reset_url = url_for("reset_password", token=token, _external=True)

    msg = Message(
        subject="Passwort zurücksetzen - Rechnungsverwaltung", sender=mail.default_sender, recipients=[user.email]
    )

    msg.body = f"""Hallo {user.username},

Sie haben eine Anfrage zum Zurücksetzen Ihres Passworts gestellt.

Klicken Sie auf den folgenden Link, um Ihr Passwort zurückzusetzen:

{reset_url}

Dieser Link ist 1 Stunde gültig.

Falls Sie diese Anfrage nicht gestellt haben, ignorieren Sie diese E-Mail.

Mit freundlichen Grüßen
Ihr Rechnungsverwaltungs-Team
"""

    msg.html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #333;">Passwort zurücksetzen</h2>

        <p>Hallo <strong>{user.username}</strong>,</p>

        <p>Sie haben eine Anfrage zum Zurücksetzen Ihres Passworts gestellt.</p>

        <p>Klicken Sie auf den folgenden Button, um Ihr Passwort zurückzusetzen:</p>

        <p style="text-align: center; margin: 30px 0;">
            <a href="{reset_url}"
               style="background: #007bff; color: white; padding: 12px 30px;
                      text-decoration: none; border-radius: 5px; display: inline-block;">
                Passwort zurücksetzen
            </a>
        </p>

        <p style="color: #666; font-size: 0.9em;">
            Oder kopieren Sie diesen Link in Ihren Browser:<br>
            <a href="{reset_url}">{reset_url}</a>
        </p>

        <p style="color: #999; font-size: 0.85em; margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee;">
            <strong>Wichtig:</strong> Dieser Link ist nur 1 Stunde gültig.<br>
            Falls Sie diese Anfrage nicht gestellt haben, ignorieren Sie diese E-Mail.
        </p>
    </body>
    </html>
    """

    mail.send(msg)
