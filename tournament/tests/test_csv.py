import csv
import io
from datetime import date, timedelta

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournament.models import Spieler, Team, Turnier


class CsvExportTests(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Herbst-Cup", datum=timezone.localdate() + timedelta(days=20), ort="Halle",
            meldeschluss=timezone.now() + timedelta(days=5), max_teams=8, startgebuehr_eur=12.5,
        )
        self.bezahlt = Team.objects.create(
            turnier=self.t, name="Netzroller", kapitaen_name="Jörg", kapitaen_email="joerg@example.de",
            bezahlt=True, bezahlt_am=date(2026, 10, 2), zahlungsart=Team.Zahlungsart.BAR,
        )
        Spieler.objects.create(team=self.bezahlt, vorname="A", nachname="B")
        Spieler.objects.create(team=self.bezahlt, vorname="C", nachname="D")
        self.boese = Team.objects.create(turnier=self.t, name="=HYPERLINK(\"x\")", kapitaen_name="-1+1",
                                         kapitaen_email="b@example.de")
        self.liste = reverse("admin:tournament_team_changelist")

    def exportieren(self, *teams):
        return self.client.post(self.liste, {"action": "als_csv", ACTION_CHECKBOX_NAME: [t.pk for t in teams]})

    def zeilen(self, antwort):
        text = antwort.content.decode("utf-8")
        self.assertTrue(text.startswith("﻿"))  # BOM für Excel
        return list(csv.reader(io.StringIO(text[1:]), delimiter=";"))

    def test_inhalt(self):
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))
        r = self.exportieren(self.bezahlt, self.boese)
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment;", r["Content-Disposition"])
        kopf, netzroller, boese = self.zeilen(r)
        self.assertEqual(kopf[:3], ["Turnier", "Team", "Kapitän"])
        self.assertEqual(netzroller, ["Herbst-Cup", "Netzroller", "Jörg", "joerg@example.de", "Bestätigt", "2",
                                      "12,50", "ja", "02.10.2026", "Bar", ""])
        # Formeln aus dem öffentlichen Anmeldeformular werden in Excel nicht ausgeführt
        self.assertEqual(boese[1:3], ["'=HYPERLINK(\"x\")", "'-1+1"])
        self.assertEqual(boese[7], "nein")

    def test_nur_fuer_orga_mit_rechten(self):
        r = self.exportieren(self.bezahlt)
        self.assertIn("/admin/login/", r.url)
        ohne = User.objects.create_user("helfer", "h@example.de", "x", is_staff=True)
        self.client.force_login(ohne)
        self.assertEqual(self.exportieren(self.bezahlt).status_code, 403)
        ohne.user_permissions.add(Permission.objects.get(codename="view_team"))
        r = self.exportieren(self.bezahlt)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.zeilen(r)), 2)
