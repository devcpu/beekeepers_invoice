"""
Migration: Add totp_required field to users table

Adds the ability for admins to enforce 2FA for specific users.
"""

from app import create_app, db
from models import User


def upgrade():
    """Add totp_required column"""
    app = create_app()
    with app.app_context():
        # SQLAlchemy DDL
        from sqlalchemy import text

        # Add column (PostgreSQL syntax)
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_required BOOLEAN DEFAULT FALSE"))

        db.session.commit()
        print("✓ Added totp_required column to users table")


def downgrade():
    """Remove totp_required column"""
    app = create_app()
    with app.app_context():
        from sqlalchemy import text

        db.session.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS totp_required"))

        db.session.commit()
        print("✓ Removed totp_required column from users table")


if __name__ == "__main__":
    print("Running migration: Add totp_required field")
    upgrade()
    print("Migration completed successfully!")
