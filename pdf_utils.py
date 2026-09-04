"""Gemeinsame ReportLab-Hilfsfunktionen fuer die PDF-Erzeugung."""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm


def add_fold_and_punch_marks(canvas, doc):
    """
    Fügt Faltmarken und Lochmarke nach DIN 5008 hinzu.
    - Obere Faltmarke bei 105mm von oben
    - Untere Faltmarke bei 210mm von oben
    - Lochmarke bei 148.5mm von oben (Mitte)
    """
    canvas.saveState()
    canvas.setStrokeColorRGB(0.5, 0.5, 0.5)
    canvas.setLineWidth(0.5)

    # Obere Faltmarke (105mm von oben)
    canvas.line(0, A4[1] - 105 * mm, 5 * mm, A4[1] - 105 * mm)

    # Lochmarke (148.5mm von oben - Mitte der Seite)
    canvas.line(0, A4[1] - 148.5 * mm, 5 * mm, A4[1] - 148.5 * mm)

    # Untere Faltmarke (210mm von oben)
    canvas.line(0, A4[1] - 210 * mm, 5 * mm, A4[1] - 210 * mm)

    canvas.restoreState()
