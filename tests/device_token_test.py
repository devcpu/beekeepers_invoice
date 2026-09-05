"""Tests fuer Geraete-Tokens (mehrere widerrufbare Dauer-Tokens pro User,
Kopplung per QR-Code/Text, Austausch gegen ein kurzlebiges JWT ueber
/api/auth/device). Siehe Plan enumerated-honking-otter.md."""

from conftest import login
from models import DeviceToken, db


def make_device_token(user, label="Handy Janusz", token="tok-" + "a" * 40):
    return DeviceToken(user_id=user.id, label=label, token=token)


# ---------------------------------------------------------------------------
# Modell-Ebene
# ---------------------------------------------------------------------------


def test_device_token_gehoert_zum_user(db_session, admin_user):
    dt = make_device_token(admin_user)
    db_session.add(dt)
    db_session.commit()

    assert dt in admin_user.device_tokens
    assert dt.user_id == admin_user.id


# ---------------------------------------------------------------------------
# Routen: Liste/Erzeugen/Widerrufen unter /settings/device-tokens
# ---------------------------------------------------------------------------


def test_device_tokens_liste_zeigt_nur_eigene_tokens(client, db_session, admin_user, cashier_user):
    dt_admin = make_device_token(admin_user, label="Admin-Handy", token="tok-admin-" + "a" * 30)
    dt_cashier = make_device_token(cashier_user, label="Kassen-Tablet", token="tok-cashier-" + "b" * 30)
    db_session.add_all([dt_admin, dt_cashier])
    db_session.commit()

    login(client, "admin")
    response = client.get("/settings/device-tokens")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Admin-Handy" in html
    assert "Kassen-Tablet" not in html


def test_device_tokens_liste_erreichbar_fuer_jede_rolle(client, cashier_user, reseller_user):
    login(client, "cashier")
    assert client.get("/settings/device-tokens").status_code == 200

    login(client, "reseller")
    assert client.get("/settings/device-tokens").status_code == 200


def test_device_token_create_route(client, admin_user, db_session):
    login(client, "admin")
    response = client.post("/settings/device-tokens/create", data={"label": "Handy Janusz"}, follow_redirects=True)
    assert response.status_code == 200

    tokens = DeviceToken.query.filter_by(user_id=admin_user.id).all()
    assert len(tokens) == 1
    assert tokens[0].label == "Handy Janusz"
    assert tokens[0].token


def test_device_token_create_route_mehrfach_erzeugt_unterschiedliche_tokens(client, admin_user, db_session):
    """Kernszenario: mehrere Geraete pro User, jedes mit eigenem Token."""
    login(client, "admin")
    client.post("/settings/device-tokens/create", data={"label": "Handy Janusz"}, follow_redirects=True)
    client.post("/settings/device-tokens/create", data={"label": "Tablet Marktstand"}, follow_redirects=True)

    tokens = DeviceToken.query.filter_by(user_id=admin_user.id).order_by(DeviceToken.id).all()
    assert len(tokens) == 2
    assert tokens[0].label == "Handy Janusz"
    assert tokens[1].label == "Tablet Marktstand"
    assert tokens[0].token != tokens[1].token


def test_device_token_revoke_eigenes_token(client, admin_user, db_session):
    dt = make_device_token(admin_user)
    db_session.add(dt)
    db_session.commit()
    token_id = dt.id

    login(client, "admin")
    response = client.post(f"/settings/device-tokens/{token_id}/revoke", follow_redirects=True)
    assert response.status_code == 200
    assert DeviceToken.query.get(token_id) is None


def test_device_token_revoke_fremdes_token_wird_abgelehnt(client, admin_user, cashier_user, db_session):
    """IDOR-Schutz: ein Cashier darf nicht das Geraet eines Admins widerrufen."""
    dt_admin = make_device_token(admin_user, label="Admin-Handy", token="tok-admin-" + "c" * 30)
    db_session.add(dt_admin)
    db_session.commit()
    token_id = dt_admin.id

    login(client, "cashier")
    response = client.post(f"/settings/device-tokens/{token_id}/revoke")
    assert response.status_code == 404

    assert DeviceToken.query.get(token_id) is not None


# ---------------------------------------------------------------------------
# /api/auth/device
# ---------------------------------------------------------------------------


def test_api_auth_device_mit_gueltigem_token_liefert_jwt(client, admin_user, db_session):
    dt = make_device_token(admin_user, token="tok-valid-" + "d" * 30)
    db_session.add(dt)
    db_session.commit()

    response = client.post("/api/auth/device", json={"token": dt.token})
    assert response.status_code == 200
    data = response.get_json()
    assert "token" in data
    assert data["user"]["username"] == "admin"

    # das zurueckgegebene JWT funktioniert an einer bestehenden @token_required-Route
    verify_response = client.get("/api/auth/verify", headers={"Authorization": f"Bearer {data['token']}"})
    assert verify_response.status_code == 200
    assert verify_response.get_json()["valid"] is True


def test_api_auth_device_aktualisiert_last_used_nicht_user_last_login(client, admin_user, db_session):
    dt = make_device_token(admin_user, token="tok-lastused-" + "e" * 30)
    db_session.add(dt)
    db_session.commit()
    assert dt.last_used_at is None
    assert admin_user.last_login is None

    client.post("/api/auth/device", json={"token": dt.token})

    db.session.refresh(dt)
    db.session.refresh(admin_user)
    assert dt.last_used_at is not None
    assert admin_user.last_login is None  # Web-Login-Feld bleibt unberuehrt


def test_api_auth_device_unbekannter_token_wird_abgelehnt(client, db_session):
    response = client.post("/api/auth/device", json={"token": "does-not-exist"})
    assert response.status_code == 401
    assert "token" not in response.get_json()


def test_api_auth_device_ohne_token_wird_abgelehnt(client):
    response = client.post("/api/auth/device", json={})
    assert response.status_code == 400


def test_api_auth_device_fuer_inaktiven_user_wird_abgelehnt(client, admin_user, db_session):
    dt = make_device_token(admin_user, token="tok-inactive-" + "f" * 30)
    db_session.add(dt)
    admin_user.is_active = False
    db_session.commit()

    response = client.post("/api/auth/device", json={"token": dt.token})
    assert response.status_code == 401


def test_api_auth_device_nach_widerruf_wird_abgelehnt(client, admin_user, db_session):
    dt = make_device_token(admin_user, token="tok-revoked-" + "g" * 30)
    db_session.add(dt)
    db_session.commit()
    token_value = dt.token

    login(client, "admin")
    client.post(f"/settings/device-tokens/{dt.id}/revoke", follow_redirects=True)

    response = client.post("/api/auth/device", json={"token": token_value})
    assert response.status_code == 401


def test_zwei_tokens_desselben_users_widerruf_isoliert(client, admin_user, db_session):
    dt1 = make_device_token(admin_user, label="Handy", token="tok-iso1-" + "h" * 30)
    dt2 = make_device_token(admin_user, label="Tablet", token="tok-iso2-" + "i" * 30)
    db_session.add_all([dt1, dt2])
    db_session.commit()

    login(client, "admin")
    client.post(f"/settings/device-tokens/{dt1.id}/revoke", follow_redirects=True)

    # dt1 ist tot
    response1 = client.post("/api/auth/device", json={"token": dt1.token})
    assert response1.status_code == 401

    # dt2 bleibt gueltig
    response2 = client.post("/api/auth/device", json={"token": dt2.token})
    assert response2.status_code == 200
