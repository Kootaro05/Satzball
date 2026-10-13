from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournament.models import Team, Turnier


class TeamAdminZahlungTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("orga", "orga@example.de", "x"))
        self.t = Turnier.objects.create(
            name="Herbst-Cup", datum=timezone.localdate() + timedelta(days=30), ort="Halle",
            meldeschluss=timezone.now() + timedelta(days=10), max_teams=3, startgebuehr_eur=20,
        )
        self.offen = self.team("Offen")
        self.bezahlt = self.team("Bezahlt", bezahlt=True)
        self.warte = self.team("Warte", status=Team.Status.WARTELISTE)
        self.team("Abgesagt", status=Team.Status.ABGESAGT)
        self.url = reverse("admin:tournament_team_changelist")

    def team(self, name, **kwargs):
        return Team.objects.create(turnier=self.t, name=name, kapitaen_name="K",
                                   kapitaen_email="k@example.de", **kwargs)

    def test_zahlungsuebersicht(self):
        self.assertEqual(self.t.zahlungsuebersicht(), {
            "eingegangen": 20, "erwartet": 40, "unbezahlt": 1, "warteliste": 1,
        })

    def test_liste_zeigt_kennzahlen(self):
        r = self.client.get(self.url)
        self.assertContains(r, "20 €</strong>von 40 € erwartet", html=False)
        self.assertEqual(r.context["uebersicht"]["unbezahlt"], 1)

    def test_filter_unbezahlt_nur_teams_mit_startplatz(self):
        r = self.client.get(self.url, {"zahlung": "unbezahlt"})
        self.assertEqual([t.name for t in r.context["cl"].result_list], ["Offen"])

    def test_haken_in_der_liste_bestaetigt_team(self):
        teams = list(Team.objects.order_by("turnier", "name"))
        daten = {
            "form-TOTAL_FORMS": str(len(teams)), "form-INITIAL_FORMS": str(len(teams)),
            "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000", "_save": "Sichern",
        }
        for i, t in enumerate(teams):
            daten[f"form-{i}-id"] = str(t.pk)
            daten[f"form-{i}-zahlungsart"] = "bar" if t == self.offen else t.zahlungsart
            if t.bezahlt or t == self.offen:
                daten[f"form-{i}-bezahlt"] = "on"
        r = self.client.post(self.url, daten)
        self.assertEqual(r.status_code, 302)
        self.offen.refresh_from_db()
        self.assertTrue(self.offen.bezahlt)
        self.assertEqual(self.offen.status, Team.Status.BESTAETIGT)
        self.assertEqual(self.offen.zahlungsart, "bar")
        self.assertEqual(self.offen.bezahlt_am, timezone.localdate())

    def test_bezahlt_zuruecknehmen_loescht_datum(self):
        self.bezahlt.bezahlt = False
        self.bezahlt.save()
        self.assertIsNone(self.bezahlt.bezahlt_am)

    def nachruecken(self, *teams):
        return self.client.post(self.url, {
            "action": "nachruecken", "_selected_action": [t.pk for t in teams],
        }, follow=True)

    def test_nachruecken_von_der_warteliste(self):
        r = self.nachruecken(self.warte, self.offen)
        self.warte.refresh_from_db()
        self.offen.refresh_from_db()
        self.assertEqual(self.warte.status, Team.Status.ANGEMELDET)
        self.assertEqual(self.offen.status, Team.Status.ANGEMELDET)  # unverändert
        self.assertContains(r, "1 Team(s) von der Warteliste nachgerückt")
        self.assertNotContains(r, "mehr Teams mit Startplatz")

    def test_nachruecken_warnt_wenn_turnier_voll(self):
        self.team("Dritter")  # jetzt 3 von 3 Plätzen belegt
        r = self.nachruecken(self.warte)
        self.assertContains(r, "mehr Teams mit Startplatz als max. Teams")
