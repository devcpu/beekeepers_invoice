"""Gemeinsame pytest-Fixtures fuer die Testsuite."""

import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from models import Customer, Invoice, LineItem, Product, User, db  # noqa: E402


@pytest.fixture
def app():
    """Flask-App mit In-Memory-SQLite fuer jeden Test frisch aufgesetzt."""
    flask_app = create_app("testing")

    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Flask-Test-Client."""
    return app.test_client()


@pytest.fixture
def db_session(app):
    """Direkter Zugriff auf die DB-Session innerhalb des App-Context."""
    return db.session


def make_user(username="admin", role="admin", password="testpass123"):
    """Erzeugt (aber committet noch nicht) einen User mit gesetztem Passwort."""
    user = User(username=username, email=f"{username}@example.test", role=role, is_active=True)
    user.set_password(password)
    return user


def make_customer(company_name="Testkunde GmbH", email="kunde@example.test"):
    return Customer(
        company_name=company_name,
        first_name="Max",
        last_name="Mustermann",
        email=email,
        address="Teststrasse 1\n12345 Testort",
    )


def make_product(name="Honig 500g", price=Decimal("9.90"), tax_rate=Decimal("7.80"), number=100):
    return Product(name=name, price=price, tax_rate=tax_rate, number=number, quantity="500g", active=True)


def make_invoice(customer, tax_model="standard", tax_rate=Decimal("19.00"), invoice_number="RE-TEST-0001"):
    return Invoice(
        invoice_number=invoice_number,
        customer_id=customer.id,
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=14),
        tax_model=tax_model,
        tax_rate=tax_rate,
        customer_type="endkunde",
    )


def make_line_item(description="Testposition", quantity=Decimal("1.00"), unit_price=Decimal("10.00"), tax_rate=None, product_id=None, position=0):
    item = LineItem(
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        tax_rate=tax_rate,
        product_id=product_id,
        position=position,
    )
    item.calculate_total()
    return item


@pytest.fixture
def admin_user(db_session):
    user = make_user(username="admin", role="admin")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def cashier_user(db_session):
    user = make_user(username="cashier", role="cashier")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def reseller_user(db_session):
    user = make_user(username="reseller", role="reseller")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def customer(db_session):
    c = make_customer()
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def product(db_session):
    p = make_product()
    db_session.add(p)
    db_session.commit()
    return p


def login(client, username, password="testpass123"):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=True)
