from datetime import date, datetime, time, timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tournament import spielplan
from tournament.models import Team, Turnier


class DruckansichtTests(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Herbst-Cup", datum=date(2026, 11, 14), beginn=time(9, 30), ort="Campus-Halle", max_teams=8,
            meldeschluss=datetime(2026, 10, 31, tzinfo=timezone.utc), modus=Turnier.Modus.GRUPPEN_KO,
        )
        for i in range(6):
            Team.objects.create(turnier=self.t, name=f"Team {i}", kapitaen_name="K", kapitaen_email="geheim@example.de",
                                status=Team.Status.BESTAETIGT, bezahlt=True)
        spielplan.erzeugen(self.t)
        self.url = f"{reverse('orga_spielplan_druck')}?turnier={self.t.pk}"

    def test_nur_fuer_orga(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r.url)

    def test_inhalt(self):
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))
        r = self.client.get(self.url)
        self.assertContains(r, "Samstag, 14. November 2026")
        self.assertContains(r, "Campus-Halle")
        self.assertContains(r, "9:30")
        self.assertContains(r, "Feld 2")
        self.assertContains(r, "Schiri:")
        self.assertContains(r, "Halbfinale 1")
        self.assertContains(r, "1. Gruppe A")
        self.assertContains(r, "Gruppe A:</b>", html=False)
        self.assertContains(r, "noch nicht veröffentlicht")
        self.assertNotContains(r, "geheim@example.de")
        self.assertNotContains(r, "online:")  # kein öffentlicher Link, solange nicht veröffentlicht

    def test_jeder_gegen_jeden_ohne_gruppenliste(self):
        self.t.modus = Turnier.Modus.JEDER_GEGEN_JEDEN
        self.t.save()
        spielplan.erzeugen(self.t)
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))
        r = self.client.get(self.url)
        self.assertContains(r, "Team 0 –")
        self.assertNotContains(r, "Gruppe A:</b>", html=False)  # alle Teams stehen ohnehin in der Tabelle

    def test_link_auf_den_oeffentlichen_spielplan(self):
        self.t.oeffentlich = self.t.spielplan_veroeffentlicht = True
        self.t.save()
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))
        r = self.client.get(self.url)
        self.assertContains(r, f"/spielplan/?turnier={self.t.pk}")
        self.assertContains(self.client.get(f"{reverse('orga_spielplan')}?turnier={self.t.pk}"), "Druckansicht")
