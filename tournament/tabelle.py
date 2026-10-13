"""Tabellenberechnung. Die Tabelle wird nie gespeichert, sondern aus beendeten Gruppenspielen berechnet.

Satz-Modus:   Siege, Satzdifferenz, Ballpunktdifferenz, direkter Vergleich
Punkte-Modus: Siege, Punktdifferenz, erzielte Punkte, direkter Vergleich
"""

from dataclasses import dataclass
from itertools import groupby

from .models import Spiel, Turnier


@dataclass
class Zeile:
    team: object
    sp: int = 0
    s: int = 0
    n: int = 0
    saetze_plus: int = 0
    saetze_minus: int = 0
    punkte_plus: int = 0
    punkte_minus: int = 0
    platz: int = 0
    gleichstand: bool = False  # auch der direkte Vergleich trennt nicht; Reihenfolge nur nach Name

    @property
    def sd(self):
        return self.saetze_plus - self.saetze_minus

    @property
    def pd(self):
        return self.punkte_plus - self.punkte_minus


def _eintragen(zeilen, spiel, satz_modus):
    a, b = zeilen[spiel.team_a], zeilen[spiel.team_b]
    pa, pb = spiel.punkte_a or 0, spiel.punkte_b or 0
    if satz_modus:
        sa, sb = spiel.saetze_a or 0, spiel.saetze_b or 0
        a.saetze_plus += sa; a.saetze_minus += sb
        b.saetze_plus += sb; b.saetze_minus += sa
        a_gewinnt = sa > sb
    else:
        a_gewinnt = pa > pb
    a.punkte_plus += pa; a.punkte_minus += pb
    b.punkte_plus += pb; b.punkte_minus += pa
    a.sp += 1; b.sp += 1
    sieger, verlierer = (a, b) if a_gewinnt else (b, a)
    sieger.s += 1
    verlierer.n += 1


def _schluessel(zeile, satz_modus):
    return (zeile.s, zeile.sd, zeile.pd) if satz_modus else (zeile.s, zeile.pd, zeile.punkte_plus)


def _direkter_vergleich(zeilen, spiele, satz_modus):
    """Gleichstand auflösen: Wertung nur aus den Spielen der punktgleichen Teams untereinander."""
    teams = {z.team for z in zeilen}
    mini = {t: Zeile(t) for t in teams}
    for spiel in spiele:
        if spiel.team_a in teams and spiel.team_b in teams:
            _eintragen(mini, spiel, satz_modus)
    sortiert = sorted(zeilen, key=lambda z: (*(-k for k in _schluessel(mini[z.team], satz_modus)), str(z.team)))
    for vorher, nachher in zip(sortiert, sortiert[1:]):
        if _schluessel(mini[vorher.team], satz_modus) == _schluessel(mini[nachher.team], satz_modus):
            vorher.gleichstand = nachher.gleichstand = True
    return sortiert


def berechnen(teams, spiele, zaehlmodus):
    """Tabelle für `teams` aus `spiele`. Gezählt werden nur beendete Gruppenspiele zwischen diesen Teams."""
    satz_modus = zaehlmodus == Turnier.Zaehlmodus.SAETZE
    zeilen = {t: Zeile(t) for t in teams}
    gewertet = [
        s for s in spiele
        if s.status == Spiel.Status.BEENDET and s.phase == Spiel.Phase.GRUPPE
        and s.team_a in zeilen and s.team_b in zeilen
    ]
    for spiel in gewertet:
        _eintragen(zeilen, spiel, satz_modus)

    vorsortiert = sorted(zeilen.values(), key=lambda z: (*(-k for k in _schluessel(z, satz_modus)), str(z.team)))
    tabelle = []
    for _, gleich in groupby(vorsortiert, key=lambda z: _schluessel(z, satz_modus)):
        gleich = list(gleich)
        tabelle += _direkter_vergleich(gleich, gewertet, satz_modus) if len(gleich) > 1 else gleich
    for platz, zeile in enumerate(tabelle, start=1):
        zeile.platz = platz
    return tabelle


def gruppentabellen(turnier):
    """[(gruppe, tabelle)] für alle Gruppen eines Turniers."""
    spiele = list(turnier.spiele.select_related("team_a", "team_b"))
    return [
        (gruppe, berechnen(list(gruppe.teams.all()), [s for s in spiele if s.gruppe_id == gruppe.pk],
                           turnier.zaehlmodus))
        for gruppe in turnier.gruppen.order_by("name")
    ]
