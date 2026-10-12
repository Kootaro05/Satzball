from datetime import date, datetime, timezone

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone as dj_timezone

from tournament.models import Gruppe, Spiel, Spieler, Team, Turnier


def turnier(**kwargs):
    werte = dict(
        name="Herbst-Cup 2026", datum=date(2026, 11, 14), ort="Campus-Halle",
        meldeschluss=datetime(2026, 10, 31, 22, 59, tzinfo=timezone.utc), max_teams=10,
    )
    werte.update(kwargs)
    return Turnier.objects.create(**werte)


def team(t, name, **kwargs):
    return Team.objects.create(turnier=t, name=name, kapitaen_name="Kapitän", kapitaen_email="k@example.de", **kwargs)


class TurnierTests(TestCase):
    def test_standardwerte(self):
        t = turnier()
        self.assertEqual(t.modus, Turnier.Modus.JEDER_GEGEN_JEDEN)
        self.assertEqual(t.zaehlmodus, Turnier.Zaehlmodus.SAETZE)
        self.assertEqual(t.gewinnsaetze, 2)  # Best of 3
        self.assertEqual(t.anzahl_felder, 2)
        self.assertFalse(t.anmeldung_offen)

    def test_min_spieler_groesser_max_spieler_ist_ungueltig(self):
        t = turnier(min_spieler=8, max_spieler=6)
        with self.assertRaises(ValidationError):
            t.full_clean()


class TeamTests(TestCase):
    def setUp(self):
        self.t = turnier()

    def test_edit_token_wird_erzeugt_und_ist_eindeutig(self):
        a, b = team(self.t, "Bit Blockers"), team(self.t, "Null Pointer Smash")
        self.assertGreaterEqual(len(a.edit_token), 32)
        self.assertNotEqual(a.edit_token, b.edit_token)

    def test_teamname_eindeutig_pro_turnier(self):
        team(self.t, "Bit Blockers")
        team(turnier(name="Frühjahrs-Cup"), "Bit Blockers")  # anderes Turnier ist ok
        with self.assertRaises(IntegrityError):
            team(self.t, "Bit Blockers")

    def test_nur_bestaetigte_und_bezahlte_teams_im_spielplan(self):
        ok = team(self.t, "Bestätigt + bezahlt", status=Team.Status.BESTAETIGT, bezahlt=True)
        team(self.t, "Bestätigt, offen", status=Team.Status.BESTAETIGT)
        team(self.t, "Angemeldet, offen")
        team(self.t, "Warteliste", status=Team.Status.WARTELISTE, bezahlt=True)
        self.assertEqual(list(Team.objects.im_spielplan()), [ok])

    def test_bezahlt_bestaetigt_das_team(self):
        tm = team(self.t, "Bit Blockers")
        tm.bezahlt = True
        tm.save()
        tm.refresh_from_db()
        self.assertEqual(tm.status, Team.Status.BESTAETIGT)
        self.assertEqual(tm.bezahlt_am, dj_timezone.localdate())
        self.assertEqual(list(Team.objects.im_spielplan()), [tm])

    def test_bezahlt_zuruecknehmen_hebt_bestaetigung_auf(self):
        tm = team(self.t, "Bit Blockers", bezahlt=True)
        tm.bezahlt = False
        tm.save()
        self.assertEqual(tm.status, Team.Status.ANGEMELDET)

    def test_bezahlt_aendert_warteliste_und_absage_nicht(self):
        for status in (Team.Status.WARTELISTE, Team.Status.ABGESAGT):
            tm = team(self.t, status, status=status, bezahlt=True)
            self.assertEqual(tm.status, status)

    def test_freie_plaetze_zaehlen_nur_startplaetze(self):
        self.t.max_teams = 3
        team(self.t, "A")
        team(self.t, "B", bezahlt=True)
        team(self.t, "C", status=Team.Status.WARTELISTE)
        team(self.t, "D", status=Team.Status.ABGESAGT)
        self.assertEqual(self.t.belegte_plaetze, 2)
        self.assertEqual(self.t.freie_plaetze, 1)

    def test_team_mit_geplanten_spielen_kann_geloescht_werden(self):
        a, b = team(self.t, "A"), team(self.t, "B")
        spiel = Spiel.objects.create(turnier=self.t, team_a=a, team_b=b, schiri_team=a)
        a.delete()
        spiel.refresh_from_db()
        self.assertIsNone(spiel.team_a)
        self.assertIsNone(spiel.schiri_team)
        self.assertEqual(spiel.team_b, b)

    def test_gruppe_aus_anderem_turnier_ist_ungueltig(self):
        fremde_gruppe = Gruppe.objects.create(turnier=turnier(name="Anderes"), name="A")
        tm = team(self.t, "Bit Blockers", gruppe=fremde_gruppe)
        with self.assertRaises(ValidationError):
            tm.full_clean()

    def test_spieler_werden_mit_team_geloescht(self):
        tm = team(self.t, "Bit Blockers")
        Spieler.objects.create(team=tm, vorname="Lena", nachname="Hoffmann")
        tm.delete()
        self.assertFalse(Spieler.objects.exists())


class SpielTests(TestCase):
    def setUp(self):
        self.t = turnier()
        self.a = team(self.t, "Bit Blockers")
        self.b = team(self.t, "Null Pointer Smash")

    def spiel(self, **kwargs):
        return Spiel(turnier=self.t, team_a=self.a, team_b=self.b, **kwargs)

    def test_team_gegen_sich_selbst_ist_ungueltig(self):
        with self.assertRaises(ValidationError):
            Spiel(turnier=self.t, team_a=self.a, team_b=self.a).full_clean()

    def test_schiri_darf_nicht_selbst_spielen(self):
        with self.assertRaises(ValidationError):
            self.spiel(schiri_team=self.a).full_clean()

    def test_ko_spiel_mit_platzhaltern_ohne_teams(self):
        s = Spiel(turnier=self.t, platzhalter_a="1. Gruppe A", platzhalter_b="2. Gruppe B")
        s.full_clean()
        self.assertEqual(str(s), "1. Gruppe A – 2. Gruppe B")

    def test_ko_spiel_gehoert_zu_keiner_gruppe(self):
        gruppe = Gruppe.objects.create(turnier=self.t, name="A")
        with self.assertRaises(ValidationError):
            Spiel(turnier=self.t, gruppe=gruppe, phase=Spiel.Phase.HALBFINALE).full_clean()
        Spiel(turnier=self.t, phase=Spiel.Phase.PLATZ_3, platzhalter_a="Verlierer HF 1",
              platzhalter_b="Verlierer HF 2").full_clean()

    def test_beendetes_spiel_braucht_beide_teams(self):
        s = Spiel(turnier=self.t, team_a=self.a, platzhalter_b="2. Gruppe B",
                  status=Spiel.Status.BEENDET, saetze_a=2, saetze_b=0)
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_satz_modus_gueltiges_ergebnis(self):
        s = self.spiel(status=Spiel.Status.BEENDET, saetze_a=1, saetze_b=2, punkte_a=63, punkte_b=60)
        s.full_clean()
        self.assertEqual(s.sieger, self.b)

    def test_satz_modus_ungueltige_ergebnisse(self):
        # Best of 3: genau ein Team braucht 2 Sätze
        for a, b in [(2, 2), (1, 0), (3, 1), (None, 2)]:
            with self.subTest(a=a, b=b), self.assertRaises(ValidationError):
                self.spiel(status=Spiel.Status.BEENDET, saetze_a=a, saetze_b=b).full_clean()

    def test_satz_modus_best_of_1(self):
        self.t.gewinnsaetze = Turnier.Gewinnsaetze.BEST_OF_1
        self.spiel(status=Spiel.Status.BEENDET, saetze_a=1, saetze_b=0).full_clean()

    def test_punkte_modus(self):
        self.t.zaehlmodus = Turnier.Zaehlmodus.PUNKTE
        s = self.spiel(status=Spiel.Status.BEENDET, punkte_a=25, punkte_b=21)
        s.full_clean()
        self.assertEqual(s.sieger, self.a)
        with self.assertRaises(ValidationError):
            self.spiel(status=Spiel.Status.BEENDET, punkte_a=25, punkte_b=25).full_clean()

    def test_geplantes_spiel_hat_keinen_sieger(self):
        self.assertIsNone(self.spiel(saetze_a=2, saetze_b=0).sieger)
