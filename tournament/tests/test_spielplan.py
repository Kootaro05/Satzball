import random
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from itertools import combinations

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from tournament import spielplan
from tournament.models import Spiel, Team, Turnier

Phase = Spiel.Phase


class KreismethodeTests(SimpleTestCase):
    def pruefen(self, teams):
        runden = spielplan.kreismethode(teams)
        paare = [frozenset(p) for paarungen, _ in runden for p in paarungen]
        self.assertEqual(len(paare), len(teams) * (len(teams) - 1) // 2)
        self.assertEqual(set(paare), {frozenset(p) for p in combinations(teams, 2)})
        for paarungen, spielfrei in runden:
            in_runde = [t for p in paarungen for t in p] + ([spielfrei] if spielfrei else [])
            self.assertEqual(sorted(in_runde), sorted(teams))  # jedes Team genau einmal pro Runde
        return runden

    def test_gerade_anzahl(self):
        runden = self.pruefen(list("ABCD"))
        self.assertEqual(len(runden), 3)
        self.assertTrue(all(spielfrei is None for _, spielfrei in runden))

    def test_ungerade_anzahl_jedes_team_einmal_spielfrei(self):
        runden = self.pruefen(list("ABCDE"))
        self.assertEqual(len(runden), 5)
        self.assertEqual(sorted(spielfrei for _, spielfrei in runden), list("ABCDE"))

    def test_zehn_teams(self):
        self.assertEqual(len(self.pruefen(list(range(10)))), 9)


class VerteilungTests(SimpleTestCase):
    def test_gruppen_vorschlag(self):
        for teams, gruppen in [(6, 2), (8, 2), (10, 2), (11, 3), (12, 3), (15, 3), (16, 4), (20, 4), (30, 4)]:
            self.assertEqual(spielplan.gruppen_vorschlag(teams), gruppen, teams)

    def test_gruppen_gleich_gross(self):
        gruppen = spielplan.gruppen_bilden(range(11), 3, random.Random(1))
        self.assertEqual(sorted(len(g) for g in gruppen), [3, 4, 4])
        self.assertEqual(sorted(t for g in gruppen for t in g), list(range(11)))

    def test_slots_rechenbeispiel_aus_dem_konzept(self):
        # 10 Teams, 2 Gruppen à 5, 2 Felder -> 20 Spiele in 10 Slots
        gruppen = [("A", list("ABCDE")), ("B", list("FGHIJ"))]
        slots = spielplan.slots_verteilen(spielplan.gruppenpartien(gruppen), 2)
        self.assertEqual(len(slots), 10)
        for slot in slots:
            teams = [t for p in slot for t in (p.a, p.b)]
            self.assertLessEqual(len(slot), 2)
            self.assertEqual(len(teams), len(set(teams)))  # kein Team doppelt im Slot

    def test_schiri_spielt_nicht_im_selben_slot_und_kommt_aus_der_anderen_gruppe(self):
        gruppen = [("A", list("ABCDE")), ("B", list("FGHIJ"))]
        slots = spielplan.slots_verteilen(spielplan.gruppenpartien(gruppen), 2)
        spielplan.schiris_zuteilen(slots, dict(gruppen))
        for slot in slots:
            spieler = {t for p in slot for t in (p.a, p.b)}
            schiris = [p.schiri for p in slot]
            self.assertTrue(all(schiris))
            self.assertFalse(spieler & set(schiris))
            self.assertEqual(len(schiris), len(set(schiris)))
        gruppe_von = {t: g for g, teams in gruppen for t in teams}
        self.assertTrue(all(gruppe_von[p.schiri] != p.gruppe for slot in slots for p in slot))
        # 20 Spiele, 10 Teams: jedes pfeift zweimal
        self.assertEqual(set(Counter(p.schiri for slot in slots for p in slot).values()), {2})

    def test_schiri_aus_anderen_gruppen_bleibt_gerecht_verteilt(self):
        gruppen = [("A", list("ABC")), ("B", list("DEF")), ("C", list("GHI"))]
        slots = spielplan.schiris_zuteilen(spielplan.slots_verteilen(spielplan.gruppenpartien(gruppen), 2), dict(gruppen))
        self.assertEqual(Counter(p.schiri for slot in slots for p in slot), Counter("ABCDEFGHI"))  # jedes Team einmal

    def test_schiri_aus_der_eigenen_gruppe_wenn_die_andere_komplett_spielt(self):
        gruppen = {"A": list("ABC"), "B": list("DE")}
        slot = [spielplan.Partie("A", "B", "A", spielfrei="C"), spielplan.Partie("D", "E", "B")]
        spielplan.schiris_zuteilen([slot], gruppen)
        self.assertEqual(slot[0].schiri, "C")  # D und E spielen gerade: das spielfreie Team pfeift
        self.assertIsNone(slot[1].schiri)  # A, B spielen, C pfeift schon – niemand frei

    def test_jeder_gegen_jeden_pfeift_das_spielfreie_team(self):
        gruppen = [("A", list("ABCDE"))]
        slots = spielplan.schiris_zuteilen(spielplan.slots_verteilen(spielplan.gruppenpartien(gruppen), 2), dict(gruppen))
        for slot in slots:
            spielend = {t for p in slot for t in (p.a, p.b)}
            for p in slot:
                if p.spielfrei and p.spielfrei not in spielend:
                    self.assertIn(p.spielfrei, [q.schiri for q in slot])

    def test_schiri_bei_gerader_gruppe(self):
        gruppen = [("A", list("ABCD"))]
        slots = spielplan.schiris_zuteilen(spielplan.slots_verteilen(spielplan.gruppenpartien(gruppen), 1), dict(gruppen))
        for slot in slots:
            p = slot[0]
            self.assertNotIn(p.schiri, (p.a, p.b))
        self.assertEqual(sorted(Counter(p.schiri for s in slots for p in s).values()), [1, 1, 2, 2])

    def test_ko_stufen(self):
        def phasen(n):
            return [phase for stufe in spielplan.ko_stufen(n) for phase, _, _ in stufe]
        self.assertEqual(phasen(1), [])
        self.assertEqual(phasen(2), [Phase.HALBFINALE] * 2 + [Phase.PLATZ_3, Phase.FINALE])
        self.assertEqual(phasen(3), [Phase.HALBFINALE] * 2 + [Phase.PLATZ_3, Phase.FINALE])
        self.assertEqual(phasen(4), [Phase.VIERTELFINALE] * 4 + [Phase.HALBFINALE] * 2 + [Phase.PLATZ_3, Phase.FINALE])
        self.assertIn((Phase.HALBFINALE, "1. Gruppe A", "2. Gruppe B"), spielplan.ko_stufen(2)[0])
        self.assertIn((Phase.HALBFINALE, "1. Gruppe A", "Bester Gruppenzweiter"), spielplan.ko_stufen(3)[0])


class SpielplanBasis(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Cup", datum=date(2026, 11, 14), beginn=time(9, 30), ort="Halle", max_teams=12,
            meldeschluss=datetime(2026, 10, 31, tzinfo=timezone.utc), modus=Turnier.Modus.GRUPPEN_KO,
        )

    def teams(self, n, **kwargs):
        werte = dict(status=Team.Status.BESTAETIGT, bezahlt=True)
        werte.update(kwargs)
        start = self.t.teams.count()
        return [Team.objects.create(turnier=self.t, name=f"Team {start + i:02d}", kapitaen_name="K",
                                    kapitaen_email="k@example.de", **werte) for i in range(n)]

    def assertKeineKonflikte(self):
        self.assertEqual(spielplan.konflikte(self.t.spiele.all()), [])


class SpielplanDbTests(SpielplanBasis):
    def test_gruppen_ko_mit_zehn_teams(self):
        self.teams(10)
        self.teams(1, bezahlt=False)  # nicht bezahlt -> nicht im Plan
        spielplan.erzeugen(self.t, zufall=random.Random(3))

        self.assertEqual(self.t.gruppen.count(), 2)
        self.assertEqual(sorted(g.teams.count() for g in self.t.gruppen.all()), [5, 5])
        gruppenspiele = self.t.spiele.filter(phase=Phase.GRUPPE)
        self.assertEqual(gruppenspiele.count(), 20)
        self.assertEqual(self.t.spiele.exclude(phase=Phase.GRUPPE).count(), 4)
        self.assertFalse(self.t.spiele.filter(team_a__bezahlt=False).exists())
        self.assertFalse(gruppenspiele.filter(schiri_team=None).exists())

        zeiten = sorted({s.uhrzeit for s in self.t.spiele.all()})
        self.assertEqual(len(zeiten), 12)  # 10 Gruppen-Slots + Halbfinale + Platz 3/Finale
        self.assertEqual(zeiten[0], time(9, 30))
        self.assertEqual(zeiten[-1], time(13, 10))
        finale = self.t.spiele.get(phase=Phase.FINALE)
        self.assertEqual((finale.platzhalter_a, finale.platzhalter_b), ("Sieger HF 1", "Sieger HF 2"))
        self.assertKeineKonflikte()

    def test_jeder_gegen_jeden(self):
        self.t.modus = Turnier.Modus.JEDER_GEGEN_JEDEN
        self.teams(5)
        spielplan.erzeugen(self.t)
        self.assertEqual(self.t.gruppen.count(), 1)
        self.assertEqual(self.t.spiele.count(), 10)
        self.assertFalse(self.t.spiele.exclude(phase=Phase.GRUPPE).exists())
        self.assertKeineKonflikte()

    def test_vier_gruppen_mit_viertelfinale(self):
        self.teams(16)
        spielplan.erzeugen(self.t, anzahl_gruppen=4)
        self.assertEqual(self.t.spiele.filter(phase=Phase.VIERTELFINALE).count(), 4)
        self.assertEqual(self.t.spiele.filter(phase=Phase.GRUPPE).count(), 4 * 6)
        self.assertKeineKonflikte()

    def test_fehler(self):
        self.teams(5)
        with self.assertRaisesMessage(spielplan.SpielplanFehler, "mindestens 6"):
            spielplan.erzeugen(self.t, anzahl_gruppen=2)
        self.teams(1)
        self.t.beginn = None
        with self.assertRaisesMessage(spielplan.SpielplanFehler, "Startzeit"):
            spielplan.erzeugen(self.t)
        self.t.beginn = time(9, 30)
        spielplan.erzeugen(self.t)
        Spiel.objects.filter(pk=self.t.spiele.filter(phase=Phase.GRUPPE).first().pk).update(
            status=Spiel.Status.BEENDET, saetze_a=2, saetze_b=0)
        with self.assertRaisesMessage(spielplan.SpielplanFehler, "Ergebnisse"):
            spielplan.erzeugen(self.t)

    def test_neu_erzeugen_ersetzt_alten_plan(self):
        self.teams(6)
        spielplan.erzeugen(self.t)
        spielplan.erzeugen(self.t)
        self.assertEqual(self.t.gruppen.count(), 2)
        self.assertEqual(self.t.spiele.filter(phase=Phase.GRUPPE).count(), 6)

    def test_schiris_nach_tauschen_neu_verteilen(self):
        self.teams(10)
        spielplan.erzeugen(self.t, zufall=random.Random(3))
        spiele = list(self.t.spiele.filter(phase=Phase.GRUPPE).order_by("uhrzeit", "feld"))
        spielplan.tauschen(spiele[0], spiele[3])  # Gruppe A aus Slot 1 mit Gruppe B aus Slot 2
        spielplan.schiris_neu(self.t)
        self.assertKeineKonflikte()
        self.assertFalse(self.t.spiele.filter(phase=Phase.GRUPPE, schiri_team=None).exists())
        # in ungeraden Gruppen pfeift weiter das spielfreie Team der Runde
        for s in self.t.spiele.filter(phase=Phase.GRUPPE).select_related("gruppe"):
            spielend = {t for x in self.t.spiele.filter(gruppe=s.gruppe, runde=s.runde) for t in (x.team_a_id, x.team_b_id)}
            self.assertNotIn(s.schiri_team_id, spielend)

    def test_tauschen_und_konflikt_erkennen(self):
        self.teams(6)
        spielplan.erzeugen(self.t)
        a, b = self.t.spiele.order_by("uhrzeit", "feld")[:2]
        spielplan.tauschen(a, b)
        a.refresh_from_db()
        self.assertEqual(a.feld, 2)
        spielplan.verschieben(a, b.uhrzeit, b.feld)  # jetzt zwei Spiele auf Feld 1
        self.assertTrue(any("doppelt belegt" in k for k in spielplan.konflikte(self.t.spiele.all())))


class UmplanenTests(SpielplanBasis):
    def team_loeschen(self, team):
        """Löschen wie im Admin (dort hängt das Umplanen dran)."""
        admin = User.objects.create_superuser("orga", "o@example.de", "x")
        self.client.force_login(admin)
        r = self.client.post(reverse("admin:tournament_team_delete", args=[team.pk]), {"post": "yes"})
        self.assertEqual(r.status_code, 302)

    def test_offene_spiele_neu_ergebnisse_bleiben(self):
        self.teams(10)
        spielplan.erzeugen(self.t, zufall=random.Random(7))
        erster_slot = list(self.t.spiele.filter(uhrzeit=time(9, 30)))
        for s in erster_slot:
            s.status, s.saetze_a, s.saetze_b = Spiel.Status.BEENDET, 2, 1
            s.save()

        gruppe_a = self.t.gruppen.get(name="A")
        weg = next(t for t in gruppe_a.teams.all()
                   if not any(t in (s.team_a, s.team_b) for s in erster_slot))
        self.team_loeschen(weg)

        # beendete Spiele unverändert
        for s in erster_slot:
            s.refresh_from_db()
            self.assertEqual((s.status, s.uhrzeit), (Spiel.Status.BEENDET, time(9, 30)))
        # Gruppe A: jedes Paar der 4 verbliebenen Teams genau einmal, gelöschtes Team nirgends
        rest = list(gruppe_a.teams.all())
        self.assertEqual(len(rest), 4)
        paare = Counter(frozenset((s.team_a_id, s.team_b_id)) for s in self.t.spiele.filter(gruppe=gruppe_a))
        self.assertEqual(set(paare), {frozenset((a.pk, b.pk)) for a, b in combinations(rest, 2)})
        self.assertEqual(set(paare.values()), {1})
        geplant = self.t.spiele.filter(status=Spiel.Status.GEPLANT)
        self.assertFalse(geplant.filter(phase=Phase.GRUPPE, team_a=None).exists())
        # offene Spiele beginnen nach dem letzten beendeten Slot, K.-o. ganz am Ende
        self.assertEqual(min(s.uhrzeit for s in geplant), time(9, 50))
        letzte_gruppe = max(s.uhrzeit for s in geplant.filter(phase=Phase.GRUPPE))
        self.assertTrue(all(s.uhrzeit > letzte_gruppe for s in geplant.exclude(phase=Phase.GRUPPE)))
        self.assertEqual(geplant.exclude(phase=Phase.GRUPPE).count(), 4)
        self.assertKeineKonflikte()

    def test_andere_gruppe_behaelt_ihre_paarungen(self):
        self.teams(10)
        spielplan.erzeugen(self.t, zufall=random.Random(7))
        gruppe_b = self.t.gruppen.get(name="B")
        vorher = set(self.t.spiele.filter(gruppe=gruppe_b).values_list("pk", "team_a", "team_b"))
        self.team_loeschen(self.t.gruppen.get(name="A").teams.first())
        self.assertEqual(set(self.t.spiele.filter(gruppe=gruppe_b).values_list("pk", "team_a", "team_b")), vorher)
        self.assertKeineKonflikte()
