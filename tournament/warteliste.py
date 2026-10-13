"""Warteliste und Startgebühr: Wer sich zuerst angemeldet hat, rückt zuerst nach.

`nachruecken` holt ein Team von der Warteliste und schickt dem Kapitän eine Mail.
`auffuellen` füllt freie Plätze automatisch – nur wenn beim Turnier
"Warteliste automatisch nachrücken lassen" angehakt ist und das Turnier nicht vorbei ist.
Aufgerufen nach allem, was einen Platz frei machen kann: Abmeldung des Kapitäns, Absage oder
Löschen im Admin, mehr Plätze beim Turnier, neue Anmeldung.

`an_zahlung_erinnern` und `unbezahlte_auf_warteliste` setzen das Versprechen um, das Teams bei der
Anmeldung lesen: "Bis zum Meldeschluss zahlen – danach rückt die Warteliste nach." Beides löst die
Orga per Knopf aus, nicht automatisch (Barzahler melden sich oft erst spät).
"""

import logging

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Team

logger = logging.getLogger(__name__)


def _mail(team, request, vorlage, betreff):
    """Mail an den Kapitän mit Bearbeitungslink; Fehler beim Versand nur protokollieren."""
    if not team.kapitaen_email:
        return False
    link = request.build_absolute_uri(reverse("team_bearbeiten", args=[team.edit_token]))
    text = render_to_string(vorlage, {"team": team, "turnier": team.turnier, "link": link})
    try:
        send_mail(betreff, text, None, [team.kapitaen_email])
        return True
    except Exception:
        logger.exception("Mail %s für Team %s konnte nicht verschickt werden", vorlage, team.pk)
        return False


def nachruecken(team, request):
    """Team von der Warteliste holen und den Kapitän informieren."""
    team.status = Team.Status.ANGEMELDET
    team.save()  # bezahlte Teams werden dabei direkt bestätigt
    _mail(team, request, "mail/nachgerueckt.txt", f"Ihr seid nachgerückt: {team.turnier.name}")


def auffuellen(turnier, request, ausser=None):
    """Freie Plätze in Anmelde-Reihenfolge von der Warteliste füllen. Gibt die nachgerückten Teams zurück.
    `ausser`: Team(s), die gerade erst auf die Warteliste gesetzt wurden – sie werden nicht sofort wieder geholt."""
    if not turnier.warteliste_automatisch or turnier.vorbei:
        return []
    if ausser is None:
        ausser = []
    elif isinstance(ausser, Team):
        ausser = [ausser]
    wartend = (
        turnier.teams.filter(status=Team.Status.WARTELISTE)
        .exclude(pk__in=[t.pk for t in ausser])
        .order_by(*Team.REIHENFOLGE)
    )
    nachgerueckt = []
    while turnier.freie_plaetze > 0:
        team = wartend.first()
        if team is None:
            break
        nachruecken(team, request)
        nachgerueckt.append(team)
    return nachgerueckt


def an_zahlung_erinnern(turnier, request):
    """Erinnerungsmail an alle Teams mit Startplatz, deren Startgebühr fehlt. Gibt die Anzahl zurück."""
    anzahl = sum(
        _mail(team, request, "mail/zahlungserinnerung.txt", f"Erinnerung Startgebühr: {turnier.name}")
        for team in turnier.unbezahlte_teams()
    )
    turnier.zahlungserinnerung_am = timezone.now()
    turnier.save(update_fields=["zahlungserinnerung_am"])
    return anzahl


def unbezahlte_auf_warteliste(turnier, request):
    """Nach dem Meldeschluss: unbezahlte Teams ans Ende der Warteliste, Mail an sie, dann nachrücken lassen.
    Gibt (auf die Warteliste gesetzte Teams, nachgerückte Teams) zurück."""
    if not turnier.meldeschluss_vorbei:
        return [], []
    verschoben = []
    for team in turnier.unbezahlte_teams():
        vorher = timezone.localtime(team.angemeldet_am)
        team.status = Team.Status.WARTELISTE
        # Ans Ende stellen – sonst stünden sie wegen der frühen Anmeldung ganz vorn
        team.angemeldet_am = timezone.now()
        vermerk = f"Ohne Zahlung nach Meldeschluss auf die Warteliste gesetzt (ursprünglich angemeldet {vorher:%d.%m.%Y %H:%M})."
        team.notiz = f"{team.notiz}\n{vermerk}".strip()
        team.save()
        verschoben.append(team)
    for team in verschoben:  # erst danach: die Wartelisten-Plätze stimmen jetzt
        _mail(team, request, "mail/auf_warteliste.txt", f"Euer Platz bei {turnier.name}")
    return verschoben, auffuellen(turnier, request, ausser=verschoben)
