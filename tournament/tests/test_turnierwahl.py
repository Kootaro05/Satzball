from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournament.models import Team, Turnier


class TurnierwahlTests(TestCase):
    def setUp(self):
        heute = timezone.localdate()
        self.aktuell = Turnier.objects.create(
            name="Herbst-Cup", oeffentlich=True, datum=heute + timedelta(days=10), ort="Halle", max_teams=8,
            meldeschluss=timezone.now() + timedelta(days=5), anmeldung_offen=True, min_spieler=2,
        )
        self.alt = Turnier.objects.create(
            name="Frühjahrs-Cup", oeffentlich=True, datum=heute - timedelta(days=150), ort="Halle", max_teams=8,
            meldeschluss=timezone.now() - timedelta(days=160),
        )
        Team.objects.create(turnier=self.alt, name="Altes Team", kapitaen_name="K", kapitaen_email="k@example.de")

    def test_ohne_wahl_das_aktuelle(self):
        r = self.client.get(reverse("startseite"))
        self.assertEqual(r.context["turnier"], self.aktuell)
        self.assertNotContains(r, "Zum aktuellen Turnier")
        self.assertContains(r, "Andere Turniere ansehen")

    def test_wahl_wird_gemerkt_und_gilt_auf_allen_seiten(self):
        r = self.client.get(reverse("startseite"), {"turnier": self.alt.pk})
        self.assertEqual(r.context["turnier"], self.alt)
        self.assertContains(r, "Du siehst das vergangene Turnier")
        for name in ["teamliste", "spielplan", "tabelle", "startseite"]:
            self.assertEqual(self.client.get(reverse(name)).context["turnier"], self.alt, name)
        self.assertContains(self.client.get(reverse("teamliste")), "Altes Team")

        r = self.client.get(reverse("startseite"), {"turnier": self.aktuell.pk})  # zurück
        self.assertEqual(r.context["turnier"], self.aktuell)
        self.assertNotContains(self.client.get(reverse("teamliste")), "Altes Team")

    def test_ungueltige_wahl_faellt_auf_aktuelles_zurueck(self):
        for wert in ["999", "abc"]:
            r = self.client.get(reverse("startseite"), {"turnier": wert})
            self.assertEqual(r.context["turnier"], self.aktuell, wert)
        self.client.get(reverse("startseite"), {"turnier": self.alt.pk})
        self.alt.delete()
        self.assertEqual(self.client.get(reverse("startseite")).context["turnier"], self.aktuell)

    def test_anmeldung_fuer_gewaehltes_turnier(self):
        self.client.get(reverse("startseite"), {"turnier": self.alt.pk})
        self.assertContains(self.client.get(reverse("anmelden")), "Anmeldung geschlossen")
        self.client.get(reverse("startseite"), {"turnier": self.aktuell.pk})
        self.assertContains(self.client.get(reverse("anmelden")), "Team anmelden")

    def test_entwurf_ist_unsichtbar(self):
        entwurf = Turnier.objects.create(
            name="Geheimer Entwurf", datum=timezone.localdate() + timedelta(days=3), ort="Halle", max_teams=8,
            meldeschluss=timezone.now() + timedelta(days=1), anmeldung_offen=True,
        )
        # früher als das aktuelle, wäre also ohne das Feld "aktuelles Turnier" geworden
        self.assertEqual(self.client.get(reverse("startseite")).context["turnier"], self.aktuell)
        self.assertNotContains(self.client.get(reverse("turniere")), "Geheimer Entwurf")
        r = self.client.get(reverse("startseite"), {"turnier": entwurf.pk})  # auch nicht per Link
        self.assertEqual(r.context["turnier"], self.aktuell)
        self.assertNotContains(r, "Geheimer Entwurf")
        self.client.get(reverse("startseite"), {"turnier": entwurf.pk})
        self.assertNotContains(self.client.get(reverse("anmelden")), "Geheimer Entwurf")
        # die Orga sieht ihn weiterhin
        self.assertEqual(Turnier.aktuelles(), entwurf)

    def test_ohne_oeffentliche_turniere(self):
        Turnier.objects.update(oeffentlich=False)
        r = self.client.get(reverse("startseite"))
        self.assertIsNone(r.context["turnier"])
        self.assertContains(r, "kein Turnier geplant")

    def test_turnierliste(self):
        r = self.client.get(reverse("turniere"))
        inhalt = r.content.decode()
        self.assertLess(inhalt.index("Herbst-Cup"), inhalt.index("Frühjahrs-Cup"))  # neueste zuerst
        self.assertContains(r, "Aktuell")
        self.assertContains(r, "Vorbei")
        self.assertContains(r, f"?turnier={self.alt.pk}")


class AdminTurnierTests(TestCase):
    def test_satzball_stil_und_zaehlmodus_skript(self):
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))
        r = self.client.get(reverse("admin:tournament_turnier_add"))
        self.assertContains(r, "css/admin.css")
        self.assertContains(r, "js/admin_turnier.js")
        self.assertContains(r, "Satzball – Orga")

    def test_punkte_modus_speichern_behaelt_satzwerte(self):
        self.client.force_login(User.objects.create_superuser("orga2", "o2@example.de", "x"))
        r = self.client.post(reverse("admin:tournament_turnier_add"), {
            "name": "Punkte-Cup", "datum": "2026-11-14", "ort": "Halle", "startgebuehr_eur": "20",
            "meldeschluss_0": "31.10.2026", "meldeschluss_1": "23:59", "max_teams": "10",
            "min_spieler": "6", "max_spieler": "10", "modus": "jeder_gegen_jeden", "anzahl_felder": "2",
            "slot_minuten": "15", "zaehlmodus": "punkte", "gewinnsaetze": "2",
            "punkte_pro_satz": "21", "punkte_entscheidungssatz": "15",
            "gruppen-TOTAL_FORMS": "0", "gruppen-INITIAL_FORMS": "0",
        })
        self.assertEqual(r.status_code, 302, r.content.decode()[:500])
        t = Turnier.objects.get(name="Punkte-Cup")
        self.assertEqual((t.zaehlmodus, t.punkte_pro_satz, t.gewinnsaetze), ("punkte", 21, 2))
