"""Testturnier für den Probelauf anlegen: python manage.py testturnier [--teams 10] [--spielplan]"""

import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from tournament import spielplan
from tournament.models import Spieler, Team, Turnier

TEAMNAMEN = [
    "Bit Blockers", "Null Pointer Smash", "Satzweise Genial", "Pritsch Perfect", "Netzwerk",
    "Block Chain", "Lob & Order", "Ace of Bases", "Baggerfahrer", "Mittelblock Mafia",
    "Smash Bros", "Aufschlag Ahoi", "Die Netzroller", "Libero Liebe", "Pritschmeister", "Return 0",
]
VORNAMEN = ["Lena", "Max", "Kim", "Jonas", "Mia", "Paul", "Emma", "Noah", "Lea", "Finn", "Sara", "Tom"]
NACHNAMEN = ["Hoffmann", "Meier", "Nguyen", "Schulz", "Wolf", "Becker", "Krüger", "Yilmaz", "Lange", "Weber"]


class Command(BaseCommand):
    help = "Legt ein Testturnier mit bestätigten und bezahlten Teams an (für den Probelauf)."

    def add_arguments(self, parser):
        parser.add_argument("--teams", type=int, default=10, help="Bezahlte Teams (Standard: 10)")
        parser.add_argument("--modus", choices=Turnier.Modus.values, default=Turnier.Modus.GRUPPEN_KO)
        parser.add_argument("--zaehlmodus", choices=Turnier.Zaehlmodus.values, default=Turnier.Zaehlmodus.SAETZE)
        parser.add_argument("--spielplan", action="store_true", dest="mit_spielplan",
                            help="Spielplan erzeugen und veröffentlichen")

    @transaction.atomic
    def handle(self, *args, teams, modus, zaehlmodus, mit_spielplan, **options):
        if not 2 <= teams <= len(TEAMNAMEN) - 2:
            raise CommandError(f"--teams muss zwischen 2 und {len(TEAMNAMEN) - 2} liegen.")
        jetzt = timezone.localtime()
        beginn = (jetzt + timedelta(minutes=30 - jetzt.minute % 30)).time().replace(second=0, microsecond=0)
        turnier = Turnier.objects.create(
            name=f"Probelauf {jetzt:%d.%m.%Y %H:%M}", datum=jetzt.date(), beginn=beginn, ort="Campus-Halle",
            startgebuehr_eur=20, meldeschluss=jetzt + timedelta(days=1), max_teams=teams + 2,
            anmeldung_offen=True, modus=modus, zaehlmodus=zaehlmodus,
            zahlungsinfo="Testturnier – bitte nichts überweisen.",
        )
        zufall = random.Random()
        # Teams mit Startplatz: die ersten `teams` bezahlt, zwei weitere offen (zum Testen des Zahlungs-Trackings)
        for i, name in enumerate(TEAMNAMEN[:teams + 2]):
            team = Team.objects.create(
                turnier=turnier, name=name, kapitaen_name=f"Kapitän {i + 1}",
                kapitaen_email=f"team{i + 1}@example.invalid", bezahlt=i < teams,
                zahlungsart=Team.Zahlungsart.BAR if i < teams else "",
            )
            for _ in range(6):
                Spieler.objects.create(team=team, vorname=zufall.choice(VORNAMEN), nachname=zufall.choice(NACHNAMEN))

        self.stdout.write(f"Turnier „{turnier}“ (id {turnier.pk}) mit {teams} bezahlten und 2 offenen Teams angelegt.")
        if mit_spielplan:
            spielplan.erzeugen(turnier)
            turnier.spielplan_veroeffentlicht = True
            turnier.save(update_fields=["spielplan_veroeffentlicht"])
            self.stdout.write(f"Spielplan erzeugt und veröffentlicht: {turnier.spiele.count()} Spiele ab {beginn:%H:%M}.")
        self.stdout.write(self.style.SUCCESS("Fertig. Nach dem Probelauf das Turnier im Admin löschen."))
