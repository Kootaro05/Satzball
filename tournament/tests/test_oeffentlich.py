from datetime import datetime, time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournament import spielplan
from tournament.models import Spiel, Team, Turnier
from tournament.views import laeuft


class OeffentlicherSpielplanTests(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Cup", datum=timezone.localdate() + timedelta(days=3), beginn=time(9, 30), ort="Halle",
            max_teams=10, meldeschluss=timezone.now() + timedelta(days=1), modus=Turnier.Modus.GRUPPEN_KO,
        )
        for i in range(6):
            Team.objects.create(turnier=self.t, name=f"Team {i}", kapitaen_name="K", kapitaen_email="geheim@example.de",
                                status=Team.Status.BESTAETIGT, bezahlt=True)
        spielplan.erzeugen(self.t)
        self.url = reverse("spielplan")

    def veroeffentlichen(self):
        self.t.spielplan_veroeffentlicht = True
        self.t.save()

    def test_unveroeffentlicht_nichts_zu_sehen(self):
        r = self.client.get(self.url)
        self.assertContains(r, "wird gerade erstellt")
        self.assertNotContains(r, "Team 0")
        self.assertNotContains(self.client.get(reverse("startseite")), "Spielplan &amp; Ergebnisse")

    def test_veroeffentlicht_mit_ergebnis_und_tabelle(self):
        self.veroeffentlichen()
        spiel = self.t.spiele.filter(phase=Spiel.Phase.GRUPPE).order_by("uhrzeit", "feld").first()
        spiel.status, spiel.saetze_a, spiel.saetze_b, spiel.punkte_a, spiel.punkte_b = Spiel.Status.BEENDET, 2, 1, 63, 60
        spiel.save()

        r = self.client.get(self.url)
        self.assertContains(r, "9:30")
        self.assertContains(r, "Ballpunkte 63:60")
        self.assertContains(r, "noch offen")
        self.assertContains(r, "Halbfinale 1")
        self.assertContains(r, "1. Gruppe A")
        self.assertContains(r, "ab ")  # K.-o.-Hinweis
        self.assertContains(r, "Platz 1 und 2 jeder Gruppe ziehen ins Halbfinale ein.")
        self.assertContains(r, 'id="tabelle"')
        self.assertNotContains(r, "geheim@example.de")
        tabelle_a = r.context["tabellen"][0][1]
        self.assertEqual(sum(z.s for z in tabelle_a), 1)
        self.assertContains(self.client.get(reverse("startseite")), "Spielplan &amp; Ergebnisse")

    def test_punkte_modus(self):
        self.t.zaehlmodus = Turnier.Zaehlmodus.PUNKTE
        self.veroeffentlichen()
        spiel = self.t.spiele.filter(phase=Spiel.Phase.GRUPPE).first()
        spiel.status, spiel.punkte_a, spiel.punkte_b = Spiel.Status.BEENDET, 25, 21
        spiel.save()
        r = self.client.get(self.url)
        self.assertContains(r, "ein Satz bis 25")
        self.assertContains(r, "PD = Punktdifferenz")
        self.assertContains(r, "Endstand")

    def test_laeuft(self):
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.combine(self.t.datum, time(9, 30)), tz)
        self.assertTrue(laeuft(self.t, time(9, 30), start + timedelta(minutes=5)))
        self.assertFalse(laeuft(self.t, time(9, 30), start + timedelta(minutes=20)))
        self.assertFalse(laeuft(self.t, time(9, 30), start - timedelta(days=1)))

    def test_navigation(self):
        r = self.client.get(reverse("startseite"))
        self.assertContains(r, f'href="{self.url}"')
        self.assertContains(r, f'href="{self.url}#tabelle"')
