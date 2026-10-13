import logging
from datetime import datetime, timedelta

from django.contrib import messages
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import spielplan as plan
from .forms import AnmeldeForm, spieler_formset
from .models import Spiel, Spieler, Team, Turnier
from .tabelle import gruppentabellen

logger = logging.getLogger(__name__)


def _sichtbare_teams(turnier):
    """Teams für öffentliche Listen: ohne Absagen, Startplätze vor Warteliste."""
    teams = turnier.teams.exclude(status=Team.Status.ABGESAGT).prefetch_related(
        Prefetch("spieler", queryset=Spieler.objects.order_by("nachname", "vorname"))
    ).order_by("pk")
    return sorted(teams, key=lambda t: not t.hat_startplatz)


def startseite(request):
    turnier = Turnier.aktuelles()
    teams = _sichtbare_teams(turnier) if turnier else []
    return render(request, "tournament/startseite.html", {
        "turnier": turnier,
        "teams": teams,
        "plaetze": [i < turnier.belegte_plaetze for i in range(turnier.max_teams)] if turnier else [],
    })


def teamliste(request):
    turnier = Turnier.aktuelles()
    return render(request, "tournament/teamliste.html", {
        "turnier": turnier,
        "teams": _sichtbare_teams(turnier) if turnier else [],
    })


def laeuft(turnier, zeit, jetzt):
    """Ist der Slot `zeit` am Spieltag gerade dran?"""
    beginn = timezone.make_aware(datetime.combine(turnier.datum, zeit))
    return beginn <= jetzt < beginn + timedelta(minutes=turnier.slot_minuten)


def _ko_hinweis(turnier, anzahl_gruppen):
    if turnier.modus != Turnier.Modus.GRUPPEN_KO:
        return ""
    return {
        2: "Platz 1 und 2 jeder Gruppe ziehen ins Halbfinale ein.",
        3: "Die Gruppensieger und der beste Gruppenzweite ziehen ins Halbfinale ein.",
        4: "Platz 1 und 2 jeder Gruppe ziehen ins Viertelfinale ein.",
    }.get(anzahl_gruppen, "")


def spielplan(request):
    turnier = Turnier.aktuelles()
    if not turnier or not turnier.spielplan_veroeffentlicht:
        return render(request, "tournament/spielplan.html", {"turnier": turnier})

    jetzt = timezone.now()
    satz_modus = turnier.zaehlmodus == Turnier.Zaehlmodus.SAETZE
    spiele = [s for s in plan.mit_titeln(turnier) if s.uhrzeit]
    for s in spiele:
        s.wert_a, s.wert_b = (s.saetze_a, s.saetze_b) if satz_modus else (s.punkte_a, s.punkte_b)
        fertig = s.status == Spiel.Status.BEENDET and None not in (s.wert_a, s.wert_b)
        s.a_gewinnt = fertig and s.wert_a > s.wert_b
        s.b_gewinnt = fertig and s.wert_b > s.wert_a
    slots = []
    for zeit in sorted({s.uhrzeit for s in spiele}):
        im_slot = sorted((s for s in spiele if s.uhrzeit == zeit), key=lambda s: s.feld)
        slots.append({"zeit": zeit, "spiele": im_slot, "laeuft": laeuft(turnier, zeit, jetzt)})
    tabellen = gruppentabellen(turnier)
    ko = [s for s in spiele if s.phase != Spiel.Phase.GRUPPE]
    return render(request, "tournament/spielplan.html", {
        "turnier": turnier,
        "slots": slots,
        "felder": range(1, max([turnier.anzahl_felder] + [s.feld for s in spiele]) + 1),
        "tabellen": tabellen,
        "ko_beginn": min((s.uhrzeit for s in ko), default=None),
        "ko_hinweis": _ko_hinweis(turnier, len(tabellen)),
        "satz_modus": satz_modus,
    })


def datenschutz(request):
    return render(request, "tournament/datenschutz.html")


def anmelden(request):
    turnier = Turnier.aktuelles()
    if not turnier or not turnier.anmeldung_moeglich:
        return render(request, "tournament/anmeldung_geschlossen.html", {"turnier": turnier})

    SpielerFormSet = spieler_formset(turnier, extra=turnier.min_spieler)
    form = AnmeldeForm(request.POST or None, turnier=turnier)
    formset = SpielerFormSet(request.POST or None, turnier=turnier, prefix="spieler")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            team = form.save(commit=False)
            team.turnier = turnier
            team.status = Team.Status.ANGEMELDET if turnier.freie_plaetze else Team.Status.WARTELISTE
            team.save()
            formset.instance = team
            formset.save()
        _bearbeitungslink_senden(request, team)
        return redirect("team_angemeldet", token=team.edit_token)

    return render(request, "tournament/anmelden.html", {"turnier": turnier, "form": form, "formset": formset})


def _bearbeitungslink_senden(request, team):
    link = request.build_absolute_uri(reverse("team_bearbeiten", args=[team.edit_token]))
    text = render_to_string("mail/bearbeitungslink.txt", {"team": team, "turnier": team.turnier, "link": link})
    try:
        send_mail(f"Eure Anmeldung: {team.turnier.name}", text, None, [team.kapitaen_email])
    except Exception:
        # Die Anmeldung gilt trotzdem; die Orga sieht den Link im Admin.
        logger.exception("Bearbeitungslink für Team %s konnte nicht verschickt werden", team.pk)


def team_angemeldet(request, token):
    team = get_object_or_404(Team.objects.select_related("turnier"), edit_token=token)
    return render(request, "tournament/team_angemeldet.html", {"team": team, "turnier": team.turnier})


def team_bearbeiten(request, token):
    team = get_object_or_404(Team.objects.select_related("turnier"), edit_token=token)
    turnier = team.turnier
    darf_aendern = not turnier.meldeschluss_vorbei and team.status != Team.Status.ABGESAGT

    SpielerFormSet = spieler_formset(turnier)
    formset = SpielerFormSet(
        request.POST if request.method == "POST" and darf_aendern else None,
        instance=team, turnier=turnier, prefix="spieler",
        queryset=team.spieler.order_by("pk"),
    )
    if request.method == "POST" and darf_aendern and formset.is_valid():
        formset.save()
        messages.success(request, "Änderungen gespeichert.")
        return redirect("team_bearbeiten", token=token)

    return render(request, "tournament/team_bearbeiten.html", {
        "team": team, "turnier": turnier, "formset": formset, "darf_aendern": darf_aendern,
    })


@require_POST
def team_abmelden(request, token):
    team = get_object_or_404(Team, edit_token=token)
    if not team.turnier.meldeschluss_vorbei and team.status != Team.Status.ABGESAGT:
        team.status = Team.Status.ABGESAGT
        team.save()
        messages.success(request, "Euer Team ist abgemeldet.")
    return redirect("team_bearbeiten", token=token)
