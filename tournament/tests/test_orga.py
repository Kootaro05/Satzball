from datetime import date, datetime, time, timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tournament import spielplan
from tournament.models import Spiel, Team, Turnier


class OrgaSeitenTests(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Cup", datum=date(2026, 11, 14), beginn=time(9, 30), ort="Halle", max_teams=10,
            meldeschluss=datetime(2026, 10, 31, tzinfo=timezone.utc), modus=Turnier.Modus.GRUPPEN_KO,
        )
        for i in range(6):
            Team.objects.create(turnier=self.t, name=f"Team {i}", kapitaen_name="K", kapitaen_email="k@example.de",
                                status=Team.Status.BESTAETIGT, bezahlt=True)
        self.url = f"{reverse('orga_spielplan')}?turnier={self.t.pk}"
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))

    def test_nur_fuer_orga(self):
        self.client.logout()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r.url)

    def test_spielplan_erzeugen_und_anzeigen(self):
        r = self.client.post(self.url, {
            "aktion": "erzeugen", "turnier": self.t.pk, "modus": "gruppen_ko",
            "anzahl_gruppen": "2", "beginn": "10:00", "slot_minuten": "15",
        })
        self.assertRedirects(r, self.url)
        self.t.refresh_from_db()
        self.assertEqual((self.t.beginn, self.t.slot_minuten), (time(10, 0), 15))
        self.assertEqual(self.t.spiele.filter(phase=Spiel.Phase.GRUPPE).count(), 6)

        r = self.client.get(self.url)
        self.assertContains(r, "Halbfinale 2")
        self.assertContains(r, "1. Gruppe B")
        self.assertContains(r, "Schiri:")
        self.assertEqual(r.context["konflikte"], [])

    def test_gruppenwahl_nur_bei_gruppen_ko(self):
        r = self.client.get(self.url)  # Turnier steht auf Gruppen + K.-o.
        self.assertContains(r, '<div class="stapel" data-nur-gruppen>', html=False)
        self.assertContains(r, "<span data-schritt-zeiten>3</span> · Zeiten", html=False)
        self.t.modus = Turnier.Modus.JEDER_GEGEN_JEDEN
        self.t.save()
        r = self.client.get(self.url)
        self.assertContains(r, '<div class="stapel" data-nur-gruppen hidden>', html=False)
        self.assertContains(r, "<span data-schritt-zeiten>2</span> · Zeiten", html=False)

    def test_punkte_modus_ohne_zielpunktzahl(self):
        self.t.zaehlmodus = Turnier.Zaehlmodus.PUNKTE
        self.t.save()
        spielplan.erzeugen(self.t)
        spiel = self.t.spiele.filter(phase=Spiel.Phase.GRUPPE).first()
        r = self.client.get(reverse("orga_ergebnis", args=[spiel.pk]))
        self.assertContains(r, "das Team mit mehr Punkten gewinnt")
        self.assertNotContains(r, "Satz bis")

    def test_fehler_wird_angezeigt(self):
        r = self.client.post(self.url, {
            "aktion": "erzeugen", "turnier": self.t.pk, "modus": "gruppen_ko",
            "anzahl_gruppen": "3", "beginn": "10:00", "slot_minuten": "20",
        }, follow=True)
        self.assertContains(r, "mindestens 9")

    def test_tauschen_und_veroeffentlichen(self):
        spielplan.erzeugen(self.t)
        a, b = self.t.spiele.order_by("uhrzeit", "feld")[:2]
        self.client.post(self.url, {"aktion": "verschieben", "turnier": self.t.pk, "spiel": a.pk, "ziel_spiel": b.pk})
        a.refresh_from_db()
        self.assertEqual(a.feld, 2)

        self.client.post(self.url, {"aktion": "verschieben", "turnier": self.t.pk, "spiel": a.pk,
                                    "ziel_zeit": "15:00", "ziel_feld": "1"})
        a.refresh_from_db()
        self.assertEqual((a.uhrzeit, a.feld), (time(15, 0), 1))

        self.client.post(self.url, {"aktion": "veroeffentlichen", "turnier": self.t.pk})
        self.t.refresh_from_db()
        self.assertTrue(self.t.spielplan_veroeffentlicht)

    def test_ergebnis_eintragen_satz_modus(self):
        spielplan.erzeugen(self.t)
        spiel = self.t.spiele.filter(phase=Spiel.Phase.GRUPPE).order_by("uhrzeit", "feld").first()
        url = reverse("orga_ergebnis", args=[spiel.pk])
        self.assertContains(self.client.get(url), "Spiel beenden")

        r = self.client.post(url, {"saetze_a": "2", "saetze_b": "2"})
        self.assertContains(r, "Genau ein Team muss 2 Sätze gewinnen")
        spiel.refresh_from_db()
        self.assertEqual(spiel.status, Spiel.Status.GEPLANT)

        r = self.client.post(url, {"saetze_a": "1", "saetze_b": "2", "punkte_a": "60", "punkte_b": "65"}, follow=True)
        self.assertContains(r, f"Sieger: {spiel.team_b}")
        spiel.refresh_from_db()
        self.assertEqual((spiel.status, spiel.saetze_b, spiel.punkte_b), (Spiel.Status.BEENDET, 2, 65))
        self.assertContains(self.client.get(self.url), "✓ 1 : 2")

    def test_ergebnis_eintragen_punkte_modus(self):
        self.t.zaehlmodus = Turnier.Zaehlmodus.PUNKTE
        self.t.save()
        spielplan.erzeugen(self.t)
        spiel = self.t.spiele.filter(phase=Spiel.Phase.GRUPPE).first()
        url = reverse("orga_ergebnis", args=[spiel.pk])
        r = self.client.get(url)
        self.assertContains(r, 'name="punkte_a"')
        self.assertNotContains(r, 'name="saetze_a"')
        self.client.post(url, {"punkte_a": "25", "punkte_b": "21"})
        spiel.refresh_from_db()
        self.assertEqual((spiel.status, spiel.punkte_a), (Spiel.Status.BEENDET, 25))

    def test_ko_spiel_ohne_teams(self):
        spielplan.erzeugen(self.t)
        finale = self.t.spiele.get(phase=Spiel.Phase.FINALE)
        self.assertContains(self.client.get(reverse("orga_ergebnis", args=[finale.pk])), "Teams stehen noch nicht fest")
