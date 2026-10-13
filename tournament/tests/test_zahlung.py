from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournament.models import Team, Turnier


class UnbezahltNachMeldeschlussTests(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Cup", oeffentlich=True, datum=timezone.localdate() + timedelta(days=20), ort="Halle",
            meldeschluss=timezone.now() + timedelta(days=5), max_teams=2, anmeldung_offen=True,
            startgebuehr_eur=20, zahlungsinfo="IBAN DE00 1234",
        )
        self.offen = self.team("Offen")  # Startplatz, nicht bezahlt
        self.bezahlt = self.team("Bezahlt", bezahlt=True)  # bestätigt
        self.wartend = self.team("Wartend", status=Team.Status.WARTELISTE)
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))
        self.liste = reverse("admin:tournament_team_changelist")

    def team(self, name, **kwargs):
        return Team.objects.create(turnier=self.t, name=name, kapitaen_name=f"K {name}",
                                   kapitaen_email=f"{name.lower()}@example.de", **kwargs)

    def kacheln(self):
        return self.client.get(self.liste, {"turnier__id__exact": self.t.pk})

    def meldeschluss_vorbei(self):
        self.t.meldeschluss = timezone.now() - timedelta(hours=1)
        self.t.save()

    def zurueckstufen(self):
        return self.client.post(reverse("admin:tournament_team_unbezahlte_auf_warteliste", args=[self.t.pk]), follow=True)

    def test_erinnerung_vor_dem_meldeschluss(self):
        r = self.kacheln()
        self.assertContains(r, "Erinnerung an 1 Team schicken")
        self.assertContains(r, "Noch nicht erinnert")
        self.assertNotContains(r, "auf die Warteliste setzen")

        r = self.client.post(reverse("admin:tournament_team_an_zahlung_erinnern", args=[self.t.pk]), follow=True)
        self.assertContains(r, "Erinnerung an 1 Team(s) verschickt")
        self.assertEqual([m.to for m in mail.outbox], [["offen@example.de"]])  # nicht Bezahlt, nicht Wartend
        self.assertIn("IBAN DE00 1234", mail.outbox[0].body)
        self.assertIn(reverse("team_bearbeiten", args=[self.offen.edit_token]), mail.outbox[0].body)
        self.assertContains(r, "Zuletzt erinnert")

    def test_nach_dem_meldeschluss_ans_ende_der_warteliste(self):
        self.meldeschluss_vorbei()
        r = self.kacheln()
        self.assertContains(r, "1 auf die Warteliste setzen")
        self.assertNotContains(r, "Erinnerung an")

        r = self.zurueckstufen()
        self.assertContains(r, "1 unbezahlte(s) Team(s) ans Ende der Warteliste gesetzt")
        self.offen.refresh_from_db()
        self.wartend.refresh_from_db()
        self.assertEqual(self.offen.status, Team.Status.WARTELISTE)
        self.assertEqual((self.wartend.wartelisten_platz, self.offen.wartelisten_platz), (1, 2))  # ans Ende
        self.assertIn("ursprünglich angemeldet", self.offen.notiz)
        [m] = mail.outbox
        self.assertEqual(m.to, ["offen@example.de"])
        self.assertIn("Platz 2 der Warteliste", m.body)
        self.assertContains(r, "Nachrücken: Wartend")  # Haken aus: Orga holt den Ersten per Knopf

    def test_mit_haken_rueckt_der_erste_wartende_sofort_nach(self):
        self.meldeschluss_vorbei()
        self.t.warteliste_automatisch = True
        self.t.save()
        self.zurueckstufen()
        self.wartend.refresh_from_db()
        self.offen.refresh_from_db()
        self.assertEqual(self.wartend.status, Team.Status.ANGEMELDET)
        self.assertEqual(self.offen.status, Team.Status.WARTELISTE)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["offen@example.de", "wartend@example.de"])

    def test_zurueckgestufte_kommen_nicht_sofort_zurueck(self):
        # niemand sonst wartet: der frei gewordene Platz bleibt frei, statt das Team gleich zurückzuholen
        self.wartend.delete()
        self.meldeschluss_vorbei()
        self.t.warteliste_automatisch = True
        self.t.save()
        self.zurueckstufen()
        self.offen.refresh_from_db()
        self.assertEqual(self.offen.status, Team.Status.WARTELISTE)
        self.assertEqual(len(mail.outbox), 1)

    def test_vor_dem_meldeschluss_nicht_moeglich(self):
        r = self.zurueckstufen()
        self.assertContains(r, "Erst nach dem Meldeschluss möglich")
        self.offen.refresh_from_db()
        self.assertEqual(self.offen.status, Team.Status.ANGEMELDET)

    def test_knoepfe_nur_mit_login_und_post(self):
        self.client.logout()
        r = self.client.post(reverse("admin:tournament_team_an_zahlung_erinnern", args=[self.t.pk]))
        self.assertIn("/admin/login/", r.url)
        self.client.force_login(User.objects.get(username="orga"))
        self.client.get(reverse("admin:tournament_team_an_zahlung_erinnern", args=[self.t.pk]))
        self.assertEqual(len(mail.outbox), 0)
