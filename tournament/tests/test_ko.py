import random
from datetime import date, datetime, time, timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tournament import ko, spielplan
from tournament.models import Spiel, Team, Turnier

Phase = Spiel.Phase


class KoBefuellenTests(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Cup", datum=date(2026, 11, 14), beginn=time(9, 0), ort="Halle", max_teams=20,
            meldeschluss=datetime(2026, 10, 31, tzinfo=timezone.utc), modus=Turnier.Modus.GRUPPEN_KO,
        )

    def plan(self, anzahl_teams, gruppen=None):
        for i in range(anzahl_teams):
            Team.objects.create(turnier=self.t, name=f"Team {i:02d}", kapitaen_name="K", kapitaen_email="k@example.de",
                                status=Team.Status.BESTAETIGT, bezahlt=True)
        spielplan.erzeugen(self.t, anzahl_gruppen=gruppen, zufall=random.Random(5))

    def rangfolge(self, name):
        """Erwartete Tabelle: In jedem Spiel gewinnt das Team mit der kleineren ID."""
        return list(self.t.gruppen.get(name=name).teams.order_by("pk"))

    def beenden(self, spiel, sieger=None):
        sieger = sieger or min((spiel.team_a, spiel.team_b), key=lambda t: t.pk)
        spiel.status = Spiel.Status.BEENDET
        spiel.saetze_a, spiel.saetze_b = (2, 0) if sieger == spiel.team_a else (0, 2)
        spiel.save()
        return ko.aktualisieren(self.t)

    def gruppe_beenden(self, name):
        meldungen = []
        for s in self.t.spiele.filter(gruppe__name=name, status=Spiel.Status.GEPLANT):
            meldungen += self.beenden(s)
        return meldungen

    def ko(self, phase, nummer=1):
        return [s for s in spielplan.mit_titeln(self.t) if s.phase == phase][nummer - 1]

    def test_zwei_gruppen_halbfinale_dann_finale(self):
        self.plan(8)
        self.assertIsNone(self.ko(Phase.HALBFINALE).team_a)

        self.gruppe_beenden("A")  # nur Gruppe A fertig
        hf1 = self.ko(Phase.HALBFINALE, 1)
        self.assertEqual((hf1.platzhalter_a, hf1.team_a), ("1. Gruppe A", self.rangfolge("A")[0]))
        self.assertIsNone(hf1.team_b)  # "2. Gruppe B" noch offen

        meldungen = self.gruppe_beenden("B")
        a, b = self.rangfolge("A"), self.rangfolge("B")
        hf1, hf2 = self.ko(Phase.HALBFINALE, 1), self.ko(Phase.HALBFINALE, 2)
        self.assertEqual((hf1.team_a, hf1.team_b), (a[0], b[1]))
        self.assertEqual((hf2.team_a, hf2.team_b), (b[0], a[1]))
        self.assertTrue(any(m.startswith("Halbfinale 1:") for m in meldungen))
        self.assertIsNone(self.ko(Phase.FINALE).team_a)

        self.beenden(hf1, sieger=hf1.team_b)
        self.beenden(hf2, sieger=hf2.team_a)
        finale, platz3 = self.ko(Phase.FINALE), self.ko(Phase.PLATZ_3)
        self.assertEqual((finale.team_a, finale.team_b), (b[1], b[0]))
        self.assertEqual((platz3.team_a, platz3.team_b), (a[0], a[1]))

    def test_korrektur_aendert_offene_ko_spiele_aber_nicht_beendete(self):
        self.plan(8)
        self.gruppe_beenden("A")
        self.gruppe_beenden("B")
        a = self.rangfolge("A")
        # Korrektur: Der Zweite aus A hat das direkte Duell gegen den Ersten doch gewonnen
        duell = self.t.spiele.get(gruppe__name="A", team_a__in=a[:2], team_b__in=a[:2])
        self.beenden(duell, sieger=a[1])
        hf1, hf2 = self.ko(Phase.HALBFINALE, 1), self.ko(Phase.HALBFINALE, 2)
        self.assertEqual((hf1.team_a, hf2.team_b), (a[1], a[0]))

        self.beenden(hf1)  # Halbfinale 1 ist gespielt
        self.beenden(duell, sieger=a[0])  # erneute Korrektur
        hf1, hf2 = self.ko(Phase.HALBFINALE, 1), self.ko(Phase.HALBFINALE, 2)
        self.assertEqual(hf1.team_a, a[1])  # beendetes Spiel bleibt
        self.assertEqual(hf2.team_b, a[1])  # offenes Spiel folgt der Tabelle

    def test_drei_gruppen_bester_zweiter_nach_schnitt(self):
        self.plan(11, gruppen=3)  # Gruppen mit 4, 4 und 3 Teams
        for name in "AB":
            self.gruppe_beenden(name)
        hf1 = self.ko(Phase.HALBFINALE, 1)
        self.assertIsNone(hf1.team_b)  # bester Zweiter erst, wenn alle Gruppen fertig sind
        self.gruppe_beenden("C")
        hf1, hf2 = self.ko(Phase.HALBFINALE, 1), self.ko(Phase.HALBFINALE, 2)
        # Zweite: 2 Siege aus 3 Spielen (Vierergruppen) schlägt 1 Sieg aus 2 (Dreiergruppe);
        # bei gleichem Schnitt entscheidet der Name
        zweite = [self.rangfolge(n)[1] for n in "ABC" if self.t.gruppen.get(name=n).teams.count() == 4]
        self.assertEqual(hf1.team_b, min(zweite, key=lambda t: t.name))
        self.assertEqual((hf2.team_a, hf2.team_b), (self.rangfolge("B")[0], self.rangfolge("C")[0]))

    def test_vier_gruppen_viertelfinale_dann_halbfinale(self):
        self.plan(16, gruppen=4)
        for name in "ABCD":
            self.gruppe_beenden(name)
        vf = [self.ko(Phase.VIERTELFINALE, n) for n in range(1, 5)]
        self.assertEqual((vf[0].team_a, vf[0].team_b), (self.rangfolge("A")[0], self.rangfolge("B")[1]))
        self.assertEqual((vf[3].team_a, vf[3].team_b), (self.rangfolge("D")[0], self.rangfolge("C")[1]))
        for spiel in vf:
            self.beenden(spiel, sieger=spiel.team_a)
        hf1 = self.ko(Phase.HALBFINALE, 1)
        self.assertEqual((hf1.team_a, hf1.team_b), (vf[0].team_a, vf[2].team_a))

    def test_gleichstand_wird_gemeldet(self):
        self.plan(6)  # 2 Gruppen à 3
        x, y, z = self.rangfolge("A")
        # Ringschluss: x schlägt y, y schlägt z, z schlägt x – alles gleich, auch im direkten Vergleich
        sieger = {frozenset((x, y)): x, frozenset((y, z)): y, frozenset((x, z)): z}
        meldungen = []
        for s in self.t.spiele.filter(gruppe__name="A"):
            meldungen += self.beenden(s, sieger=sieger[frozenset((s.team_a, s.team_b))])
        self.assertTrue(any("Gleichstand" in m and "Gruppe A" in m for m in meldungen), meldungen)

    def test_jeder_gegen_jeden_hat_keine_ko_runde(self):
        self.t.modus = Turnier.Modus.JEDER_GEGEN_JEDEN
        self.plan(4)
        meldungen = []
        for s in self.t.spiele.all():
            meldungen += self.beenden(s)
        self.assertEqual(meldungen, [])

    def test_meldung_auf_der_ergebnis_seite(self):
        self.plan(6)
        self.gruppe_beenden("A")
        letztes = self.t.spiele.filter(gruppe__name="B").order_by("uhrzeit").last()
        for s in self.t.spiele.filter(gruppe__name="B").exclude(pk=letztes.pk):
            self.beenden(s)
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))
        r = self.client.post(reverse("orga_ergebnis", args=[letztes.pk]), {"saetze_a": "2", "saetze_b": "0"}, follow=True)
        self.assertContains(r, "Halbfinale 1:")
