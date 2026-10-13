"""Spielplan: Gruppen, Kreismethode, Slots, Schiris, K.-o.-Platzhalter, Umplanen.

Die Funktionen im ersten Teil arbeiten mit beliebigen hashbaren Teams und brauchen keine Datenbank.
"""

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction

from .models import Gruppe, Spiel, Team, Turnier

GRUPPENNAMEN = "ABCD"
Phase = Spiel.Phase


@dataclass
class Partie:
    a: object
    b: object
    gruppe: object = None
    runde: int = 1
    spielfrei: object = None  # spielfreies Team der Runde, pfeift bevorzugt
    schiri: object = None
    spiel: Spiel = None  # bestehendes Spiel (beim Umplanen)
    fest: bool = False  # Schiri nicht neu zuteilen (beendetes Spiel)


# --- Reine Funktionen ------------------------------------------------------------------------

def gruppen_vorschlag(anzahl_teams):
    """Gruppen mit höchstens 5 Teams; mindestens 2, höchstens 4 Gruppen."""
    return min(max(math.ceil(anzahl_teams / 5), 2), 4)


def gruppen_bilden(teams, anzahl, zufall=None):
    """Teams zufällig und möglichst gleich groß auf `anzahl` Gruppen verteilen."""
    teams = list(teams)
    (zufall or random.Random()).shuffle(teams)
    gruppen = [[] for _ in range(anzahl)]
    for i, team in enumerate(teams):
        gruppen[i % anzahl].append(team)
    return gruppen


def kreismethode(teams):
    """Runden eines Rundenturniers: Liste von (paarungen, spielfreies Team oder None)."""
    teams = list(teams)
    if len(teams) % 2:
        teams.append(None)  # Platzhalter "spielfrei"
    n = len(teams)
    runden = []
    for r in range(n - 1):
        paarungen, spielfrei = [], None
        for i in range(n // 2):
            a, b = teams[i], teams[n - 1 - i]
            if i == 0 and r % 2:
                a, b = b, a  # das feste Team nicht immer zuerst nennen
            if a is None or b is None:
                spielfrei = b if a is None else a
            else:
                paarungen.append((a, b))
        runden.append((paarungen, spielfrei))
        teams = [teams[0], teams[-1]] + teams[1:-1]  # erstes Team fest, Rest rotiert
    return runden


def verzahnen(listen):
    """Abwechselnd je ein Element aus jeder Liste: A1, B1, A2, B2, …"""
    listen = [list(liste) for liste in listen]
    ergebnis = []
    while any(listen):
        for liste in listen:
            if liste:
                ergebnis.append(liste.pop(0))
    return ergebnis


def gruppenpartien(gruppen, gespielt=frozenset()):
    """Partien aller Gruppen, rundenweise verzahnt. gruppen: [(schluessel, teams)].
    Paare in `gespielt` (frozensets) werden ausgelassen."""
    je_gruppe = []
    for schluessel, teams in gruppen:
        partien = []
        for runde, (paarungen, spielfrei) in enumerate(kreismethode(teams), start=1):
            for a, b in paarungen:
                if frozenset((a, b)) not in gespielt:
                    partien.append(Partie(a, b, schluessel, runde, spielfrei))
        je_gruppe.append(partien)
    return verzahnen(je_gruppe)


def slots_verteilen(partien, felder):
    """Partien der Reihe nach in Slots legen: höchstens `felder` Spiele, kein Team doppelt."""
    offen = list(partien)
    slots = []
    while offen:
        slot, belegt = [], set()
        for partie in list(offen):
            if len(slot) == felder:
                break
            if partie.a in belegt or partie.b in belegt:
                continue
            slot.append(partie)
            belegt.update((partie.a, partie.b))
            offen.remove(partie)
        slots.append(slot)
    return slots


def schiris_zuteilen(slots, gruppen_teams):
    """Pro Spiel ein Team, das im Slot weder spielt noch schon pfeift. Bevorzugt das spielfreie
    Team der Runde, sonst ein Team der Gruppe mit den wenigsten Einsätzen, sonst irgendeins."""
    einsaetze = Counter()
    alle = [t for teams in gruppen_teams.values() for t in teams]
    for slot in slots:
        beschaeftigt = {t for p in slot for t in (p.a, p.b)} | {p.schiri for p in slot if p.fest and p.schiri}
        for p in slot:
            if p.fest:
                continue
            frei = [t for t in gruppen_teams.get(p.gruppe, []) if t not in beschaeftigt]
            frei = frei or [t for t in alle if t not in beschaeftigt]
            if not frei:
                p.schiri = None
                continue
            p.schiri = p.spielfrei if p.spielfrei in frei else min(frei, key=lambda t: einsaetze[t])
            einsaetze[p.schiri] += 1
            beschaeftigt.add(p.schiri)
    return slots


def ko_stufen(anzahl_gruppen):
    """K.-o.-Spiele als Stufen von (phase, platzhalter_a, platzhalter_b)."""
    if anzahl_gruppen == 2:
        stufen = [[(Phase.HALBFINALE, "1. Gruppe A", "2. Gruppe B"),
                   (Phase.HALBFINALE, "1. Gruppe B", "2. Gruppe A")]]
    elif anzahl_gruppen == 3:
        stufen = [[(Phase.HALBFINALE, "1. Gruppe A", "Bester Gruppenzweiter"),
                   (Phase.HALBFINALE, "1. Gruppe B", "1. Gruppe C")]]
    elif anzahl_gruppen == 4:
        stufen = [
            [(Phase.VIERTELFINALE, "1. Gruppe A", "2. Gruppe B"),
             (Phase.VIERTELFINALE, "1. Gruppe B", "2. Gruppe A"),
             (Phase.VIERTELFINALE, "1. Gruppe C", "2. Gruppe D"),
             (Phase.VIERTELFINALE, "1. Gruppe D", "2. Gruppe C")],
            [(Phase.HALBFINALE, "Sieger VF 1", "Sieger VF 3"),
             (Phase.HALBFINALE, "Sieger VF 2", "Sieger VF 4")],
        ]
    else:
        return []
    stufen.append([(Phase.PLATZ_3, "Verlierer HF 1", "Verlierer HF 2"),
                   (Phase.FINALE, "Sieger HF 1", "Sieger HF 2")])
    return stufen


def in_slots(stufen, felder):
    """Jede Stufe auf Slots mit höchstens `felder` Spielen aufteilen."""
    return [stufe[i:i + felder] for stufe in stufen for i in range(0, len(stufe), felder)]


# --- Mit Datenbank ---------------------------------------------------------------------------

class SpielplanFehler(Exception):
    pass


def _zeit(turnier, start, minuten):
    return (datetime.combine(turnier.datum, start) + timedelta(minutes=minuten)).time()


def _speichern(turnier, gruppen_teams, partien, ko_slots, start):
    """Gruppenpartien und K.-o.-Slots ab `start` auf Slots und Felder legen und speichern.
    ko_slots enthält neue Einträge (phase, platzhalter_a, platzhalter_b) oder bestehende Spiele."""
    slots = schiris_zuteilen(slots_verteilen(partien, turnier.anzahl_felder), gruppen_teams)
    for i, slot in enumerate(slots):
        zeit = _zeit(turnier, start, i * turnier.slot_minuten)
        for feld, p in enumerate(slot, start=1):
            spiel = p.spiel or Spiel(turnier=turnier)
            spiel.gruppe, spiel.phase, spiel.runde = p.gruppe, Phase.GRUPPE, p.runde
            spiel.team_a, spiel.team_b, spiel.schiri_team = p.a, p.b, p.schiri
            spiel.uhrzeit, spiel.feld = zeit, feld
            spiel.save()
    for i, slot in enumerate(ko_slots, start=len(slots)):
        zeit = _zeit(turnier, start, i * turnier.slot_minuten)
        for feld, eintrag in enumerate(slot, start=1):
            if isinstance(eintrag, Spiel):
                spiel = eintrag
            else:
                phase, a, b = eintrag
                spiel = Spiel(turnier=turnier, phase=phase, platzhalter_a=a, platzhalter_b=b)
            spiel.uhrzeit, spiel.feld = zeit, feld
            spiel.save()


@transaction.atomic
def erzeugen(turnier, anzahl_gruppen=None, zufall=None):
    """Neuen Spielplan aus allen bestätigten und bezahlten Teams erzeugen (ersetzt den alten)."""
    if turnier.spiele.filter(status=Spiel.Status.BEENDET).exists():
        raise SpielplanFehler("Es gibt schon Ergebnisse – der Plan kann nicht mehr neu erzeugt werden.")
    if not turnier.beginn:
        raise SpielplanFehler("Bitte zuerst eine Startzeit festlegen.")
    teams = list(Team.objects.im_spielplan().filter(turnier=turnier).order_by("pk"))
    if turnier.modus == Turnier.Modus.JEDER_GEGEN_JEDEN:
        anzahl, mindestens = 1, 2
    else:
        anzahl = anzahl_gruppen or gruppen_vorschlag(len(teams))
        if anzahl not in (2, 3, 4):
            raise SpielplanFehler("Es sind 2, 3 oder 4 Gruppen möglich.")
        mindestens = 3 * anzahl
    if len(teams) < mindestens:
        raise SpielplanFehler(
            f"Dafür braucht es mindestens {mindestens} bestätigte und bezahlte Teams (aktuell {len(teams)})."
        )

    turnier.spiele.all().delete()
    turnier.gruppen.all().delete()
    gruppen = []
    for name, mitglieder in zip(GRUPPENNAMEN, gruppen_bilden(teams, anzahl, zufall)):
        gruppe = Gruppe.objects.create(turnier=turnier, name=name)
        Team.objects.filter(pk__in=[t.pk for t in mitglieder]).update(gruppe=gruppe)
        gruppen.append((gruppe, mitglieder))

    ko = ko_stufen(anzahl) if turnier.modus == Turnier.Modus.GRUPPEN_KO else []
    _speichern(turnier, dict(gruppen), gruppenpartien(gruppen), in_slots(ko, turnier.anzahl_felder), turnier.beginn)
    turnier.spielplan_veroeffentlicht = False
    turnier.save(update_fields=["spielplan_veroeffentlicht"])


@transaction.atomic
def umplanen(turnier, betroffene_gruppen_ids):
    """Nach dem Löschen von Teams: Beendete Spiele bleiben. In betroffenen Gruppen werden die offenen
    Spiele ohne die gelöschten Teams neu gepaart; danach rücken alle offenen Spiele lückenlos auf."""
    geplant = list(turnier.spiele.filter(status=Spiel.Status.GEPLANT)
                   .select_related("team_a", "team_b").order_by("uhrzeit", "feld"))
    if not turnier.beginn or not any(s.uhrzeit for s in geplant):
        return
    beendet = list(turnier.spiele.filter(status=Spiel.Status.BEENDET))

    start = min(s.uhrzeit for s in geplant if s.uhrzeit)
    zuletzt = max((s.uhrzeit for s in beendet if s.uhrzeit), default=None)
    if zuletzt and zuletzt >= start:
        start = _zeit(turnier, zuletzt, turnier.slot_minuten)

    gruppen_teams, je_gruppe = {}, []
    for gruppe in turnier.gruppen.order_by("name"):
        teams = list(gruppe.teams.order_by("pk"))
        gruppen_teams[gruppe] = teams
        offen = [s for s in geplant if s.gruppe_id == gruppe.pk]
        if gruppe.pk in betroffene_gruppen_ids:
            Spiel.objects.filter(pk__in=[s.pk for s in offen]).delete()
            gespielt = {frozenset((s.team_a, s.team_b)) for s in beendet
                        if s.gruppe_id == gruppe.pk and s.team_a and s.team_b}
            je_gruppe.append(gruppenpartien([(gruppe, teams)], gespielt))
        else:
            je_gruppe.append([Partie(s.team_a, s.team_b, gruppe, s.runde, spiel=s) for s in offen])

    ko_slots = defaultdict(list)
    for s in geplant:
        if s.phase != Phase.GRUPPE:
            ko_slots[s.uhrzeit].append(s)
    _speichern(turnier, gruppen_teams, verzahnen(je_gruppe), [ko_slots[z] for z in sorted(ko_slots)], start)


def schiris_neu(turnier):
    """Schiris aller offenen Gruppenspiele neu verteilen, z. B. nach dem Verschieben.
    Spielfrei ist ein Team, das in seiner Gruppe in dieser Runde nicht spielt."""
    spiele = list(turnier.spiele.filter(phase=Phase.GRUPPE).exclude(uhrzeit=None)
                  .select_related("team_a", "team_b", "schiri_team"))
    gruppen_teams = {g.pk: list(g.teams.order_by("pk")) for g in turnier.gruppen.all()}
    in_runde = defaultdict(set)
    for s in spiele:
        in_runde[(s.gruppe_id, s.runde)].update(t for t in (s.team_a, s.team_b) if t)

    je_slot = defaultdict(list)
    for s in spiele:
        fehlend = [t for t in gruppen_teams.get(s.gruppe_id, []) if t not in in_runde[(s.gruppe_id, s.runde)]]
        je_slot[s.uhrzeit].append(Partie(
            s.team_a, s.team_b, s.gruppe_id, s.runde, spielfrei=fehlend[0] if len(fehlend) == 1 else None,
            schiri=s.schiri_team, spiel=s, fest=s.status == Spiel.Status.BEENDET,
        ))
    slots = schiris_zuteilen([je_slot[z] for z in sorted(je_slot)], gruppen_teams)
    for slot in slots:
        for p in slot:
            if not p.fest and p.spiel.schiri_team != p.schiri:
                p.spiel.schiri_team = p.schiri
                p.spiel.save(update_fields=["schiri_team"])


def titel_setzen(spiele):
    """Spieltitel: "Gruppe A" bzw. "Halbfinale 1" (Nummer nach Zeit und Feld)."""
    zaehler = {}
    for s in sorted(spiele, key=lambda s: (s.uhrzeit is None, s.uhrzeit, s.feld)):
        if s.phase == Spiel.Phase.GRUPPE:
            s.titel = f"Gruppe {s.gruppe.name}" if s.gruppe else "Gruppenspiel"
        elif s.phase in (Spiel.Phase.FINALE, Spiel.Phase.PLATZ_3):
            s.titel = s.get_phase_display()
        else:
            zaehler[s.phase] = zaehler.get(s.phase, 0) + 1
            s.titel = f"{s.get_phase_display()} {zaehler[s.phase]}"
    return spiele


def mit_titeln(turnier):
    """Alle Spiele eines Turniers mit Teams und gesetztem `titel`."""
    return titel_setzen(list(turnier.spiele.select_related("gruppe", "team_a", "team_b", "schiri_team")))


def tauschen(spiel, anderes):
    spiel.uhrzeit, anderes.uhrzeit = anderes.uhrzeit, spiel.uhrzeit
    spiel.feld, anderes.feld = anderes.feld, spiel.feld
    spiel.save(update_fields=["uhrzeit", "feld"])
    anderes.save(update_fields=["uhrzeit", "feld"])


def verschieben(spiel, uhrzeit, feld):
    spiel.uhrzeit, spiel.feld = uhrzeit, feld
    spiel.save(update_fields=["uhrzeit", "feld"])


def konflikte(spiele):
    """Hinweise, wenn ein Feld doppelt belegt ist oder ein Team im selben Slot mehrfach auftaucht."""
    hinweise = []
    je_slot = defaultdict(list)
    for s in spiele:
        if s.uhrzeit:
            je_slot[s.uhrzeit].append(s)
    for zeit in sorted(je_slot):
        slot = je_slot[zeit]
        uhr = zeit.strftime("%H:%M")
        felder = Counter(s.feld for s in slot)
        hinweise += [f"{uhr}: Feld {f} ist doppelt belegt." for f, n in felder.items() if n > 1]
        teams = Counter(t for s in slot for t in (s.team_a, s.team_b, s.schiri_team) if t)
        hinweise += [f"{uhr}: {t} ist mehrfach eingeplant." for t, n in teams.items() if n > 1]
    return hinweise
