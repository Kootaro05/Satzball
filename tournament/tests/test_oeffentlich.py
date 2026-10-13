from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournament import spielplan
from tournament.models import Spiel, Team, Turnier


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
        # 2 Gruppen à 3: 3 Gruppen-Slots ab 9:30 à 20 min -> K.-o. ab 10:30
        self.assertContains(r, "ab 10:30 · K.-o.-Runde")
        self.assertContains(r, "Platz 1 und 2 jeder Gruppe ziehen ins Halbfinale ein.")
        self.assertContains(r, f'href="{reverse("tabelle")}"')  # Link zur Tabelle
        self.assertNotContains(r, "geheim@example.de")
        self.assertContains(self.client.get(reverse("startseite")), "Spielplan &amp; Ergebnisse")

        r = self.client.get(reverse("tabelle"))
        tabelle_a = r.context["tabellen"][0][1]
        self.assertEqual(sum(z.s for z in tabelle_a), 1)
        self.assertContains(r, "Gruppe B")
        self.assertContains(r, "SD = Satzdifferenz")
        self.assertContains(r, "Platz 1 und 2 jeder Gruppe ziehen ins Halbfinale ein.")
        self.assertNotContains(r, "geheim@example.de")

    def test_tabelle_unveroeffentlicht(self):
        r = self.client.get(reverse("tabelle"))
        self.assertContains(r, "sobald der Spielplan veröffentlicht ist")
        self.assertNotContains(r, "Team 0")

    def test_punkte_modus(self):
        self.t.zaehlmodus = Turnier.Zaehlmodus.PUNKTE
        self.veroeffentlichen()
        spiel = self.t.spiele.filter(phase=Spiel.Phase.GRUPPE).first()
        spiel.status, spiel.punkte_a, spiel.punkte_b = Spiel.Status.BEENDET, 25, 21
        spiel.save()
        r = self.client.get(self.url)
        self.assertContains(r, "ein Satz bis 25")
        self.assertContains(self.client.get(reverse("tabelle")), "PD = Punktdifferenz")
        self.assertContains(r, "Endstand")

    def laeuft(self, jetzt):
        """Uhrzeit des Slots mit "Läuft" (oder None) für einen Zeitpunkt am Spieltag."""
        tz = timezone.get_current_timezone()
        moment = timezone.make_aware(datetime.combine(self.t.datum, jetzt), tz)
        with patch("tournament.views.timezone.now", return_value=moment):
            r = self.client.get(self.url)
        return next((slot["zeit"] for slot in r.context["slots"] if slot["laeuft"]), None)

    def beenden(self, zeit):
        for s in self.t.spiele.filter(uhrzeit=zeit):
            s.status, s.saetze_a, s.saetze_b = Spiel.Status.BEENDET, 2, 0
            s.save()

    def test_laeuft_folgt_dem_echten_stand(self):
        self.veroeffentlichen()
        self.assertIsNone(self.laeuft(time(9, 0)))              # vor dem Start
        self.assertEqual(self.laeuft(time(9, 35)), time(9, 30))
        # Turnier hängt hinterher: um 10:15 ist Slot 1 noch nicht fertig -> Slot 1 läuft
        self.assertEqual(self.laeuft(time(10, 15)), time(9, 30))
        self.beenden(time(9, 30))
        self.assertEqual(self.laeuft(time(10, 15)), time(9, 50))
        # Slot 1 fertig, aber Slot 2 hat noch nicht begonnen -> nichts läuft
        self.assertIsNone(self.laeuft(time(9, 45)))

    def test_laeuft_nur_am_spieltag(self):
        self.veroeffentlichen()
        tz = timezone.get_current_timezone()
        am_tag_davor = timezone.make_aware(datetime.combine(self.t.datum - timedelta(days=1), time(9, 35)), tz)
        with patch("tournament.views.timezone.now", return_value=am_tag_davor):
            r = self.client.get(self.url)
        self.assertFalse(any(slot["laeuft"] for slot in r.context["slots"]))

    def test_navigation_markiert_aktuelle_seite(self):
        for name in ["startseite", "teamliste", "spielplan", "tabelle"]:
            r = self.client.get(reverse(name))
            self.assertContains(r, f'<a href="{reverse(name)}" aria-current="page">', html=False)
            self.assertContains(r, 'aria-current="page"', count=1)
