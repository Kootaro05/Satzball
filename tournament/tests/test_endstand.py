import random
from datetime import date, datetime, time, timezone

from django.test import TestCase
from django.urls import reverse

from tournament import ko, spielplan
from tournament.models import Spiel, Team, Turnier
from tournament.tabelle import endstand

Phase = Spiel.Phase


class EndstandTests(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Cup", datum=date(2026, 11, 14), beginn=time(9, 0), ort="Halle", max_teams=20,
            meldeschluss=datetime(2026, 10, 31, tzinfo=timezone.utc), modus=Turnier.Modus.GRUPPEN_KO,
            oeffentlich=True,
        )

    def plan(self, anzahl_teams):
        for i in range(anzahl_teams):
            Team.objects.create(turnier=self.t, name=f"Team {i:02d}", kapitaen_name="K", kapitaen_email="k@example.de",
                                status=Team.Status.BESTAETIGT, bezahlt=True)
        spielplan.erzeugen(self.t, zufall=random.Random(5))
        self.t.spielplan_veroeffentlicht = True  # erzeugen() zieht die Veröffentlichung zurück
        self.t.save()

    def beenden(self, spiel, sieger=None):
        """Beendet das Spiel; ohne `sieger` gewinnt das Team mit der kleineren ID."""
        spiel.refresh_from_db()
        sieger = sieger or min((spiel.team_a, spiel.team_b), key=lambda t: t.pk)
        spiel.status = Spiel.Status.BEENDET
        spiel.saetze_a, spiel.saetze_b = (2, 0) if sieger == spiel.team_a else (0, 2)
        spiel.save()
        ko.aktualisieren(self.t)

    def alle_beenden(self, phase, sieger=None):
        for s in self.t.spiele.filter(phase=phase, status=Spiel.Status.GEPLANT).order_by("pk"):
            self.beenden(s, sieger=sieger(s) if sieger else None)

    def startseite(self):
        return self.client.get(reverse("startseite"))

    def test_gruppen_ko_nach_finale_und_spiel_um_platz_3(self):
        self.plan(8)
        self.alle_beenden(Phase.GRUPPE)
        self.alle_beenden(Phase.HALBFINALE)
        self.assertEqual(endstand(self.t), [])
        self.assertNotContains(self.startseite(), "Endstand")

        finale = self.t.spiele.get(phase=Phase.FINALE)
        self.beenden(finale, sieger=finale.team_b)  # der Außenseiter gewinnt
        finale.refresh_from_db()
        self.assertEqual(endstand(self.t), [(1, finale.team_b), (2, finale.team_a)])  # Platz 3 noch offen

        platz_3 = self.t.spiele.get(phase=Phase.PLATZ_3)
        self.beenden(platz_3)
        platz_3.refresh_from_db()
        self.assertEqual(endstand(self.t), [(1, finale.team_b), (2, finale.team_a), (3, platz_3.sieger)])
        r = self.startseite()
        self.assertContains(r, "Endstand")
        self.assertContains(r, f"1. {finale.team_b.name}")
        self.assertContains(r, f"3. {platz_3.sieger.name}")

    def test_geloeschtes_team_faellt_raus(self):
        self.plan(8)
        for phase in (Phase.GRUPPE, Phase.HALBFINALE, Phase.PLATZ_3, Phase.FINALE):
            self.alle_beenden(phase)
        finale = self.t.spiele.get(phase=Phase.FINALE)
        zweiter = finale.team_b if finale.sieger == finale.team_a else finale.team_a
        zweiter.delete()
        self.assertEqual([platz for platz, _ in endstand(self.t)], [1, 3])
        self.assertNotContains(self.startseite(), "2. <")

    def test_jeder_gegen_jeden_erst_wenn_alle_spiele_beendet_sind(self):
        self.t.modus = Turnier.Modus.JEDER_GEGEN_JEDEN
        self.t.save()
        self.plan(5)
        offen = list(self.t.spiele.order_by("pk"))
        for s in offen[:-1]:
            self.beenden(s)
        self.assertEqual(endstand(self.t), [])
        self.beenden(offen[-1])
        teams = list(self.t.teams.order_by("pk"))  # das Team mit der kleineren ID gewinnt immer
        self.assertEqual(endstand(self.t), [(1, teams[0]), (2, teams[1]), (3, teams[2])])

    def test_jeder_gegen_jeden_gleichstand_teilt_den_platz(self):
        self.t.modus = Turnier.Modus.JEDER_GEGEN_JEDEN
        self.t.save()
        self.plan(3)
        x, y, z = self.t.teams.order_by("pk")
        ring = {frozenset((x, y)): x, frozenset((y, z)): y, frozenset((x, z)): z}
        self.alle_beenden(Phase.GRUPPE, sieger=lambda s: ring[frozenset((s.team_a, s.team_b))])
        self.assertEqual([platz for platz, _ in endstand(self.t)], [1, 1, 1])

    def test_nicht_ohne_veroeffentlichten_spielplan(self):
        self.plan(8)
        for phase in (Phase.GRUPPE, Phase.HALBFINALE, Phase.PLATZ_3, Phase.FINALE):
            self.alle_beenden(phase)
        self.assertContains(self.startseite(), "Endstand")
        self.t.spielplan_veroeffentlicht = False
        self.t.save()
        self.assertNotContains(self.startseite(), "Endstand")
