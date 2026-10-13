"""K.-o.-Runde automatisch befüllen.

Die K.-o.-Spiele tragen Platzhalter wie "1. Gruppe A", "Bester Gruppenzweiter" oder "Sieger HF 1"
(siehe spielplan.ko_stufen). Nach jedem eingetragenen Ergebnis setzt `aktualisieren` in allen noch
offenen K.-o.-Spielen die Teams ein, deren Platzhalter sich schon auflösen lassen:

- "<n>. Gruppe X": sobald alle Spiele der Gruppe beendet sind
- "Bester Gruppenzweiter": sobald alle Gruppen fertig sind; Vergleich nach Schnitt pro Spiel
- "Sieger/Verlierer VF|HF <n>": sobald das Spiel beendet ist

Steht ein Platz nach Tabelle und direktem Vergleich nicht fest (echter Gleichstand), wird er nicht
nach dem Alphabet vergeben, sondern bleibt leer; die Orga bekommt eine offene Entscheidung
("Entscheidungssatz spielen lassen, Sieger im Admin eintragen").

Der Platzhalter ist die Quelle: Wird ein Ergebnis korrigiert, ändert sich das Team in noch offenen
K.-o.-Spielen mit. Beendete K.-o.-Spiele bleiben unverändert. Wer ein Team von Hand setzt, leert im
Admin den Platzhalter.
"""

import re
from dataclasses import dataclass

from . import spielplan
from .models import Spiel, Turnier
from .tabelle import gruppentabellen

GRUPPENPLATZ = re.compile(r"^(\d+)\. Gruppe ([A-Z])$")
VORRUNDE = re.compile(r"^(Sieger|Verlierer) (VF|HF) (\d+)$")
BESTER_ZWEITER = "Bester Gruppenzweiter"
RUNDE = {"VF": "Viertelfinale", "HF": "Halbfinale"}


@dataclass
class Entscheidung:
    """Ein K.-o.-Platz, den die Tabelle nicht entscheiden kann."""
    spiel: Spiel
    platzhalter: str
    teams: tuple

    @property
    def text(self):
        namen = " und ".join(", ".join(t.name for t in self.teams).rsplit(", ", 1))
        return (
            f"{self.platzhalter}: Gleichstand zwischen {namen} – auch der direkte Vergleich entscheidet nicht. "
            f"Bitte einen Entscheidungssatz spielen lassen und den Sieger im Admin bei „{self.spiel.titel}“ "
            "eintragen (dort den Platzhalter leeren)."
        )


def _schnitt(zeile, satz_modus):
    """Werte pro Spiel – damit Zweite aus unterschiedlich großen Gruppen vergleichbar sind."""
    sp = zeile.sp or 1
    if satz_modus:
        return (zeile.s / sp, zeile.sd / sp, zeile.pd / sp)
    return (zeile.s / sp, zeile.pd / sp, zeile.punkte_plus / sp)


def _verlierer(spiel):
    sieger = spiel.sieger
    if sieger is None:
        return None
    return spiel.team_b if sieger == spiel.team_a else spiel.team_a


def _planen(turnier):
    """Was in offenen K.-o.-Spielen stehen müsste: ({(spiel, seite): team oder None}, [Entscheidung])."""
    if turnier.modus != Turnier.Modus.GRUPPEN_KO:
        return {}, []
    satz_modus = turnier.zaehlmodus == Turnier.Zaehlmodus.SAETZE
    spiele = spielplan.mit_titeln(turnier)
    for s in spiele:
        s.turnier = turnier  # für Spiel.sieger, ohne weitere Abfrage

    fertig = {}
    for gruppe, tabelle in gruppentabellen(turnier):
        gruppenspiele = [s for s in spiele if s.gruppe_id == gruppe.pk]
        if gruppenspiele and all(s.status == Spiel.Status.BEENDET for s in gruppenspiele):
            fertig[gruppe.name] = tabelle
    alle_gruppen_fertig = bool(fertig) and len(fertig) == turnier.gruppen.count()
    ko_spiele = [s for s in spiele if s.phase != Spiel.Phase.GRUPPE]
    nach_titel = {s.titel: s for s in ko_spiele}

    def aufloesen(platzhalter):
        """(team, None) wenn klar, (None, teams) bei echtem Gleichstand, (None, None) wenn noch offen."""
        if m := GRUPPENPLATZ.match(platzhalter):
            platz, name = int(m.group(1)), m.group(2)
            tabelle = fertig.get(name)
            if not tabelle or len(tabelle) < platz:
                return None, None
            zeile = tabelle[platz - 1]
            return (None, zeile.gleichstand) if zeile.gleichstand else (zeile.team, None)
        if platzhalter == BESTER_ZWEITER:
            if not alle_gruppen_fertig:
                return None, None
            zweite = [t[1] for t in fertig.values() if len(t) >= 2]
            if not zweite:
                return None, None
            bester = max(_schnitt(z, satz_modus) for z in zweite)
            kandidaten = [z for z in zweite if _schnitt(z, satz_modus) == bester]
            if len(kandidaten) > 1:
                return None, tuple(z.team for z in kandidaten)
            if kandidaten[0].gleichstand:  # Platz 2 in der eigenen Gruppe ist selbst offen
                return None, kandidaten[0].gleichstand
            return kandidaten[0].team, None
        if m := VORRUNDE.match(platzhalter):
            art, runde, nummer = m.groups()
            vorher = nach_titel.get(f"{RUNDE[runde]} {nummer}")
            if not vorher or vorher.status != Spiel.Status.BEENDET:
                return None, None
            return (vorher.sieger if art == "Sieger" else _verlierer(vorher)), None
        return None, None

    soll, entscheidungen = {}, []
    for spiel in sorted(ko_spiele, key=lambda s: (s.uhrzeit is None, s.uhrzeit, s.feld, s.pk)):
        if spiel.status != Spiel.Status.GEPLANT:
            continue
        for seite in ("a", "b"):
            platzhalter = getattr(spiel, f"platzhalter_{seite}")
            if not platzhalter:
                continue
            team, gleichstand = aufloesen(platzhalter)
            if gleichstand:
                entscheidungen.append(Entscheidung(spiel, platzhalter, gleichstand))
                soll[(spiel, seite)] = None  # nicht nach dem Alphabet vergeben
            elif team:
                soll[(spiel, seite)] = team
    return soll, entscheidungen


def offene_entscheidungen(turnier):
    """K.-o.-Plätze, die ein Entscheidungssatz klären muss (für die Orga-Spielplanseite)."""
    return _planen(turnier)[1]


def aktualisieren(turnier):
    """Offene K.-o.-Spiele befüllen. Gibt Meldungen für die Orga zurück (geänderte Spiele, offene Entscheidungen)."""
    soll, entscheidungen = _planen(turnier)
    geaendert = []
    for (spiel, seite), team in soll.items():
        if getattr(spiel, f"team_{seite}_id") != (team.pk if team else None):
            setattr(spiel, f"team_{seite}", team)
            if spiel not in geaendert:
                geaendert.append(spiel)
    meldungen = []
    for spiel in geaendert:
        spiel.save(update_fields=["team_a", "team_b"])
        meldungen.append(f"{spiel.titel}: {spiel.team_a or spiel.platzhalter_a} – {spiel.team_b or spiel.platzhalter_b}")
    return meldungen + [e.text for e in entscheidungen]
