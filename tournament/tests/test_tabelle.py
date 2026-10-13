from datetime import date, datetime, timezone

from django.test import TestCase

from tournament.models import Gruppe, Spiel, Team, Turnier
from tournament.tabelle import berechnen, gruppentabellen


class TabelleTests(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Cup", datum=date(2026, 11, 14), ort="Halle", max_teams=8,
            meldeschluss=datetime(2026, 10, 31, tzinfo=timezone.utc),
        )
        self.gruppe = Gruppe.objects.create(turnier=self.t, name="A")
        self.teams = {n: Team.objects.create(turnier=self.t, name=n, kapitaen_name="K", kapitaen_email="k@example.de",
                                             gruppe=self.gruppe) for n in ["Adler", "Zebra", "Chaos", "Delta"]}

    def spiel(self, a, b, sa=None, sb=None, pa=None, pb=None, **kwargs):
        werte = dict(turnier=self.t, gruppe=self.gruppe, team_a=self.teams[a], team_b=self.teams[b],
                     saetze_a=sa, saetze_b=sb, punkte_a=pa, punkte_b=pb, status=Spiel.Status.BEENDET)
        werte.update(kwargs)
        return Spiel.objects.create(**werte)

    def reihenfolge(self):
        tabelle = berechnen(list(self.teams.values()), list(self.t.spiele.all()), self.t.zaehlmodus)
        return [z.team.name for z in tabelle], tabelle

    def test_satz_modus_siege_dann_satzdifferenz_dann_ballpunkte(self):
        self.spiel("Adler", "Delta", 2, 0, 50, 30)
        self.spiel("Zebra", "Delta", 2, 1, 70, 60)
        self.spiel("Chaos", "Delta", 2, 0, 50, 40)
        namen, tabelle = self.reihenfolge()
        # Adler und Chaos: 1 Sieg, SD +2 -> Ballpunkte entscheiden (+20 vor +10)
        self.assertEqual(namen, ["Adler", "Chaos", "Zebra", "Delta"])
        adler = tabelle[0]
        self.assertEqual((adler.platz, adler.sp, adler.s, adler.n, adler.sd, adler.pd), (1, 1, 1, 0, 2, 20))
        delta = tabelle[-1]
        self.assertEqual((delta.saetze_plus, delta.saetze_minus, delta.n), (1, 6, 3))

    def test_direkter_vergleich(self):
        # Zebra und Adler: je 2 Siege, Satzdifferenz +1, keine Ballpunkte -> Zebra hat Adler geschlagen
        self.spiel("Zebra", "Adler", 2, 1)
        self.spiel("Chaos", "Zebra", 2, 0)
        self.spiel("Zebra", "Delta", 2, 0)
        self.spiel("Adler", "Chaos", 2, 1)
        self.spiel("Adler", "Delta", 2, 1)
        namen, tabelle = self.reihenfolge()
        self.assertEqual(namen[:2], ["Zebra", "Adler"])
        self.assertEqual((tabelle[0].s, tabelle[0].sd), (tabelle[1].s, tabelle[1].sd))

    def test_punkte_modus(self):
        self.t.zaehlmodus = Turnier.Zaehlmodus.PUNKTE
        self.spiel("Adler", "Delta", pa=25, pb=20)
        self.spiel("Zebra", "Delta", pa=25, pb=20)
        self.spiel("Chaos", "Delta", pa=30, pb=25)
        namen, tabelle = self.reihenfolge()
        # alle +5 Punktdifferenz -> mehr erzielte Punkte zuerst, dann Name
        self.assertEqual(namen, ["Chaos", "Adler", "Zebra", "Delta"])
        self.assertEqual((tabelle[0].punkte_plus, tabelle[0].pd), (30, 5))

    def test_zaehlt_nur_beendete_gruppenspiele_vorhandener_teams(self):
        self.spiel("Adler", "Delta", 2, 0)
        self.spiel("Zebra", "Delta", 2, 0, status=Spiel.Status.GEPLANT)
        self.spiel("Chaos", "Delta", 2, 0, gruppe=None, phase=Spiel.Phase.FINALE)
        weg = self.spiel("Chaos", "Adler", 2, 0)
        self.teams["Chaos"].delete()
        self.teams.pop("Chaos")
        weg.refresh_from_db()
        self.assertIsNone(weg.team_a)
        namen, tabelle = self.reihenfolge()
        self.assertEqual(namen[0], "Adler")
        self.assertEqual(sum(z.sp for z in tabelle), 2)  # nur Adler–Delta zählt

    def test_gruppentabellen(self):
        self.spiel("Adler", "Delta", 2, 0)
        [(gruppe, tabelle)] = gruppentabellen(self.t)
        self.assertEqual(gruppe, self.gruppe)
        self.assertEqual(tabelle[0].team.name, "Adler")
