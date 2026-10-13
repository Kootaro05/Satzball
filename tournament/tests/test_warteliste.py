from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournament import warteliste
from tournament.models import Team, Turnier


class WartelisteTests(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Cup", oeffentlich=True, datum=timezone.localdate() + timedelta(days=20), ort="Halle",
            meldeschluss=timezone.now() + timedelta(days=5), max_teams=1, anmeldung_offen=True,
            startgebuehr_eur=20, min_spieler=2,
        )
        # Anmelde-Reihenfolge absichtlich nicht alphabetisch
        self.zeta = self.team("Zeta")  # bekommt den einzigen Platz
        self.alpha = self.team("Alpha", status=Team.Status.WARTELISTE)
        self.mitte = self.team("Mitte", status=Team.Status.WARTELISTE)

    def team(self, name, **kwargs):
        return Team.objects.create(turnier=self.t, name=name, kapitaen_name=f"Kapitän {name}",
                                   kapitaen_email=f"{name.lower()}@example.de", **kwargs)

    def automatisch(self):
        self.t.warteliste_automatisch = True
        self.t.save()

    def orga(self):
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))

    def admin_team_speichern(self, team, **werte):
        daten = {
            "turnier": self.t.pk, "name": team.name, "status": team.status, "gruppe": "",
            "kapitaen_name": team.kapitaen_name, "kapitaen_email": team.kapitaen_email,
            "zahlungsart": team.zahlungsart, "notiz": "",
            "spieler-TOTAL_FORMS": "0", "spieler-INITIAL_FORMS": "0",
        }
        if team.bezahlt:
            daten["bezahlt"] = "on"
        daten.update(werte)
        return self.client.post(reverse("admin:tournament_team_change", args=[team.pk]), daten, follow=True)

    def test_reihenfolge_nach_eingang(self):
        self.assertEqual((self.alpha.wartelisten_platz, self.mitte.wartelisten_platz), (1, 2))
        self.assertIsNone(self.zeta.wartelisten_platz)
        self.orga()
        r = self.client.get(reverse("admin:tournament_team_changelist"))
        self.assertEqual([t.name for t in r.context["cl"].result_list], ["Zeta", "Alpha", "Mitte"])
        self.assertContains(r, "#1")

    def test_platz_oeffentlich_und_fuer_den_kapitaen(self):
        self.assertContains(self.client.get(reverse("teamliste")), "Warteliste · 1")
        r = self.client.get(reverse("team_bearbeiten", args=[self.mitte.edit_token]))
        self.assertContains(r, "<b>Platz 2</b> der Warteliste", html=False)
        self.assertContains(r, "entscheidet die Orga")

    def test_ohne_haken_kein_automatisches_nachruecken(self):
        self.client.post(reverse("team_abmelden", args=[self.zeta.edit_token]))
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.status, Team.Status.WARTELISTE)
        self.assertEqual(len(mail.outbox), 0)

    def test_abmeldung_laesst_ersten_nachruecken(self):
        self.automatisch()
        self.client.post(reverse("team_abmelden", args=[self.zeta.edit_token]))
        self.alpha.refresh_from_db()
        self.mitte.refresh_from_db()
        self.assertEqual(self.alpha.status, Team.Status.ANGEMELDET)
        self.assertEqual(self.mitte.wartelisten_platz, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["alpha@example.de"])
        self.assertIn("nachgerückt", mail.outbox[0].subject)
        self.assertIn(reverse("team_bearbeiten", args=[self.alpha.edit_token]), mail.outbox[0].body)
        r = self.client.get(reverse("team_bearbeiten", args=[self.mitte.edit_token]))
        self.assertContains(r, "rückt ihr automatisch nach")

    def test_bezahltes_wartelisten_team_ist_nach_dem_nachruecken_bestaetigt(self):
        self.alpha.bezahlt = True
        self.alpha.save()
        self.automatisch()
        self.client.post(reverse("team_abmelden", args=[self.zeta.edit_token]))
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.status, Team.Status.BESTAETIGT)

    def test_absage_im_admin(self):
        self.automatisch()
        self.orga()
        r = self.admin_team_speichern(self.zeta, status="abgesagt")
        self.assertContains(r, "Alpha ist automatisch von der Warteliste nachgerückt")
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.status, Team.Status.ANGEMELDET)

    def test_loeschen_im_admin(self):
        self.automatisch()
        self.orga()
        self.client.post(reverse("admin:tournament_team_delete", args=[self.zeta.pk]), {"post": "yes"})
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.status, Team.Status.ANGEMELDET)

    def test_mehr_plaetze_fuellen_die_warteliste(self):
        self.automatisch()
        self.t.max_teams = 3
        self.t.save()
        nachgerueckt = warteliste.auffuellen(self.t, self.client.get("/").wsgi_request)
        self.assertEqual([t.name for t in nachgerueckt], ["Alpha", "Mitte"])
        self.assertEqual(len(mail.outbox), 2)

    def test_mehr_plaetze_im_admin(self):
        self.automatisch()
        self.orga()
        r = self.client.post(reverse("admin:tournament_turnier_change", args=[self.t.pk]), {
            "name": self.t.name, "oeffentlich": "on", "datum": self.t.datum.isoformat(), "ort": self.t.ort,
            "startgebuehr_eur": "20", "meldeschluss_0": timezone.localtime(self.t.meldeschluss).strftime("%d.%m.%Y"),
            "meldeschluss_1": "23:59", "anmeldung_offen": "on", "max_teams": "2", "warteliste_automatisch": "on",
            "min_spieler": "2", "max_spieler": "10", "modus": "jeder_gegen_jeden", "anzahl_felder": "2",
            "slot_minuten": "20", "zaehlmodus": "saetze", "gewinnsaetze": "2", "punkte_pro_satz": "25",
            "punkte_entscheidungssatz": "15", "gruppen-TOTAL_FORMS": "0", "gruppen-INITIAL_FORMS": "0",
        }, follow=True)
        self.assertContains(r, "Alpha ist automatisch von der Warteliste nachgerückt")
        self.mitte.refresh_from_db()
        self.assertEqual((self.mitte.status, self.mitte.wartelisten_platz), (Team.Status.WARTELISTE, 1))

    def test_vergangenes_turnier_rueckt_nicht_nach(self):
        self.automatisch()
        Turnier.objects.filter(pk=self.t.pk).update(datum=timezone.localdate() - timedelta(days=1))
        self.t.refresh_from_db()
        self.assertEqual(warteliste.auffuellen(self.t, self.client.get("/").wsgi_request), [])

    def test_aktion_nachruecken_von_hand_in_anmelde_reihenfolge_mit_mail(self):
        self.orga()
        self.t.max_teams = 3
        self.t.save()
        r = self.client.post(reverse("admin:tournament_team_changelist"), {
            "action": "nachruecken", "_selected_action": [self.mitte.pk, self.alpha.pk],
        }, follow=True)
        self.assertContains(r, "2 Team(s) von der Warteliste nachgerückt, Mail verschickt")
        self.assertEqual([m.to[0] for m in mail.outbox], ["alpha@example.de", "mitte@example.de"])

    def anmelden(self, name):
        return self.client.post(reverse("anmelden"), {
            "name": name, "kapitaen_name": "K", "kapitaen_email": f"{name.lower()}@example.de", "datenschutz": "on",
            "spieler-TOTAL_FORMS": "2", "spieler-INITIAL_FORMS": "0",
            "spieler-0-vorname": "A", "spieler-0-nachname": "B", "spieler-1-vorname": "C", "spieler-1-nachname": "D",
        })

    def test_neue_anmeldung_ueberholt_die_warteliste_nicht(self):
        self.t.max_teams = 2  # ein Platz frei, aber Alpha und Mitte warten schon (Haken aus)
        self.t.save()
        self.assertContains(self.client.get(reverse("anmelden")), "Es warten schon Teams")
        self.anmelden("Neu")
        neu = Team.objects.get(name="Neu")
        self.assertEqual((neu.status, neu.wartelisten_platz), (Team.Status.WARTELISTE, 3))
        r = self.client.get(reverse("team_angemeldet", args=[neu.edit_token]))
        self.assertContains(r, "Platz 3 der Warteliste")

    def test_neue_anmeldung_mit_haken_holt_den_ersten_wartenden(self):
        self.t.max_teams = 2
        self.automatisch()
        self.anmelden("Neu")
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.status, Team.Status.ANGEMELDET)  # Alpha bekommt den Platz, nicht "Neu"
        self.assertEqual(Team.objects.get(name="Neu").wartelisten_platz, 2)

    def test_ohne_wartende_gibt_es_den_platz_direkt(self):
        Team.objects.filter(status=Team.Status.WARTELISTE).delete()
        self.t.max_teams = 2
        self.t.save()
        self.anmelden("Neu")
        self.assertEqual(Team.objects.get(name="Neu").status, Team.Status.ANGEMELDET)

    def test_zurueckgestuftes_team_rueckt_nicht_sofort_wieder_nach(self):
        self.automatisch()
        self.orga()
        # Zeta (frühestes Team) bewusst auf die Warteliste: Alpha bekommt den Platz, Zeta bleibt wartend
        self.admin_team_speichern(self.zeta, status="warteliste")
        self.zeta.refresh_from_db()
        self.alpha.refresh_from_db()
        self.assertEqual(self.zeta.status, Team.Status.WARTELISTE)
        self.assertEqual(self.alpha.status, Team.Status.ANGEMELDET)
        # beim nächsten freien Platz ist Zeta (früheste Anmeldung) wieder als Erstes dran
        self.client.post(reverse("team_abmelden", args=[self.alpha.edit_token]))
        self.zeta.refresh_from_db()
        self.assertEqual(self.zeta.status, Team.Status.ANGEMELDET)

    def kacheln(self):
        return self.client.get(reverse("admin:tournament_team_changelist"), {"turnier__id__exact": self.t.pk})

    def test_knopf_nachruecken(self):
        self.orga()
        self.t.max_teams = 2
        self.t.save()
        r = self.kacheln()
        self.assertContains(r, "Nachrücken: Alpha")  # der Erste der Warteliste, nicht alphabetisch zufällig
        knopf = reverse("admin:tournament_team_naechsten_nachruecken", args=[self.t.pk])
        self.assertContains(r, f'action="{knopf}"')

        r = self.client.post(knopf, follow=True)
        self.assertContains(r, "Alpha ist von der Warteliste nachgerückt, Mail verschickt")
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.status, Team.Status.ANGEMELDET)
        self.assertEqual([m.to for m in mail.outbox], [["alpha@example.de"]])
        self.assertContains(r, "kein Platz frei")  # jetzt voll, Mitte wartet weiter

    def test_knopf_nur_wenn_sinnvoll(self):
        self.orga()
        self.assertContains(self.kacheln(), "kein Platz frei")  # 1 von 1 Platz belegt
        self.automatisch()
        self.assertContains(self.kacheln(), "rücken automatisch nach")
        self.assertNotContains(self.kacheln(), "Nachrücken: ")

    def test_knopf_aendert_nichts_per_get_und_braucht_login(self):
        knopf = reverse("admin:tournament_team_naechsten_nachruecken", args=[self.t.pk])
        self.t.max_teams = 2
        self.t.save()
        r = self.client.post(knopf)
        self.assertIn("/admin/login/", r.url)  # ohne Orga-Login kein Nachrücken
        self.orga()
        self.client.get(knopf)
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.status, Team.Status.WARTELISTE)
