"""Warteliste: Wer sich zuerst angemeldet hat, rückt zuerst nach.

`nachruecken` holt ein Team von der Warteliste und schickt dem Kapitän eine Mail.
`auffuellen` füllt freie Plätze automatisch – nur wenn beim Turnier
"Warteliste automatisch nachrücken lassen" angehakt ist und das Turnier nicht vorbei ist.
Aufgerufen nach allem, was einen Platz frei machen kann: Abmeldung des Kapitäns, Absage oder
Löschen im Admin, mehr Plätze beim Turnier.
"""

import logging

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

from .models import Team

logger = logging.getLogger(__name__)


def nachruecken(team, request):
    """Team von der Warteliste holen und den Kapitän informieren."""
    team.status = Team.Status.ANGEMELDET
    team.save()  # bezahlte Teams werden dabei direkt bestätigt
    if not team.kapitaen_email:
        return
    link = request.build_absolute_uri(reverse("team_bearbeiten", args=[team.edit_token]))
    text = render_to_string("mail/nachgerueckt.txt", {"team": team, "turnier": team.turnier, "link": link})
    try:
        send_mail(f"Ihr seid nachgerückt: {team.turnier.name}", text, None, [team.kapitaen_email])
    except Exception:
        logger.exception("Nachrück-Mail für Team %s konnte nicht verschickt werden", team.pk)


def auffuellen(turnier, request, ausser=None):
    """Freie Plätze in Anmelde-Reihenfolge von der Warteliste füllen. Gibt die nachgerückten Teams zurück.
    `ausser`: Team, das die Orga gerade selbst auf die Warteliste gesetzt hat – es wird nicht sofort wieder geholt."""
    if not turnier.warteliste_automatisch or turnier.vorbei:
        return []
    wartend = turnier.teams.filter(status=Team.Status.WARTELISTE).order_by(*Team.REIHENFOLGE)
    if ausser is not None:
        wartend = wartend.exclude(pk=ausser.pk)
    nachgerueckt = []
    while turnier.freie_plaetze > 0:
        team = wartend.first()
        if team is None:
            break
        nachruecken(team, request)
        nachgerueckt.append(team)
    return nachgerueckt
