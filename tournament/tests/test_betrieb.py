import sqlite3
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tournament import spielplan
from tournament.models import Spiel, Spieler, Team, Turnier


class TeamdatenLoeschenTests(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Cup", datum=timezone.localdate() - timedelta(days=100), ort="Halle", max_teams=10,
            meldeschluss=timezone.now() - timedelta(days=110), beginn=timezone.localtime().time(),
        )
        for i in range(6):
            team = Team.objects.create(turnier=self.t, name=f"Team {i}", kapitaen_name="Lena",
                                       kapitaen_email="lena@example.de", notiz="ruft an", bezahlt=True)
            Spieler.objects.create(team=team, vorname="Max", nachname="Meier")
        spielplan.erzeugen(self.t)
        self.spiel = self.t.spiele.filter(phase=Spiel.Phase.GRUPPE).first()
        self.spiel.status, self.spiel.saetze_a, self.spiel.saetze_b = Spiel.Status.BEENDET, 2, 0
        self.spiel.save()
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))
        self.url = reverse("admin:tournament_turnier_changelist")

    def aktion(self, **extra):
        return self.client.post(self.url, {"action": "teamdaten_loeschen", "_selected_action": [self.t.pk], **extra},
                                follow=True)

    def test_loescht_personendaten_ergebnisse_bleiben(self):
        alter_token = self.t.teams.first().edit_token
        self.t.teamdaten_loeschen()
        self.assertFalse(Spieler.objects.exists())
        self.assertEqual(set(self.t.teams.values_list("kapitaen_name", "kapitaen_email", "notiz")), {("", "", "")})
        self.assertEqual(self.t.teams.count(), 6)
        self.assertNotEqual(self.t.teams.first().edit_token, alter_token)
        self.assertEqual(self.client.get(reverse("team_bearbeiten", args=[alter_token])).status_code, 404)
        self.spiel.refresh_from_db()
        self.assertEqual((self.spiel.status, self.spiel.saetze_a), (Spiel.Status.BEENDET, 2))
        self.t.refresh_from_db()
        self.assertEqual(self.t.teamdaten_geloescht_am, timezone.localdate())

    def test_admin_protokoll_mit_namen_wird_geloescht(self):
        from django.contrib.admin.models import CHANGE, LogEntry
        from django.contrib.contenttypes.models import ContentType

        team = self.t.teams.first()
        admin = User.objects.get(username="orga")
        LogEntry.objects.create(
            user=admin, content_type=ContentType.objects.get_for_model(Team), object_id=str(team.pk),
            object_repr=team.name, action_flag=CHANGE,
            change_message='[{"added": {"name": "Spieler", "object": "Lena Hoffmann"}}]',
        )
        anderes = Turnier.objects.create(name="Anderes", datum=self.t.datum, ort="Halle", max_teams=4,
                                         meldeschluss=self.t.meldeschluss)
        LogEntry.objects.create(
            user=admin, content_type=ContentType.objects.get_for_model(Turnier), object_id=str(anderes.pk),
            object_repr=anderes.name, action_flag=CHANGE, change_message="[]",
        )
        self.t.teamdaten_loeschen()
        self.assertFalse(LogEntry.objects.filter(change_message__contains="Lena Hoffmann").exists())
        self.assertTrue(LogEntry.objects.filter(object_repr="Anderes").exists())  # anderes bleibt

    def test_admin_aktion_fragt_erst_nach(self):
        r = self.aktion()
        self.assertContains(r, "Ja, Teamdaten löschen")
        self.assertTrue(Spieler.objects.exists())
        r = self.aktion(bestaetigt="ja")
        self.assertContains(r, "Teamdaten von 1 Turnier(en) gelöscht")
        self.assertFalse(Spieler.objects.exists())

    def test_nicht_vor_dem_turniertag(self):
        self.t.datum = timezone.localdate()
        self.t.save()
        r = self.aktion(bestaetigt="ja")
        self.assertContains(r, "erst nach dem Turniertag möglich")
        self.assertTrue(Spieler.objects.exists())

    def test_team_ohne_kapitaensdaten_im_admin_speicherbar(self):
        self.t.teamdaten_loeschen()
        team = self.t.teams.first()
        r = self.client.get(reverse("admin:tournament_team_change", args=[team.pk]))
        self.assertEqual(r.status_code, 200)
        team.full_clean()


class AnmeldungPflichtfelderTests(TestCase):
    def test_kapitaen_bleibt_pflicht(self):
        Turnier.objects.create(
            name="Cup", oeffentlich=True, datum=timezone.localdate() + timedelta(days=5), ort="Halle", max_teams=10,
            meldeschluss=timezone.now() + timedelta(days=2), anmeldung_offen=True, min_spieler=1,
        )
        r = self.client.post(reverse("anmelden"), {
            "name": "X", "kapitaen_name": "", "kapitaen_email": "", "datenschutz": "on",
            "spieler-TOTAL_FORMS": "1", "spieler-INITIAL_FORMS": "0",
            "spieler-0-vorname": "A", "spieler-0-nachname": "B",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["form"].errors), 2)
        self.assertFalse(Team.objects.exists())


class BefehleTests(TestCase):
    def test_testturnier(self):
        ausgabe = StringIO()
        call_command("testturnier", "--teams", "8", "--spielplan", stdout=ausgabe)
        t = Turnier.objects.get()
        self.assertEqual(t.datum, timezone.localdate())
        self.assertEqual(Team.objects.im_spielplan().count(), 8)
        self.assertEqual(t.teams.filter(bezahlt=False).count(), 2)
        self.assertTrue(t.spielplan_veroeffentlicht)
        self.assertTrue(t.oeffentlich)
        timberborn = t.teams.get(name="Timberborn-Volleys")
        self.assertEqual((timberborn.kapitaen_name, timberborn.bezahlt), ("Maxim Stremel (Coach)", True))
        self.assertEqual(
            list(timberborn.spieler.order_by("pk").values_list("vorname", "nachname")),
            [("Maxim", "Stremel"), ("Leon", "P."), ("Martin", "K."),
             ("Max", "K."), ("Leon", "S."), ("Oliver", "M.")],
        )
        self.assertEqual(t.spiele.filter(phase=Spiel.Phase.GRUPPE).count(), 12)  # 2 Gruppen à 4
        self.assertFalse(t.teams.exclude(kapitaen_email__endswith="@example.invalid").exists())
        self.assertIn("Spielplan erzeugt", ausgabe.getvalue())



    def test_testturnier_mit_zu_wenigen_teams(self):
        with self.assertRaisesMessage(CommandError, "mindestens 6"):
            call_command("testturnier", "--teams", "4", "--spielplan", stdout=StringIO())
        self.assertFalse(Turnier.objects.exists())  # nichts Halbes übrig
        call_command("testturnier", "--teams", "4", stdout=StringIO())  # ohne Spielplan geht es
        self.assertEqual(Turnier.objects.count(), 1)


class SicherungTests(TransactionTestCase):
    # Ohne umschließende Test-Transaktion – sonst wartet das SQLite-Backup endlos auf die Sperre.
    def test_sicherung(self):
        Turnier.objects.create(name="Gesichert", datum=timezone.localdate(), ort="Halle", max_teams=4,
                               meldeschluss=timezone.now())
        with tempfile.TemporaryDirectory() as tmp, override_settings(DATA_DIR=Path(tmp)):
            for _ in range(3):
                call_command("sicherung", "--behalten", "2", stdout=StringIO())
            dateien = sorted((Path(tmp) / "sicherungen").glob("db-*.sqlite3"))
            self.assertLessEqual(len(dateien), 2)
            with sqlite3.connect(dateien[-1]) as db:
                namen = [r[0] for r in db.execute("select name from tournament_turnier")]
            db.close()
            self.assertEqual(namen, ["Gesichert"])
