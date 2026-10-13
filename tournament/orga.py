"""Orga-Seiten außerhalb des Admins: Spielplan erzeugen/anpassen (Screen 07) und Ergebnis eintragen (Screen 08)."""

from datetime import datetime, timedelta

from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import ko, spielplan
from .models import Spiel, Team, Turnier
from .tabelle import gruppentabellen


class SpielplanForm(forms.Form):
    modus = forms.ChoiceField(choices=Turnier.Modus.choices, widget=forms.RadioSelect)
    anzahl_gruppen = forms.TypedChoiceField(choices=[(2, "2"), (3, "3"), (4, "4")], coerce=int, required=False)
    beginn = forms.TimeField(label="Startzeit", widget=forms.TimeInput(attrs={"type": "time"}))
    slot_minuten = forms.IntegerField(label="Slotlänge (min)", min_value=5, max_value=120)


def _turnier(request):
    turnier_id = request.GET.get("turnier") or request.POST.get("turnier")
    return get_object_or_404(Turnier, pk=turnier_id) if turnier_id else Turnier.aktuelles()


def _spiele(turnier):
    return spielplan.mit_titeln(turnier)


@staff_member_required
def spielplan_seite(request):
    turnier = _turnier(request)
    if not turnier:
        messages.warning(request, "Bitte zuerst ein Turnier anlegen.")
        return redirect("admin:tournament_turnier_add")
    anzahl_teams = Team.objects.im_spielplan().filter(turnier=turnier).count()
    hier = f"{reverse('orga_spielplan')}?turnier={turnier.pk}"

    form = SpielplanForm(request.POST if request.POST.get("aktion") == "erzeugen" else None, initial={
        "modus": turnier.modus, "beginn": turnier.beginn, "slot_minuten": turnier.slot_minuten,
        "anzahl_gruppen": turnier.gruppen.count() if turnier.modus == Turnier.Modus.GRUPPEN_KO and turnier.gruppen.exists()
        else spielplan.gruppen_vorschlag(anzahl_teams),
    })

    if request.method == "POST":
        aktion = request.POST.get("aktion")
        if aktion == "erzeugen" and form.is_valid():
            turnier.modus = form.cleaned_data["modus"]
            turnier.beginn = form.cleaned_data["beginn"]
            turnier.slot_minuten = form.cleaned_data["slot_minuten"]
            turnier.save(update_fields=["modus", "beginn", "slot_minuten"])
            try:
                spielplan.erzeugen(turnier, form.cleaned_data.get("anzahl_gruppen"))
                messages.success(request, "Spielplan erzeugt. Spiele per Drag & Drop tauschen, dann veröffentlichen.")
            except spielplan.SpielplanFehler as fehler:
                messages.error(request, str(fehler))
            return redirect(hier)
        if aktion == "verschieben":
            spiel = get_object_or_404(Spiel, pk=request.POST.get("spiel"), turnier=turnier)
            if request.POST.get("ziel_spiel"):
                spielplan.tauschen(spiel, get_object_or_404(Spiel, pk=request.POST["ziel_spiel"], turnier=turnier))
            else:
                zeit = datetime.strptime(request.POST["ziel_zeit"], "%H:%M").time()
                spielplan.verschieben(spiel, zeit, int(request.POST["ziel_feld"]))
            spielplan.schiris_neu(turnier)
            return redirect(hier)
        if aktion in ("veroeffentlichen", "zurueckziehen"):
            turnier.spielplan_veroeffentlicht = aktion == "veroeffentlichen"
            turnier.save(update_fields=["spielplan_veroeffentlicht"])
            messages.success(request, "Spielplan ist öffentlich." if turnier.spielplan_veroeffentlicht
                             else "Spielplan ist nicht mehr öffentlich.")
            return redirect(hier)

    spiele = _spiele(turnier)
    zeiten = sorted({s.uhrzeit for s in spiele if s.uhrzeit})
    felder = list(range(1, max([turnier.anzahl_felder] + [s.feld for s in spiele]) + 1))
    belegung = {(s.uhrzeit, s.feld): s for s in spiele}
    ende = (datetime.combine(turnier.datum, zeiten[-1]) + timedelta(minutes=turnier.slot_minuten)).time() if zeiten else None

    return render(request, "tournament/orga/spielplan.html", {
        "turnier": turnier,
        "turniere": Turnier.objects.all(),
        "form": form,
        "anzahl_teams": anzahl_teams,
        "hat_ergebnisse": any(s.status == Spiel.Status.BEENDET for s in spiele),
        "zeilen": [(z, [belegung.get((z, f)) for f in felder]) for z in zeiten],
        "felder": felder,
        "anzahl_spiele": len(spiele),
        "ende": ende,
        "konflikte": spielplan.konflikte(spiele),
        "tabellen": gruppentabellen(turnier),
        "ohne_zeit": [s for s in spiele if not s.uhrzeit],
    })


@staff_member_required
def ergebnis_seite(request, pk):
    spiel = get_object_or_404(Spiel.objects.select_related("turnier", "gruppe", "team_a", "team_b", "schiri_team"), pk=pk)
    turnier = spiel.turnier
    satz_modus = turnier.zaehlmodus == Turnier.Zaehlmodus.SAETZE
    spiele = _spiele(turnier)
    spiel = next(s for s in spiele if s.pk == spiel.pk)
    fehler = []

    if request.method == "POST":
        def zahl(name):
            wert = request.POST.get(name, "").strip()
            return int(wert) if wert.isdigit() else None

        if satz_modus:
            spiel.saetze_a, spiel.saetze_b = zahl("saetze_a"), zahl("saetze_b")
        spiel.punkte_a, spiel.punkte_b = zahl("punkte_a"), zahl("punkte_b")
        spiel.status = Spiel.Status.BEENDET
        try:
            spiel.full_clean()
            spiel.save()
            messages.success(request, "Gespeichert.")
            for meldung in ko.aktualisieren(turnier):
                messages.info(request, meldung)
            return redirect("orga_ergebnis", pk=spiel.pk)
        except ValidationError as e:
            spiel.status = Spiel.Status.GEPLANT
            fehler = [m for liste in e.message_dict.values() for m in liste]

    zeitlich = [s for s in spiele if s.uhrzeit]
    zeitlich.sort(key=lambda s: (s.uhrzeit, s.feld))
    naechstes = next((s for s in zeitlich if s.status == Spiel.Status.GEPLANT and s.pk != spiel.pk
                      and (s.uhrzeit, s.feld) > (spiel.uhrzeit, spiel.feld)), None) if spiel.uhrzeit else None
    return render(request, "tournament/orga/ergebnis.html", {
        "spiel": spiel,
        "turnier": turnier,
        "satz_modus": satz_modus,
        "korrigieren": request.GET.get("korrigieren") or fehler or spiel.status == Spiel.Status.GEPLANT,
        "fehler": fehler,
        "nummer": zeitlich.index(spiel) + 1 if spiel in zeitlich else None,
        "anzahl": len(zeitlich),
        "naechstes": naechstes,
        "parallel": [s for s in zeitlich if s.uhrzeit == spiel.uhrzeit and s.pk != spiel.pk],
    })
