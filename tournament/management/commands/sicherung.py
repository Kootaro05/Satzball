"""Sicherung der SQLite-Datenbank: python manage.py sicherung [--behalten 14]

Nutzt die Backup-Funktion von SQLite, damit die Kopie auch bei laufendem Server konsistent ist.
Die Sicherungen liegen in data/sicherungen/ (im Container /app/data/sicherungen, also im Volume).
"""

import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Sichert die Datenbank nach data/sicherungen/ und behält die neuesten Sicherungen."

    def add_arguments(self, parser):
        parser.add_argument("--behalten", type=int, default=14, help="Anzahl Sicherungen, die bleiben (Standard: 14)")

    def handle(self, *args, behalten, **options):
        ordner = settings.DATA_DIR / "sicherungen"
        ordner.mkdir(exist_ok=True)
        ziel = ordner / f"db-{timezone.localtime():%Y-%m-%d-%H%M%S}.sqlite3"

        connection.ensure_connection()
        with sqlite3.connect(ziel) as kopie:
            connection.connection.backup(kopie)
        kopie.close()

        alte = sorted(ordner.glob("db-*.sqlite3"))[:-behalten] if behalten > 0 else []
        for datei in alte:
            datei.unlink()
        self.stdout.write(self.style.SUCCESS(f"Gesichert: {ziel}"))
        if alte:
            self.stdout.write(f"{len(alte)} ältere Sicherung(en) entfernt.")
