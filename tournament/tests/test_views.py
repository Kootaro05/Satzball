from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournament.models import Spieler, Team, Turnier


def turnier(**kwargs):
    werte = dict(
        name="Herbst-Cup 2026", oeffentlich=True, datum=timezone.localdate() + timedelta(days=30), ort="Campus-Halle",
        meldeschluss=timezone.now() + timedelta(days=10), max_teams=10,
        min_spieler=2, max_spieler=4, anmeldung_offen=True, startgebuehr_eur=20,
    )
    werte.update(kwargs)
    return Turnier.objects.create(**werte)


def anmeldedaten(teamname="Bit Blockers", spieler=(("Lena", "Hoffmann"), ("Max", "Meier")), extra_zeilen=2):
    daten = {
        "name": teamname, "kapitaen_name": "Lena Hoffmann", "kapitaen_email": "lena@example.de",
        "datenschutz": "on",
    }
    zeilen = list(spieler) + [("", "")] * extra_zeilen
    daten.update({
        "spieler-TOTAL_FORMS": str(len(zeilen)), "spieler-INITIAL_FORMS": "0",
        "spieler-MIN_NUM_FORMS": "0", "spieler-MAX_NUM_FORMS": "1000",
    })
    for i, (vorname, nachname) in enumerate(zeilen):
        daten[f"spieler-{i}-vorname"] = vorname
        daten[f"spieler-{i}-nachname"] = nachname
    return daten


class OeffentlicheSeitenTests(TestCase):
    def test_startseite_ohne_turnier(self):
        r = self.client.get(reverse("startseite"))
        self.assertContains(r, "kein Turnier geplant")

    def test_startseite_und_teamliste_zeigen_teams_und_spieler(self):
        t = turnier()
        tm = Team.objects.create(turnier=t, name="Bit Blockers", kapitaen_name="L", kapitaen_email="l@example.de")
        Spieler.objects.create(team=tm, vorname="Lena", nachname="Hoffmann")
        Team.objects.create(turnier=t, name="Abgesagt FC", kapitaen_name="X", kapitaen_email="x@example.de",
                            status=Team.Status.ABGESAGT)

        r = self.client.get(reverse("startseite"))
        self.assertContains(r, "Herbst-Cup 2026")
        self.assertContains(r, "<b>9</b> von 10 Plätzen frei")
        self.assertContains(r, "Bit Blockers")

        r = self.client.get(reverse("teamliste"))
        self.assertContains(r, "Lena Hoffmann")  # Spielernamen sind öffentlich
        self.assertNotContains(r, "Abgesagt FC")
        self.assertNotContains(r, "l@example.de")  # E-Mail nicht


class AnmeldungTests(TestCase):
    def setUp(self):
        self.t = turnier()

    def test_anmeldung_legt_team_und_spieler_an_und_schickt_link(self):
        r = self.client.post(reverse("anmelden"), anmeldedaten())
        team = Team.objects.get()
        self.assertRedirects(r, reverse("team_angemeldet", args=[team.edit_token]))
        self.assertEqual(team.status, Team.Status.ANGEMELDET)
        self.assertEqual(sorted(team.spieler.values_list("vorname", flat=True)), ["Lena", "Max"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["lena@example.de"])
        self.assertIn(reverse("team_bearbeiten", args=[team.edit_token]), mail.outbox[0].body)

    def test_bestaetigungsseite(self):
        self.client.post(reverse("anmelden"), anmeldedaten())
        team = Team.objects.get()
        r = self.client.get(reverse("team_angemeldet", args=[team.edit_token]))
        self.assertContains(r, "sind dabei!")
        self.assertContains(r, "Platz 1 von 10")

    def test_volles_turnier_fuehrt_auf_warteliste(self):
        self.t.max_teams = 1
        self.t.save()
        self.client.post(reverse("anmelden"), anmeldedaten("Erstes Team"))
        self.client.post(reverse("anmelden"), anmeldedaten("Zweites Team"))
        self.assertEqual(Team.objects.get(name="Zweites Team").status, Team.Status.WARTELISTE)

    def test_zu_wenige_spieler(self):
        r = self.client.post(reverse("anmelden"), anmeldedaten(spieler=[("Lena", "Hoffmann")]))
        self.assertContains(r, "Mindestens 2 Spieler")
        self.assertFalse(Team.objects.exists())

    def test_weniger_als_empfohlen_ist_erlaubt(self):
        self.t.min_spieler = 4  # Empfehlung, keine Pflicht
        self.t.save()
        r = self.client.post(reverse("anmelden"), anmeldedaten())  # 2 Spieler
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Team.objects.get().spieler.count(), 2)
        r = self.client.get(reverse("anmelden"))
        self.assertContains(r, 'data-pflicht="2" data-empfohlen="4"')

    def test_zu_viele_spieler(self):
        spieler = [(f"S{i}", "X") for i in range(5)]
        r = self.client.post(reverse("anmelden"), anmeldedaten(spieler=spieler))
        self.assertContains(r, "Höchstens 4 Spieler")
        self.assertFalse(Team.objects.exists())

    def test_datenschutz_muss_bestaetigt_werden(self):
        daten = anmeldedaten()
        del daten["datenschutz"]
        r = self.client.post(reverse("anmelden"), daten)
        self.assertContains(r, "Datenschutzhinweise")
        self.assertFalse(Team.objects.exists())

    def test_teamname_doppelt(self):
        self.client.post(reverse("anmelden"), anmeldedaten())
        r = self.client.post(reverse("anmelden"), anmeldedaten("bit blockers"))
        self.assertContains(r, "Diesen Teamnamen gibt es schon")
        self.assertEqual(Team.objects.count(), 1)

    def test_anmeldung_geschlossen_nach_meldeschluss(self):
        self.t.meldeschluss = timezone.now() - timedelta(minutes=1)
        self.t.save()
        r = self.client.post(reverse("anmelden"), anmeldedaten())
        self.assertContains(r, "Anmeldung geschlossen")
        self.assertFalse(Team.objects.exists())

    def test_anmeldung_geschlossen_wenn_nicht_offen(self):
        self.t.anmeldung_offen = False
        self.t.save()
        self.assertContains(self.client.get(reverse("anmelden")), "Anmeldung geschlossen")


class TeamBearbeitenTests(TestCase):
    def setUp(self):
        self.t = turnier()
        self.team = Team.objects.create(turnier=self.t, name="Bit Blockers", kapitaen_name="L",
                                        kapitaen_email="l@example.de")
        self.lena = Spieler.objects.create(team=self.team, vorname="Lena", nachname="Hoffmann")
        self.max = Spieler.objects.create(team=self.team, vorname="Max", nachname="Meier")
        self.url = reverse("team_bearbeiten", args=[self.team.edit_token])

    def daten(self, zeilen):
        """zeilen: Liste von (id oder "", vorname, nachname, loeschen)"""
        d = {"spieler-TOTAL_FORMS": str(len(zeilen)), "spieler-INITIAL_FORMS": "2",
             "spieler-MIN_NUM_FORMS": "0", "spieler-MAX_NUM_FORMS": "1000"}
        for i, (pk, vorname, nachname, loeschen) in enumerate(zeilen):
            d.update({f"spieler-{i}-id": pk, f"spieler-{i}-vorname": vorname, f"spieler-{i}-nachname": nachname})
            if loeschen:
                d[f"spieler-{i}-DELETE"] = "on"
        return d

    def test_falscher_token_gibt_404(self):
        self.assertEqual(self.client.get(reverse("team_bearbeiten", args=["falsch"])).status_code, 404)

    def test_seite_zeigt_team_und_zahlungsstatus(self):
        r = self.client.get(self.url)
        self.assertContains(r, "Bit Blockers")
        self.assertContains(r, "20 € offen")

    def test_spieler_aendern_hinzufuegen_entfernen(self):
        r = self.client.post(self.url, self.daten([
            (self.lena.pk, "Lena", "Hoffmann-Schulz", False),
            (self.max.pk, "Max", "Meier", True),
            ("", "Kim", "Nguyen", False),
        ]))
        self.assertRedirects(r, self.url)
        namen = sorted(self.team.spieler.values_list("nachname", flat=True))
        self.assertEqual(namen, ["Hoffmann-Schulz", "Nguyen"])

    def test_mindestanzahl_gilt_auch_beim_bearbeiten(self):
        r = self.client.post(self.url, self.daten([
            (self.lena.pk, "Lena", "Hoffmann", False),
            (self.max.pk, "Max", "Meier", True),
        ]))
        self.assertContains(r, "Mindestens 2 Spieler")
        self.assertEqual(self.team.spieler.count(), 2)

    def test_nach_meldeschluss_keine_aenderung(self):
        self.t.meldeschluss = timezone.now() - timedelta(minutes=1)
        self.t.save()
        r = self.client.post(self.url, self.daten([
            (self.lena.pk, "Geändert", "Hoffmann", False),
            (self.max.pk, "Max", "Meier", False),
        ]))
        self.assertContains(r, "Meldeschluss ist vorbei")
        self.lena.refresh_from_db()
        self.assertEqual(self.lena.vorname, "Lena")

    def test_team_abmelden(self):
        r = self.client.post(reverse("team_abmelden", args=[self.team.edit_token]))
        self.assertRedirects(r, self.url)
        self.team.refresh_from_db()
        self.assertEqual(self.team.status, Team.Status.ABGESAGT)

    def test_abmelden_nur_per_post(self):
        r = self.client.get(reverse("team_abmelden", args=[self.team.edit_token]))
        self.assertEqual(r.status_code, 405)
