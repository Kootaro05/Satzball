"""K.-o.-Runde automatisch befüllen.

Die K.-o.-Spiele tragen Platzhalter wie "1. Gruppe A", "Bester Gruppenzweiter" oder "Sieger HF 1"
(siehe spielplan.ko_stufen). Nach jedem eingetragenen Ergebnis setzt `aktualisieren` in allen noch
offenen K.-o.-Spielen die Teams ein, deren Platzhalter sich schon auflösen lassen:

- "<n>. Gruppe X": sobald alle Spiele der Gruppe beendet sind
- "Bester Gruppenzweiter": sobald alle Gruppen fertig sind; Vergleich nach Schnitt pro Spiel
- "Sieger/Verlierer VF|HF <n>": sobald das Spiel beendet ist

Der Platzhalter ist die Quelle: Wird ein Ergebnis korrigiert, ändert sich das Team in noch offenen
K.-o.-Spielen mit. Beendete K.-o.-Spiele bleiben unverändert. Wer ein Team von Hand setzen will,
leert im Admin den Platzhalter.
"""

import re

from . import spielplan
from .models import Spiel, Turnier
from .tabelle import gruppentabellen

GRUPPENPLATZ = re.compile(r"^(\d+)\. Gruppe ([A-Z])$")
VORRUNDE = re.compile(r"^(Sieger|Verlierer) (VF|HF) (\d+)$")
BESTER_ZWEITER = "Bester Gruppenzweiter"
RUNDE = {"VF": "Viertelfinale", "HF": "Halbfinale"}


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


def aktualisieren(turnier):
    """Offene K.-o.-Spiele befüllen. Gibt Meldungen für die Orga zurück (neu gesetzte Spiele, Gleichstände)."""
    if turnier.modus != Turnier.Modus.GRUPPEN_KO:
        return []
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
    genutzte_gruppen = set()

    def aufloesen(platzhalter):
        if m := GRUPPENPLATZ.match(platzhalter):
            platz, name = int(m.group(1)), m.group(2)
            tabelle = fertig.get(name)
            if tabelle and len(tabelle) >= platz:
                genutzte_gruppen.add(name)
                return tabelle[platz - 1].team
            return None
        if platzhalter == BESTER_ZWEITER:
            if not alle_gruppen_fertig:
                return None
            zweite = [t[1] for t in fertig.values() if len(t) >= 2]
            if not zweite:
                return None
            genutzte_gruppen.update(fertig)
            return min(zweite, key=lambda z: (*(-w for w in _schnitt(z, satz_modus)), str(z.team))).team
        if m := VORRUNDE.match(platzhalter):
            art, runde, nummer = m.groups()
            vorher = nach_titel.get(f"{RUNDE[runde]} {nummer}")
            if not vorher or vorher.status != Spiel.Status.BEENDET:
                return None
            return vorher.sieger if art == "Sieger" else _verlierer(vorher)
        return None

    meldungen = []
    for spiel in sorted(ko_spiele, key=lambda s: (s.uhrzeit is None, s.uhrzeit, s.feld, s.pk)):
        if spiel.status != Spiel.Status.GEPLANT:
            continue
        geaendert = False
        for seite in ("a", "b"):
            platzhalter = getattr(spiel, f"platzhalter_{seite}")
            team = aufloesen(platzhalter) if platzhalter else None
            if team and getattr(spiel, f"team_{seite}_id") != team.pk:
                setattr(spiel, f"team_{seite}", team)
                geaendert = True
        if geaendert:
            spiel.save(update_fields=["team_a", "team_b"])
            a = spiel.team_a or spiel.platzhalter_a
            b = spiel.team_b or spiel.platzhalter_b
            meldungen.append(f"{spiel.titel}: {a} – {b}")

    if meldungen:
        for name in sorted(genutzte_gruppen):
            gleich = [z.team.name for z in fertig[name][:3] if z.gleichstand]
            if gleich:
                meldungen.append(
                    f"Achtung, Gruppe {name}: Gleichstand zwischen {', '.join(gleich)} – auch der direkte "
                    "Vergleich entscheidet nicht, die Reihenfolge ist nur alphabetisch. Bitte prüfen."
                )
    return meldungen
