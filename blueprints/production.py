"""Honig-Rueckverfolgbarkeit: Eimer (Rohmaterial-Behaelter), Chargen, Abfuellsitzungen.

Siehe AGENTS.md Abschnitt "Honig-Rueckverfolgbarkeit" und Plan
enumerated-honking-otter.md fuer das Datenmodell und die Designentscheidungen.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from auth_utils import role_required
from models import AbfuellCharge, AbfuellErgebnis, AbfuellungQuelle, HonigCharge, HonigEimer, Product, db

production_bp = Blueprint("production", __name__)

MHD_VORSCHLAG_TAGE = 730  # ca. 2 Jahre, siehe Designentscheidung 5


@production_bp.route("/production/eimer")
@role_required("admin", "cashier")
def list_eimer():
    """Liste aller Eimer mit aktuellem Fuellstand/Status."""
    eimer_liste = HonigEimer.query.order_by(HonigEimer.eimer_nummer).all()
    return render_template("production/eimer_list.html", eimer_liste=eimer_liste)


@production_bp.route("/production/eimer/create", methods=["GET", "POST"])
@role_required("admin", "cashier")
def create_eimer():
    """Neuen Eimer anlegen."""
    if request.method == "POST":
        try:
            kapazitaet = request.form.get("kapazitaet_kg")
            eimer = HonigEimer(
                eimer_nummer=request.form["eimer_nummer"],
                kapazitaet_kg=Decimal(kapazitaet) if kapazitaet else None,
            )
            db.session.add(eimer)
            db.session.commit()
            flash(f'Eimer "{eimer.eimer_nummer}" erfolgreich angelegt!', "success")
            return redirect(url_for("production.list_eimer"))
        except IntegrityError as exc:
            db.session.rollback()
            current_app.logger.error("Fehler beim Anlegen des Eimers: %s", exc)
            flash("Eimernummer existiert bereits.", "error")
        except (InvalidOperation, KeyError) as exc:
            db.session.rollback()
            current_app.logger.error("Fehler beim Anlegen des Eimers: %s", exc)
            flash("Ungültige Eingabe.", "error")

    return render_template("production/eimer_create.html")


@production_bp.route("/production/eimer/<int:eimer_id>")
@role_required("admin", "cashier")
def view_eimer(eimer_id):
    """Eimer-Detailansicht mit Historie aller Befuellungen."""
    eimer = HonigEimer.query.get_or_404(eimer_id)
    return render_template("production/eimer_detail.html", eimer=eimer)


@production_bp.route("/production/eimer/<int:eimer_id>/befuellen", methods=["GET", "POST"])
@role_required("admin", "cashier")
def befuellen_eimer(eimer_id):
    """Neue HonigCharge fuer diesen Eimer anlegen (Sorte, Schleudertag, Gewicht)."""
    eimer = HonigEimer.query.get_or_404(eimer_id)

    if request.method == "POST":
        if eimer.aktuelle_charge is not None:
            flash("Dieser Eimer hat bereits eine offene Füllung.", "error")
            return redirect(url_for("production.view_eimer", eimer_id=eimer.id))

        try:
            gewicht = Decimal(request.form["gewicht_kg"])
            if gewicht <= 0:
                flash("Das Gewicht muss größer als 0 sein.", "error")
                return redirect(url_for("production.befuellen_eimer", eimer_id=eimer.id))

            wassergehalt_str = request.form.get("wassergehalt_prozent", "").strip()
            wassergehalt = Decimal(wassergehalt_str) if wassergehalt_str else None
            if wassergehalt is not None and not 0 < wassergehalt < 100:
                flash("Der Wassergehalt muss zwischen 0 und 100 % liegen.", "error")
                return redirect(url_for("production.befuellen_eimer", eimer_id=eimer.id))

            charge = HonigCharge(
                eimer_id=eimer.id,
                sorte=request.form["sorte"],
                schleudertag=datetime.strptime(request.form["schleudertag"], "%Y-%m-%d").date(),
                gewicht_kg=gewicht,
                restmenge_kg=gewicht,
                wassergehalt_prozent=wassergehalt,
            )
            db.session.add(charge)
            db.session.commit()
            flash(f'Eimer "{eimer.eimer_nummer}" erfolgreich befüllt ({gewicht}kg {charge.sorte}).', "success")
            return redirect(url_for("production.view_eimer", eimer_id=eimer.id))
        except (InvalidOperation, KeyError, ValueError) as exc:
            db.session.rollback()
            current_app.logger.error("Fehler beim Befüllen von Eimer %s: %s", eimer.id, exc)
            flash("Ungültige Eingabe.", "error")

    sorten = [s[0] for s in db.session.query(HonigCharge.sorte).distinct().all()]
    return render_template("production/eimer_befuellen.html", eimer=eimer, sorten=sorten, today=date.today().isoformat())


@production_bp.route("/production/abfuellungen")
@role_required("admin", "cashier")
def list_abfuellungen():
    """Liste aller Abfuellsitzungen (Chargenuebersicht)."""
    abfuellungen = AbfuellCharge.query.order_by(AbfuellCharge.abfuelldatum.desc()).all()
    return render_template("production/abfuellung_list.html", abfuellungen=abfuellungen)


@production_bp.route("/production/abfuellungen/create", methods=["GET", "POST"])
@role_required("admin", "cashier")
def create_abfuellung():
    """Neue Abfuellsitzung: Quellen (Eimer/Chargen) + Ergebnisse (Produkte/Glasanzahl)."""
    if request.method == "POST":
        chargennummer = request.form.get("chargennummer", "").strip()
        quellen_ids = request.form.getlist("honig_charge_id[]")
        mengen = request.form.getlist("entnommene_menge_kg[]")
        produkt_ids = request.form.getlist("product_id[]")
        glas_anzahlen = request.form.getlist("anzahl_glaeser[]")

        redirect_target = redirect(url_for("production.create_abfuellung"))

        if not chargennummer:
            flash("Chargennummer (MHD) ist erforderlich.", "error")
            return redirect_target
        if not quellen_ids:
            flash("Mindestens ein Eimer/eine Charge als Quelle wählen.", "error")
            return redirect_target
        if not produkt_ids:
            flash("Mindestens ein erzeugtes Produkt angeben.", "error")
            return redirect_target

        try:
            mengen_decimal = [Decimal(m) for m in mengen]
            glas_anzahlen_int = [int(a) for a in glas_anzahlen]
        except InvalidOperation:
            flash("Mengen müssen gültige Zahlen sein.", "error")
            return redirect_target
        except ValueError:
            flash("Glasanzahlen müssen ganze Zahlen sein.", "error")
            return redirect_target

        if any(m <= 0 for m in mengen_decimal):
            flash("Entnommene Mengen müssen größer als 0 sein.", "error")
            return redirect_target
        if any(a <= 0 for a in glas_anzahlen_int):
            flash("Glasanzahlen müssen größer als 0 sein.", "error")
            return redirect_target

        if AbfuellCharge.query.filter_by(chargennummer=chargennummer).first():
            flash(f"Chargennummer {chargennummer} existiert bereits -- bitte ein abweichendes MHD wählen.", "error")
            return redirect_target

        try:
            mindesthaltbarkeitsdatum = datetime.strptime(chargennummer, "%Y-%m-%d").date()
        except ValueError:
            flash("Chargennummer muss im Format JJJJ-MM-TT vorliegen.", "error")
            return redirect_target

        # Sortenmischungs-Warnung wird im Formular VOR dem Submit per JS geprüft,
        # serverseitig nicht wiederholt (nicht blockierend, siehe Designentscheidung 4).

        try:
            abfuellung = AbfuellCharge(
                chargennummer=chargennummer,
                mindesthaltbarkeitsdatum=mindesthaltbarkeitsdatum,
                sorte=request.form["sorte"],
                abfuelldatum=date.today(),
            )
            db.session.add(abfuellung)
            db.session.flush()  # abfuellung.id benoetigt fuer Quellen/Ergebnisse

            for charge_id, menge in zip(quellen_ids, mengen_decimal):
                honig_charge = HonigCharge.query.get_or_404(charge_id)
                if menge > honig_charge.restmenge_kg:
                    raise ValueError(f"Eimer {honig_charge.eimer.eimer_nummer}: nicht genug Restmenge.")
                honig_charge.restmenge_kg -= menge
                db.session.add(
                    AbfuellungQuelle(
                        abfuell_charge_id=abfuellung.id,
                        honig_charge_id=honig_charge.id,
                        entnommene_menge_kg=menge,
                    )
                )

            for product_id, anzahl in zip(produkt_ids, glas_anzahlen_int):
                product = Product.query.get_or_404(product_id)
                db.session.add(
                    AbfuellErgebnis(
                        abfuell_charge_id=abfuellung.id,
                        product_id=product.id,
                        anzahl_glaeser=anzahl,
                        anzahl_glaeser_aktuell=anzahl,
                    )
                )
                product.number += anzahl

            db.session.commit()
            flash(f"Abfüllung mit Chargennummer {chargennummer} erfolgreich angelegt.", "success")
            return redirect(url_for("production.view_abfuellung", charge_id=abfuellung.id))
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            current_app.logger.error("Fehler beim Anlegen der Abfüllung: %s", exc)
            flash(str(exc) or "Abfüllung konnte nicht gespeichert werden.", "error")
            return redirect_target

    offene_chargen = HonigCharge.query.filter(HonigCharge.restmenge_kg > 0).order_by(HonigCharge.schleudertag).all()
    produkte = Product.query.filter_by(active=True).order_by(Product.name).all()
    mhd_vorschlag = (date.today() + timedelta(days=MHD_VORSCHLAG_TAGE)).isoformat()
    return render_template(
        "production/abfuellung_create.html",
        offene_chargen=offene_chargen,
        produkte=produkte,
        mhd_vorschlag=mhd_vorschlag,
    )


@production_bp.route("/production/abfuellungen/<int:charge_id>")
@role_required("admin", "cashier")
def view_abfuellung(charge_id):
    """Abfuellungs-Detailansicht: Quellen + erzeugte Produkt-Ergebnisse."""
    abfuellung = AbfuellCharge.query.get_or_404(charge_id)
    return render_template("production/abfuellung_detail.html", abfuellung=abfuellung)


@production_bp.route("/production/abfuellungen/<int:charge_id>/delete", methods=["POST"])
@role_required("admin", "cashier")
def delete_abfuellung(charge_id):
    """Abfuellsitzung stornieren: bucht Produktbestand und Restmenge zurueck."""
    abfuellung = AbfuellCharge.query.get_or_404(charge_id)

    try:
        for ergebnis in abfuellung.ergebnisse:
            ergebnis.product.number -= ergebnis.anzahl_glaeser
        for quelle in abfuellung.quellen:
            quelle.honig_charge.restmenge_kg += quelle.entnommene_menge_kg
        db.session.delete(abfuellung)
        db.session.commit()
        flash(f"Abfüllung {abfuellung.chargennummer} storniert, Bestand zurückgebucht.", "success")
    except Exception as exc:  # noqa: BLE001 -- bewusste Team-Entscheidung, siehe AGENTS.md
        db.session.rollback()
        current_app.logger.error("Fehler beim Stornieren der Abfüllung %s: %s", charge_id, exc)
        flash("Abfüllung konnte nicht storniert werden.", "error")

    return redirect(url_for("production.list_abfuellungen"))
