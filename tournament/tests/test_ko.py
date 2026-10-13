import random
from datetime import date, datetime, time, timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tournament import ko, spielplan
from tournament.models import Spiel, Team, Turnier

Phase = Spiel.Phase


class KoBefuellenTests(TestCase):
    def setUp(self):
        self.t = Turnier.objects.create(
            name="Cup", datum=date(2026, 11, 14), beginn=time(9, 0), ort="Halle", max_teams=20,
            meldeschluss=datetime(2026, 10, 31, tzinfo=timezone.utc), modus=Turnier.Modus.GRUPPEN_KO,
        )

    def plan(self, anzahl_teams, gruppen=None):
        for i in range(anzahl_teams):
            Team.objects.create(turnier=self.t, name=f"Team {i:02d}", kapitaen_name="K", kapitaen_email="k@example.de",
                                status=Team.Status.BESTAETIGT, bezahlt=True)
        spielplan.erzeugen(self.t, anzahl_gruppen=gruppen, zufall=random.Random(5))

    def rangfolge(self, name):
        """Erwartete Tabelle: In jedem Spiel gewinnt das Team mit der kleineren ID."""
        return list(self.t.gruppen.get(name=name).teams.order_by("pk"))

    def beenden(self, spiel, sieger=None, ballpunkte=None):
        sieger = sieger or min((spiel.team_a, spiel.team_b), key=lambda t: t.pk)
        spiel.status = Spiel.Status.BEENDET
        spiel.saetze_a, spiel.saetze_b = (2, 0) if sieger == spiel.team_a else (0, 2)
        if ballpunkte:  # (Punkte Sieger, Punkte Verlierer)
            spiel.punkte_a, spiel.punkte_b = ballpunkte if sieger == spiel.team_a else ballpunkte[::-1]
        spiel.save()
        return ko.aktualisieren(self.t)

    def gruppe_beenden(self, name, sieger=None):
        """Alle offenen Spiele der Gruppe beenden; sieger: optional {frozenset(paar): team}."""
        meldungen = []
        for s in self.t.spiele.filter(gruppe__name=name, status=Spiel.Status.GEPLANT):
            paar = frozenset((s.team_a, s.team_b))
            meldungen += self.beenden(s, sieger=(sieger or {}).get(paar))
        return meldungen

    def ringschluss(self, x, y, z):
        """x schlägt y, y schlägt z, z schlägt x – alles gleich, auch im direkten Vergleich."""
        return {frozenset((x, y)): x, frozenset((y, z)): y, frozenset((x, z)): z}

    def ko(self, phase, nummer=1):
        return [s for s in spielplan.mit_titeln(self.t) if s.phase == phase][nummer - 1]

    def admin_speichern(self, spiel, **werte):
        """Spiel über das Admin-Formular speichern (wie die Orga)."""
        daten = {
            "turnier": self.t.pk, "phase": spiel.phase, "gruppe": spiel.gruppe_id or "", "runde": spiel.runde,
            "uhrzeit": spiel.uhrzeit.strftime("%H:%M"), "feld": spiel.feld, "status": spiel.status,
            "team_a": spiel.team_a_id or "", "platzhalter_a": spiel.platzhalter_a,
            "team_b": spiel.team_b_id or "", "platzhalter_b": spiel.platzhalter_b,
            "schiri_team": spiel.schiri_team_id or "", "saetze_a": "", "saetze_b": "", "punkte_a": "", "punkte_b": "",
        }
        daten.update(werte)
        return self.client.post(reverse("admin:tournament_spiel_change", args=[spiel.pk]), daten, follow=True)

    def test_zwei_gruppen_halbfinale_dann_finale(self):
        self.plan(8)
        self.assertIsNone(self.ko(Phase.HALBFINALE).team_a)

        self.gruppe_beenden("A")  # nur Gruppe A fertig
        hf1 = self.ko(Phase.HALBFINALE, 1)
        self.assertEqual((hf1.platzhalter_a, hf1.team_a), ("1. Gruppe A", self.rangfolge("A")[0]))
        self.assertIsNone(hf1.team_b)  # "2. Gruppe B" noch offen

        meldungen = self.gruppe_beenden("B")
        a, b = self.rangfolge("A"), self.rangfolge("B")
        hf1, hf2 = self.ko(Phase.HALBFINALE, 1), self.ko(Phase.HALBFINALE, 2)
        self.assertEqual((hf1.team_a, hf1.team_b), (a[0], b[1]))
        self.assertEqual((hf2.team_a, hf2.team_b), (b[0], a[1]))
        self.assertTrue(any(m.startswith("Halbfinale 1:") for m in meldungen))
        self.assertIsNone(self.ko(Phase.FINALE).team_a)
        self.assertEqual(ko.offene_entscheidungen(self.t), [])

        self.beenden(hf1, sieger=hf1.team_b)
        self.beenden(hf2, sieger=hf2.team_a)
        finale, platz3 = self.ko(Phase.FINALE), self.ko(Phase.PLATZ_3)
        self.assertEqual((finale.team_a, finale.team_b), (b[1], b[0]))
        self.assertEqual((platz3.team_a, platz3.team_b), (a[0], a[1]))

    def test_korrektur_aendert_offene_ko_spiele_aber_nicht_beendete(self):
        self.plan(8)
        self.gruppe_beenden("A")
        self.gruppe_beenden("B")
        a = self.rangfolge("A")
        # Korrektur: Der Zweite aus A hat das direkte Duell gegen den Ersten doch gewonnen
        duell = self.t.spiele.get(gruppe__name="A", team_a__in=a[:2], team_b__in=a[:2])
        self.beenden(duell, sieger=a[1])
        hf1, hf2 = self.ko(Phase.HALBFINALE, 1), self.ko(Phase.HALBFINALE, 2)
        self.assertEqual((hf1.team_a, hf2.team_b), (a[1], a[0]))

        self.beenden(hf1)  # Halbfinale 1 ist gespielt
        self.beenden(duell, sieger=a[0])  # erneute Korrektur
        hf1, hf2 = self.ko(Phase.HALBFINALE, 1), self.ko(Phase.HALBFINALE, 2)
        self.assertEqual(hf1.team_a, a[1])  # beendetes Spiel bleibt
        self.assertEqual(hf2.team_b, a[1])  # offenes Spiel folgt der Tabelle

    def test_drei_gruppen_bester_zweiter_nach_schnitt(self):
        self.plan(11, gruppen=3)  # Gruppen mit 4, 4 und 3 Teams
        vierer = [n for n in "ABC" if self.t.gruppen.get(name=n).teams.count() == 4]
        for name in "ABC":
            if name != vierer[0]:
                self.gruppe_beenden(name)
        self.assertIsNone(self.ko(Phase.HALBFINALE, 1).team_b)  # erst, wenn alle Gruppen fertig sind
        # In der ersten Vierergruppe gewinnt der Zweite sein Spiel gegen den Dritten deutlicher
        zweiter, dritter = self.rangfolge(vierer[0])[1:3]
        for s in self.t.spiele.filter(gruppe__name=vierer[0]):
            self.beenden(s, ballpunkte=(50, 20) if {s.team_a, s.team_b} == {zweiter, dritter} else None)
        hf1, hf2 = self.ko(Phase.HALBFINALE, 1), self.ko(Phase.HALBFINALE, 2)
        # 2 Siege aus 3 Spielen schlägt 1 aus 2 (Dreiergruppe); zwischen den Vierergruppen: Ballpunkte pro Spiel
        self.assertEqual(hf1.team_b, zweiter)
        self.assertEqual((hf2.team_a, hf2.team_b), (self.rangfolge("B")[0], self.rangfolge("C")[0]))
        self.assertEqual(ko.offene_entscheidungen(self.t), [])

    def test_bester_zweiter_bei_gleichstand_bleibt_offen(self):
        self.plan(12, gruppen=3)  # drei Vierergruppen, alle Zweiten exakt gleich
        meldungen = []
        for name in "ABC":
            meldungen += self.gruppe_beenden(name)
        hf1 = self.ko(Phase.HALBFINALE, 1)
        self.assertIsNone(hf1.team_b)
        self.assertIsNotNone(hf1.team_a)  # der Gruppensieger steht trotzdem fest
        [entscheidung] = ko.offene_entscheidungen(self.t)
        self.assertEqual(entscheidung.platzhalter, "Bester Gruppenzweiter")
        self.assertEqual(set(entscheidung.teams), {self.rangfolge(n)[1] for n in "ABC"})
        self.assertTrue(any("Entscheidungssatz" in m and "Halbfinale 1" in m for m in meldungen))

    def test_vier_gruppen_viertelfinale_dann_halbfinale(self):
        self.plan(16, gruppen=4)
        for name in "ABCD":
            self.gruppe_beenden(name)
        vf = [self.ko(Phase.VIERTELFINALE, n) for n in range(1, 5)]
        self.assertEqual((vf[0].team_a, vf[0].team_b), (self.rangfolge("A")[0], self.rangfolge("B")[1]))
        self.assertEqual((vf[3].team_a, vf[3].team_b), (self.rangfolge("D")[0], self.rangfolge("C")[1]))
        for spiel in vf:
            self.beenden(spiel, sieger=spiel.team_a)
        hf1 = self.ko(Phase.HALBFINALE, 1)
        self.assertEqual((hf1.team_a, hf1.team_b), (vf[0].team_a, vf[2].team_a))

    def test_gleichstand_in_der_gruppe_bleibt_offen(self):
        self.plan(6)  # 2 Gruppen à 3
        self.gruppe_beenden("B")
        x, y, z = self.rangfolge("A")
        meldungen = self.gruppe_beenden("A", sieger=self.ringschluss(x, y, z))
        hf1, hf2 = self.ko(Phase.HALBFINALE, 1), self.ko(Phase.HALBFINALE, 2)
        self.assertIsNone(hf1.team_a)  # "1. Gruppe A" offen, nicht alphabetisch vergeben
        self.assertIsNone(hf2.team_b)  # "2. Gruppe A" ebenso
        self.assertIsNotNone(hf1.team_b)  # Gruppe B ist eindeutig
        texte = [e.text for e in ko.offene_entscheidungen(self.t)]
        self.assertEqual(len(texte), 2)
        self.assertTrue(all("Entscheidungssatz" in t and x.name in t and z.name in t for t in texte))
        self.assertTrue(any("1. Gruppe A" in m for m in meldungen))

    def test_gleichstand_nur_um_platz_zwei(self):
        self.plan(8)  # 2 Gruppen à 4
        self.gruppe_beenden("B")
        a1, a2, a3, a4 = self.rangfolge("A")
        # a1 gewinnt alles; a2, a3, a4 im Ringschluss -> Platz 2 offen, Platz 1 klar
        sieger = self.ringschluss(a2, a3, a4)
        sieger.update({frozenset((a1, t)): a1 for t in (a2, a3, a4)})
        self.gruppe_beenden("A", sieger=sieger)
        hf1, hf2 = self.ko(Phase.HALBFINALE, 1), self.ko(Phase.HALBFINALE, 2)
        self.assertEqual(hf1.team_a, a1)
        self.assertIsNone(hf2.team_b)
        [entscheidung] = ko.offene_entscheidungen(self.t)
        self.assertEqual(set(entscheidung.teams), {a2, a3, a4})

    def test_entscheidung_von_hand_im_admin(self):
        self.plan(6)
        self.gruppe_beenden("B")
        x, y, z = self.rangfolge("A")
        self.gruppe_beenden("A", sieger=self.ringschluss(x, y, z))
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))

        r = self.client.get(f"{reverse('orga_spielplan')}?turnier={self.t.pk}")
        hf1 = self.ko(Phase.HALBFINALE, 1)
        self.assertContains(r, "Offene Entscheidungen")
        self.assertContains(r, reverse("admin:tournament_spiel_change", args=[hf1.pk]))

        # Entscheidungssatz gespielt, z gewinnt Gruppe A -> im Admin eintragen und Platzhalter leeren
        r = self.admin_speichern(hf1, team_a=z.pk, platzhalter_a="")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Platzhalter leeren")  # Hinweis im Formular bzw. offene Entscheidung
        hf1.refresh_from_db()
        self.assertEqual(hf1.team_a, z)
        self.assertEqual([e.platzhalter for e in ko.offene_entscheidungen(self.t)], ["2. Gruppe A"])

    def test_ergebnis_im_admin_befuellt_ko_runde(self):
        self.plan(6)
        self.gruppe_beenden("A")
        offene = list(self.t.spiele.filter(gruppe__name="B", status=Spiel.Status.GEPLANT))
        for s in offene[:-1]:
            self.beenden(s)
        letztes = offene[-1]
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))
        a_gewinnt = letztes.team_a.pk < letztes.team_b.pk
        r = self.admin_speichern(letztes, status="beendet", saetze_a=2 if a_gewinnt else 0, saetze_b=0 if a_gewinnt else 2)
        self.assertContains(r, "Halbfinale 1:")
        hf1 = self.ko(Phase.HALBFINALE, 1)
        self.assertEqual((hf1.team_a, hf1.team_b), (self.rangfolge("A")[0], self.rangfolge("B")[1]))

    def test_jeder_gegen_jeden_hat_keine_ko_runde(self):
        self.t.modus = Turnier.Modus.JEDER_GEGEN_JEDEN
        self.plan(4)
        meldungen = []
        for s in self.t.spiele.all():
            meldungen += self.beenden(s)
        self.assertEqual(meldungen, [])

    def test_meldung_auf_der_ergebnis_seite(self):
        self.plan(6)
        self.gruppe_beenden("A")
        letztes = self.t.spiele.filter(gruppe__name="B").order_by("uhrzeit").last()
        for s in self.t.spiele.filter(gruppe__name="B").exclude(pk=letztes.pk):
            self.beenden(s)
        self.client.force_login(User.objects.create_superuser("orga", "o@example.de", "x"))
        a_gewinnt = letztes.team_a.pk < letztes.team_b.pk
        r = self.client.post(reverse("orga_ergebnis", args=[letztes.pk]),
                             {"saetze_a": "2" if a_gewinnt else "0", "saetze_b": "0" if a_gewinnt else "2"}, follow=True)
        self.assertContains(r, "Halbfinale 1:")
