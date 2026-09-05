"""Tests fuer die Honig-Rueckverfolgbarkeit (Eimer -> Charge -> Abfuellung).

Deckt models.py (HonigEimer/HonigCharge/AbfuellCharge/AbfuellungQuelle/
AbfuellErgebnis) und blueprints/production.py ab, siehe Plan
enumerated-honking-otter.md.
"""

from datetime import date, timedelta
from decimal import Decimal

from conftest import login, make_product
from models import AbfuellCharge, AbfuellErgebnis, AbfuellungQuelle, HonigCharge, HonigEimer, Product, db


def make_eimer(eimer_nummer="E-001", kapazitaet_kg=Decimal("25.000")):
    return HonigEimer(eimer_nummer=eimer_nummer, kapazitaet_kg=kapazitaet_kg)


def make_honig_charge(eimer, sorte="Blütenhonig", schleudertag=None, gewicht_kg=Decimal("20.000")):
    return HonigCharge(
        eimer_id=eimer.id,
        sorte=sorte,
        schleudertag=schleudertag or date.today(),
        gewicht_kg=gewicht_kg,
        restmenge_kg=gewicht_kg,
    )


# ---------------------------------------------------------------------------
# Modell-Ebene: HonigCharge.status (abgeleitete Property)
# ---------------------------------------------------------------------------


def test_honig_charge_status_voll_direkt_nach_befuellung(db_session):
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer, gewicht_kg=Decimal("20.000"))
    db_session.add(charge)
    db_session.commit()

    assert charge.status == "voll"


def test_honig_charge_status_teilweise_abgefuellt_nach_teilentnahme(db_session):
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer, gewicht_kg=Decimal("20.000"))
    db_session.add(charge)
    db_session.commit()

    charge.restmenge_kg -= Decimal("5.000")
    db_session.commit()

    assert charge.status == "teilweise_abgefuellt"


def test_honig_charge_status_leer_bei_restmenge_null(db_session):
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer, gewicht_kg=Decimal("20.000"))
    db_session.add(charge)
    db_session.commit()

    charge.restmenge_kg = Decimal("0.000")
    db_session.commit()

    assert charge.status == "leer"


# ---------------------------------------------------------------------------
# Modell-Ebene: HonigEimer.aktuelle_charge
# ---------------------------------------------------------------------------


def test_aktuelle_charge_none_bei_frischem_eimer(db_session):
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    assert eimer.aktuelle_charge is None


def test_aktuelle_charge_liefert_offene_charge_nach_befuellung(db_session):
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer)
    db_session.add(charge)
    db_session.commit()

    assert eimer.aktuelle_charge is not None
    assert eimer.aktuelle_charge.id == charge.id


def test_aktuelle_charge_none_nach_vollstaendiger_entnahme(db_session):
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer, gewicht_kg=Decimal("20.000"))
    db_session.add(charge)
    db_session.commit()

    charge.restmenge_kg = Decimal("0.000")
    db_session.commit()

    assert eimer.aktuelle_charge is None


def test_hoechstens_eine_offene_honig_charge_pro_eimer_auf_query_ebene(db_session):
    """Nicht nur ueber aktuelle_charge pruefen (next() wuerde eine zweite
    offene Charge stillschweigend verdecken statt laut zu scheitern)."""
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer)
    db_session.add(charge)
    db_session.commit()

    offene = HonigCharge.query.filter(HonigCharge.eimer_id == eimer.id, HonigCharge.restmenge_kg > 0).all()
    assert len(offene) == 1


# ---------------------------------------------------------------------------
# Routen: Eimer anlegen/befuellen
# ---------------------------------------------------------------------------


def test_eimer_create_route(client, admin_user):
    login(client, "admin")
    response = client.post(
        "/production/eimer/create",
        data={"eimer_nummer": "E-042", "kapazitaet_kg": "25.0"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    eimer = HonigEimer.query.filter_by(eimer_nummer="E-042").first()
    assert eimer is not None


def test_eimer_befuellen_route(client, admin_user, db_session):
    login(client, "admin")
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    response = client.post(
        f"/production/eimer/{eimer.id}/befuellen",
        data={"sorte": "Waldhonig", "schleudertag": date.today().isoformat(), "gewicht_kg": "22.500"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    charge = HonigCharge.query.filter_by(eimer_id=eimer.id).first()
    assert charge is not None
    assert charge.sorte == "Waldhonig"
    assert charge.gewicht_kg == Decimal("22.500")
    assert charge.restmenge_kg == Decimal("22.500")
    assert charge.status == "voll"


def test_eimer_befuellen_route_abgelehnt_wenn_bereits_offene_charge(client, admin_user, db_session):
    login(client, "admin")
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    erste_charge = make_honig_charge(eimer)
    db_session.add(erste_charge)
    db_session.commit()

    response = client.post(
        f"/production/eimer/{eimer.id}/befuellen",
        data={"sorte": "Waldhonig", "schleudertag": date.today().isoformat(), "gewicht_kg": "10.000"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    chargen = HonigCharge.query.filter_by(eimer_id=eimer.id).all()
    assert len(chargen) == 1  # kein zweiter offener Datensatz entstanden


# ---------------------------------------------------------------------------
# Routen: Abfuellung anlegen -- ein Eimer, ein Ergebnis
# ---------------------------------------------------------------------------


def test_abfuellung_create_ein_eimer_ein_produkt(client, admin_user, db_session):
    login(client, "admin")
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer, gewicht_kg=Decimal("20.000"))
    db_session.add(charge)
    db_session.commit()

    produkt = make_product(name="500g Blütenhonig", number=0)
    db_session.add(produkt)
    db_session.commit()

    chargennummer = (date.today() + timedelta(days=730)).isoformat()

    response = client.post(
        "/production/abfuellungen/create",
        data={
            "chargennummer": chargennummer,
            "sorte": "Blütenhonig",
            "honig_charge_id[]": [str(charge.id)],
            "entnommene_menge_kg[]": ["18.000"],
            "product_id[]": [str(produkt.id)],
            "anzahl_glaeser[]": ["30"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    abfuellung = AbfuellCharge.query.filter_by(chargennummer=chargennummer).first()
    assert abfuellung is not None
    assert abfuellung.sorte == "Blütenhonig"

    db.session.refresh(charge)
    assert charge.restmenge_kg == Decimal("2.000")
    assert charge.status == "teilweise_abgefuellt"

    quelle = AbfuellungQuelle.query.filter_by(abfuell_charge_id=abfuellung.id).first()
    assert quelle is not None
    assert quelle.entnommene_menge_kg == Decimal("18.000")

    ergebnis = AbfuellErgebnis.query.filter_by(abfuell_charge_id=abfuellung.id).first()
    assert ergebnis is not None
    assert ergebnis.anzahl_glaeser == 30

    db.session.refresh(produkt)
    assert produkt.number == 30


def test_abfuellung_vollstaendige_entnahme_setzt_charge_leer(client, admin_user, db_session):
    login(client, "admin")
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer, gewicht_kg=Decimal("20.000"))
    db_session.add(charge)
    db_session.commit()

    produkt = make_product(name="500g Blütenhonig", number=0)
    db_session.add(produkt)
    db_session.commit()

    chargennummer = (date.today() + timedelta(days=730)).isoformat()

    client.post(
        "/production/abfuellungen/create",
        data={
            "chargennummer": chargennummer,
            "sorte": "Blütenhonig",
            "honig_charge_id[]": [str(charge.id)],
            "entnommene_menge_kg[]": ["20.000"],
            "product_id[]": [str(produkt.id)],
            "anzahl_glaeser[]": ["40"],
        },
        follow_redirects=True,
    )

    db.session.refresh(charge)
    assert charge.restmenge_kg == Decimal("0.000")
    assert charge.status == "leer"


# ---------------------------------------------------------------------------
# Routen: Abfuellung mit mehreren Quellen (m:n)
# ---------------------------------------------------------------------------


def test_abfuellung_aus_mehreren_eimern(client, admin_user, db_session):
    login(client, "admin")
    eimer1 = make_eimer(eimer_nummer="E-010")
    eimer2 = make_eimer(eimer_nummer="E-011")
    db_session.add_all([eimer1, eimer2])
    db_session.commit()

    charge1 = make_honig_charge(eimer1, gewicht_kg=Decimal("15.000"))
    charge2 = make_honig_charge(eimer2, gewicht_kg=Decimal("10.000"))
    db_session.add_all([charge1, charge2])
    db_session.commit()

    produkt = make_product(name="500g Blütenhonig", number=0)
    db_session.add(produkt)
    db_session.commit()

    chargennummer = (date.today() + timedelta(days=730)).isoformat()

    client.post(
        "/production/abfuellungen/create",
        data={
            "chargennummer": chargennummer,
            "sorte": "Blütenhonig",
            "honig_charge_id[]": [str(charge1.id), str(charge2.id)],
            "entnommene_menge_kg[]": ["15.000", "8.000"],
            "product_id[]": [str(produkt.id)],
            "anzahl_glaeser[]": ["46"],
        },
        follow_redirects=True,
    )

    abfuellung = AbfuellCharge.query.filter_by(chargennummer=chargennummer).first()
    assert abfuellung is not None

    quellen = AbfuellungQuelle.query.filter_by(abfuell_charge_id=abfuellung.id).all()
    assert len(quellen) == 2
    mengen = {q.honig_charge_id: q.entnommene_menge_kg for q in quellen}
    assert mengen[charge1.id] == Decimal("15.000")
    assert mengen[charge2.id] == Decimal("8.000")

    db.session.refresh(charge1)
    db.session.refresh(charge2)
    assert charge1.status == "leer"
    assert charge2.status == "teilweise_abgefuellt"


# ---------------------------------------------------------------------------
# Routen: Abfuellsitzung mit mehreren Ergebnis-Zeilen (Kernszenario)
# ---------------------------------------------------------------------------


def test_abfuellung_mit_zwei_produkten_teilt_sich_chargennummer(client, admin_user, db_session):
    login(client, "admin")
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer, gewicht_kg=Decimal("30.000"))
    db_session.add(charge)
    db_session.commit()

    produkt_500 = make_product(name="500g Blütenhonig", number=0)
    produkt_250 = make_product(name="250g Blütenhonig", number=0)
    db_session.add_all([produkt_500, produkt_250])
    db_session.commit()

    chargennummer = (date.today() + timedelta(days=730)).isoformat()

    client.post(
        "/production/abfuellungen/create",
        data={
            "chargennummer": chargennummer,
            "sorte": "Blütenhonig",
            "honig_charge_id[]": [str(charge.id)],
            "entnommene_menge_kg[]": ["25.000"],
            "product_id[]": [str(produkt_500.id), str(produkt_250.id)],
            "anzahl_glaeser[]": ["30", "20"],
        },
        follow_redirects=True,
    )

    abfuellung = AbfuellCharge.query.filter_by(chargennummer=chargennummer).first()
    assert abfuellung is not None

    ergebnisse = AbfuellErgebnis.query.filter_by(abfuell_charge_id=abfuellung.id).all()
    assert len(ergebnisse) == 2
    anzahlen = {e.product_id: e.anzahl_glaeser for e in ergebnisse}
    assert anzahlen[produkt_500.id] == 30
    assert anzahlen[produkt_250.id] == 20

    db.session.refresh(produkt_500)
    db.session.refresh(produkt_250)
    assert produkt_500.number == 30
    assert produkt_250.number == 20


# ---------------------------------------------------------------------------
# Edge Cases / Validierung
# ---------------------------------------------------------------------------


def test_abfuellung_entnahme_groesser_als_restmenge_wird_abgelehnt(client, admin_user, db_session):
    login(client, "admin")
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer, gewicht_kg=Decimal("10.000"))
    db_session.add(charge)
    db_session.commit()

    produkt = make_product(name="500g Blütenhonig", number=0)
    db_session.add(produkt)
    db_session.commit()

    chargennummer = (date.today() + timedelta(days=730)).isoformat()

    response = client.post(
        "/production/abfuellungen/create",
        data={
            "chargennummer": chargennummer,
            "sorte": "Blütenhonig",
            "honig_charge_id[]": [str(charge.id)],
            "entnommene_menge_kg[]": ["999.000"],
            "product_id[]": [str(produkt.id)],
            "anzahl_glaeser[]": ["30"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # kein Teil-Commit: weder Charge noch Produktbestand duerfen veraendert sein
    assert AbfuellCharge.query.filter_by(chargennummer=chargennummer).first() is None
    db.session.refresh(charge)
    assert charge.restmenge_kg == Decimal("10.000")
    db.session.refresh(produkt)
    assert produkt.number == 0


def test_abfuellung_doppelte_chargennummer_wird_mit_flash_abgelehnt(client, admin_user, db_session):
    login(client, "admin")
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge1 = make_honig_charge(eimer, gewicht_kg=Decimal("30.000"))
    db_session.add(charge1)
    db_session.commit()

    produkt = make_product(name="500g Blütenhonig", number=0)
    db_session.add(produkt)
    db_session.commit()

    chargennummer = (date.today() + timedelta(days=730)).isoformat()

    payload = {
        "chargennummer": chargennummer,
        "sorte": "Blütenhonig",
        "honig_charge_id[]": [str(charge1.id)],
        "entnommene_menge_kg[]": ["10.000"],
        "product_id[]": [str(produkt.id)],
        "anzahl_glaeser[]": ["20"],
    }
    client.post("/production/abfuellungen/create", data=payload, follow_redirects=True)

    # zweite Sitzung, andere Quelle, gleiche Chargennummer
    eimer2 = make_eimer(eimer_nummer="E-999")
    db_session.add(eimer2)
    db_session.commit()
    charge2 = make_honig_charge(eimer2, gewicht_kg=Decimal("10.000"))
    db_session.add(charge2)
    db_session.commit()

    payload2 = dict(payload)
    payload2["honig_charge_id[]"] = [str(charge2.id)]

    response = client.post("/production/abfuellungen/create", data=payload2, follow_redirects=True)
    assert response.status_code == 200
    assert "existiert bereits" in response.get_data(as_text=True)

    # nur eine Abfuellung mit dieser Chargennummer
    assert AbfuellCharge.query.filter_by(chargennummer=chargennummer).count() == 1


def test_abfuellung_ohne_glasanzahl_oder_menge_wird_abgelehnt(client, admin_user, db_session):
    login(client, "admin")
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer, gewicht_kg=Decimal("10.000"))
    db_session.add(charge)
    db_session.commit()

    produkt = make_product(name="500g Blütenhonig", number=0)
    db_session.add(produkt)
    db_session.commit()

    chargennummer = (date.today() + timedelta(days=730)).isoformat()

    response = client.post(
        "/production/abfuellungen/create",
        data={
            "chargennummer": chargennummer,
            "sorte": "Blütenhonig",
            "honig_charge_id[]": [str(charge.id)],
            "entnommene_menge_kg[]": ["0.000"],
            "product_id[]": [str(produkt.id)],
            "anzahl_glaeser[]": ["30"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert AbfuellCharge.query.filter_by(chargennummer=chargennummer).first() is None


def test_abfuellung_ohne_quellen_wird_abgelehnt(client, admin_user, db_session):
    login(client, "admin")
    produkt = make_product(name="500g Blütenhonig", number=0)
    db_session.add(produkt)
    db_session.commit()

    chargennummer = (date.today() + timedelta(days=730)).isoformat()

    response = client.post(
        "/production/abfuellungen/create",
        data={
            "chargennummer": chargennummer,
            "sorte": "Blütenhonig",
            "honig_charge_id[]": [],
            "entnommene_menge_kg[]": [],
            "product_id[]": [str(produkt.id)],
            "anzahl_glaeser[]": ["30"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert AbfuellCharge.query.filter_by(chargennummer=chargennummer).first() is None


def test_abfuellung_ohne_ergebnisse_wird_abgelehnt(client, admin_user, db_session):
    login(client, "admin")
    eimer = make_eimer()
    db_session.add(eimer)
    db_session.commit()

    charge = make_honig_charge(eimer, gewicht_kg=Decimal("10.000"))
    db_session.add(charge)
    db_session.commit()

    chargennummer = (date.today() + timedelta(days=730)).isoformat()

    response = client.post(
        "/production/abfuellungen/create",
        data={
            "chargennummer": chargennummer,
            "sorte": "Blütenhonig",
            "honig_charge_id[]": [str(charge.id)],
            "entnommene_menge_kg[]": ["5.000"],
            "product_id[]": [],
            "anzahl_glaeser[]": [],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert AbfuellCharge.query.filter_by(chargennummer=chargennummer).first() is None

    # Eimer wurde nicht angetastet
    db.session.refresh(charge)
    assert charge.restmenge_kg == Decimal("10.000")


def test_sortenmischung_wird_nicht_blockiert(client, admin_user, db_session):
    """Sortenmischung erzeugt (optional) eine Warnung, wird aber nicht verhindert."""
    login(client, "admin")
    eimer1 = make_eimer(eimer_nummer="E-020")
    eimer2 = make_eimer(eimer_nummer="E-021")
    db_session.add_all([eimer1, eimer2])
    db_session.commit()

    charge1 = make_honig_charge(eimer1, sorte="Waldhonig", gewicht_kg=Decimal("10.000"))
    charge2 = make_honig_charge(eimer2, sorte="Blütenhonig", gewicht_kg=Decimal("10.000"))
    db_session.add_all([charge1, charge2])
    db_session.commit()

    produkt = make_product(name="500g Mischhonig", number=0)
    db_session.add(produkt)
    db_session.commit()

    chargennummer = (date.today() + timedelta(days=730)).isoformat()

    response = client.post(
        "/production/abfuellungen/create",
        data={
            "chargennummer": chargennummer,
            "sorte": "Mischung",
            "honig_charge_id[]": [str(charge1.id), str(charge2.id)],
            "entnommene_menge_kg[]": ["10.000", "10.000"],
            "product_id[]": [str(produkt.id)],
            "anzahl_glaeser[]": ["40"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert AbfuellCharge.query.filter_by(chargennummer=chargennummer).first() is not None


# ---------------------------------------------------------------------------
# Loeschen-Route
# ---------------------------------------------------------------------------


def test_abfuellung_delete_bucht_produkt_und_restmenge_zurueck(client, admin_user, db_session):
    login(client, "admin")
    eimer1 = make_eimer(eimer_nummer="E-030")
    eimer2 = make_eimer(eimer_nummer="E-031")
    db_session.add_all([eimer1, eimer2])
    db_session.commit()

    charge1 = make_honig_charge(eimer1, gewicht_kg=Decimal("20.000"))
    charge2 = make_honig_charge(eimer2, gewicht_kg=Decimal("15.000"))
    db_session.add_all([charge1, charge2])
    db_session.commit()

    produkt_500 = make_product(name="500g Blütenhonig", number=5)
    produkt_250 = make_product(name="250g Blütenhonig", number=3)
    db_session.add_all([produkt_500, produkt_250])
    db_session.commit()

    chargennummer = (date.today() + timedelta(days=730)).isoformat()

    client.post(
        "/production/abfuellungen/create",
        data={
            "chargennummer": chargennummer,
            "sorte": "Blütenhonig",
            "honig_charge_id[]": [str(charge1.id), str(charge2.id)],
            "entnommene_menge_kg[]": ["18.000", "10.000"],
            "product_id[]": [str(produkt_500.id), str(produkt_250.id)],
            "anzahl_glaeser[]": ["30", "20"],
        },
        follow_redirects=True,
    )

    abfuellung = AbfuellCharge.query.filter_by(chargennummer=chargennummer).first()
    assert abfuellung is not None

    response = client.post(f"/production/abfuellungen/{abfuellung.id}/delete", follow_redirects=True)
    assert response.status_code == 200

    assert AbfuellCharge.query.get(abfuellung.id) is None
    assert AbfuellungQuelle.query.filter_by(abfuell_charge_id=abfuellung.id).count() == 0
    assert AbfuellErgebnis.query.filter_by(abfuell_charge_id=abfuellung.id).count() == 0

    db.session.refresh(charge1)
    db.session.refresh(charge2)
    assert charge1.restmenge_kg == Decimal("20.000")
    assert charge2.restmenge_kg == Decimal("15.000")

    db.session.refresh(produkt_500)
    db.session.refresh(produkt_250)
    assert produkt_500.number == 5  # zurueckgebucht auf Ausgangswert
    assert produkt_250.number == 3
