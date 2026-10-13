"""Datenmodell laut docs/konzept.md: Turnier, Team, Spieler, Gruppe, Spiel.

Die Tabelle (Platzierung) wird nicht gespeichert, sondern aus beendeten Spielen berechnet.
"""

import secrets

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# Darunter kann ein Team nicht antreten. min_spieler am Turnier ist nur eine Empfehlung.
MIN_SPIELER = 2


def neuer_edit_token():
    # 24 Zufallsbytes -> 32 URL-sichere Zeichen
    return secrets.token_urlsafe(24)


class Turnier(models.Model):
    class Modus(models.TextChoices):
        JEDER_GEGEN_JEDEN = "jeder_gegen_jeden", "Jeder gegen jeden"
        GRUPPEN_KO = "gruppen_ko", "Gruppen + K.-o."

    class Zaehlmodus(models.TextChoices):
        SAETZE = "saetze", "Satz-Modus"
        PUNKTE = "punkte", "Punkte-Modus (ohne Sätze, mehr Punkte gewinnt)"

    class Gewinnsaetze(models.IntegerChoices):
        BEST_OF_1 = 1, "Best of 1"
        BEST_OF_3 = 2, "Best of 3"
        BEST_OF_5 = 3, "Best of 5"

    name = models.CharField(max_length=100)
    oeffentlich = models.BooleanField(
        "öffentlich sichtbar", default=False,
        help_text="Erst dann sehen Besucher das Turnier (Startseite, Turnierliste, Anmeldung). "
                  "Entwürfe und Testturniere ausgeschaltet lassen.",
    )
    datum = models.DateField()
    beginn = models.TimeField(null=True, blank=True, help_text="Startzeit am Spieltag, z. B. 9:30.")
    ort = models.CharField(max_length=200)
    startgebuehr_eur = models.DecimalField("Startgebühr (€)", max_digits=6, decimal_places=2, default=0)
    zahlungsinfo = models.TextField(
        blank=True, help_text="Wie gezahlt wird (IBAN, PayPal, Bar-Termine). Erscheint nach der Anmeldung.",
    )
    meldeschluss = models.DateTimeField()
    max_teams = models.PositiveSmallIntegerField("max. Teams")
    min_spieler = models.PositiveSmallIntegerField(
        "empfohlene Spielerzahl", default=6,
        help_text=f"Weniger Spieler sind erlaubt (Hinweis im Formular); Pflicht sind mindestens {MIN_SPIELER}.",
    )
    max_spieler = models.PositiveSmallIntegerField("max. Spieler pro Team", default=10)
    anmeldung_offen = models.BooleanField("Anmeldung offen", default=False)
    modus = models.CharField(max_length=20, choices=Modus.choices, default=Modus.JEDER_GEGEN_JEDEN)
    anzahl_felder = models.PositiveSmallIntegerField("Anzahl Felder", default=2)
    slot_minuten = models.PositiveSmallIntegerField("Slotlänge (min)", default=20)
    spielplan_veroeffentlicht = models.BooleanField("Spielplan veröffentlicht", default=False)
    warteliste_automatisch = models.BooleanField(
        "Warteliste automatisch nachrücken lassen", default=False,
        help_text="Wird ein Platz frei, rückt das erste Team der Warteliste nach und bekommt eine Mail. "
                  "Sonst entscheidet die Orga über die Aktion „Von der Warteliste nachrücken“.",
    )
    teamdaten_geloescht_am = models.DateField(
        "Teamdaten gelöscht am", null=True, blank=True, editable=False,
        help_text="Spieler und Kapitänsdaten sind gelöscht; Teamnamen und Ergebnisse bleiben.",
    )
    zaehlmodus = models.CharField("Zählmodus", max_length=10, choices=Zaehlmodus.choices, default=Zaehlmodus.SAETZE)
    gewinnsaetze = models.PositiveSmallIntegerField(
        "Gewinnsätze", choices=Gewinnsaetze.choices, default=Gewinnsaetze.BEST_OF_3,
        help_text="Nur im Satz-Modus.",
    )
    punkte_pro_satz = models.PositiveSmallIntegerField(
        "Punkte pro Satz", default=25, help_text="Nur im Satz-Modus.",
    )
    punkte_entscheidungssatz = models.PositiveSmallIntegerField(
        "Punkte Entscheidungssatz", default=15, help_text="Nur im Satz-Modus.",
    )

    class Meta:
        verbose_name = "Turnier"
        verbose_name_plural = "Turniere"
        ordering = ["-datum"]

    def __str__(self):
        return self.name

    @classmethod
    def aktuelles(cls, nur_oeffentliche=False):
        """Das nächste anstehende Turnier, sonst das zuletzt gelaufene.
        Öffentliche Seiten fragen mit nur_oeffentliche=True, die Orga sieht alle."""
        turniere = cls.objects.filter(oeffentlich=True) if nur_oeffentliche else cls.objects.all()
        heute = timezone.localdate()
        return turniere.filter(datum__gte=heute).order_by("datum").first() or turniere.first()

    @property
    def vorbei(self):
        return self.datum < timezone.localdate()

    @property
    def meldeschluss_vorbei(self):
        return timezone.now() >= self.meldeschluss

    @property
    def anmeldung_moeglich(self):
        return self.anmeldung_offen and not self.meldeschluss_vorbei

    @property
    def tage_bis_meldeschluss(self):
        return max((timezone.localtime(self.meldeschluss).date() - timezone.localdate()).days, 0)

    @property
    def belegte_plaetze(self):
        return self.teams.filter(status__in=Team.STARTPLATZ_STATUS).count()

    @property
    def freie_plaetze(self):
        return max(self.max_teams - self.belegte_plaetze, 0)

    def zahlungsuebersicht(self):
        """Kennzahlen für die Orga (Screen 06). Erwartet wird die Gebühr aller Teams mit Startplatz."""
        teams = list(self.teams.only("status", "bezahlt"))
        startplatz = [t for t in teams if t.hat_startplatz]
        bezahlt = [t for t in teams if t.bezahlt]
        return {
            "eingegangen": self.startgebuehr_eur * len(bezahlt),
            "erwartet": self.startgebuehr_eur * len(startplatz),
            "unbezahlt": sum(1 for t in startplatz if not t.bezahlt),
            "warteliste": sum(1 for t in teams if t.status == Team.Status.WARTELISTE),
        }

    def teamdaten_loeschen(self):
        """Datenschutz: Spieler, Kapitänsdaten und Notizen löschen, Bearbeitungslinks ungültig machen.
        Auch das Änderungsprotokoll des Admins zu diesen Teams und Spielern (enthält Namen) wird gelöscht.
        Teamnamen und Ergebnisse bleiben."""
        from django.contrib.admin.models import LogEntry
        from django.contrib.contenttypes.models import ContentType

        spieler = Spieler.objects.filter(team__turnier=self)
        for model, ids in [(Team, self.teams.values_list("pk", flat=True)), (Spieler, spieler.values_list("pk", flat=True))]:
            LogEntry.objects.filter(
                content_type=ContentType.objects.get_for_model(model), object_id__in=[str(pk) for pk in ids],
            ).delete()
        spieler.delete()
        for team in self.teams.all():
            Team.objects.filter(pk=team.pk).update(
                kapitaen_name="", kapitaen_email="", notiz="", edit_token=neuer_edit_token(),
            )
        self.teamdaten_geloescht_am = timezone.localdate()
        self.save(update_fields=["teamdaten_geloescht_am"])

    def clean(self):
        if self.min_spieler is not None and self.min_spieler < MIN_SPIELER:
            raise ValidationError({"min_spieler": f"Mindestens {MIN_SPIELER} – weniger Spieler sind nie erlaubt."})
        if self.max_spieler is not None and self.max_spieler < MIN_SPIELER:
            raise ValidationError({"max_spieler": f"Mindestens {MIN_SPIELER}."})
        if self.min_spieler is not None and self.max_spieler is not None and self.min_spieler > self.max_spieler:
            raise ValidationError({"max_spieler": "Muss mindestens so groß sein wie die empfohlene Spielerzahl."})


class Gruppe(models.Model):
    turnier = models.ForeignKey(Turnier, on_delete=models.CASCADE, related_name="gruppen")
    name = models.CharField(max_length=20, help_text="z. B. A, B, …")

    class Meta:
        verbose_name = "Gruppe"
        verbose_name_plural = "Gruppen"
        ordering = ["turnier", "name"]
        constraints = [
            models.UniqueConstraint(fields=["turnier", "name"], name="gruppe_name_eindeutig_pro_turnier"),
        ]

    def __str__(self):
        return f"Gruppe {self.name}"


class TeamQuerySet(models.QuerySet):
    def im_spielplan(self):
        """Nur bestätigte und bezahlte Teams kommen in den Spielplan."""
        return self.filter(status=Team.Status.BESTAETIGT, bezahlt=True)


class Team(models.Model):
    class Status(models.TextChoices):
        ANGEMELDET = "angemeldet", "Angemeldet"
        BESTAETIGT = "bestaetigt", "Bestätigt"
        WARTELISTE = "warteliste", "Warteliste"
        ABGESAGT = "abgesagt", "Abgesagt"

    class Zahlungsart(models.TextChoices):
        BAR = "bar", "Bar"
        UEBERWEISUNG = "ueberweisung", "Überweisung"
        PAYPAL = "paypal", "PayPal"

    turnier = models.ForeignKey(Turnier, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField("Teamname", max_length=100)
    # Leer nur nach dem Löschen der Teamdaten (Datenschutz); im Anmeldeformular Pflicht.
    kapitaen_name = models.CharField("Kapitän", max_length=100, blank=True)
    kapitaen_email = models.EmailField("E-Mail Kapitän", blank=True)
    edit_token = models.CharField(max_length=64, unique=True, default=neuer_edit_token, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ANGEMELDET)
    bezahlt = models.BooleanField(default=False)
    bezahlt_am = models.DateField("bezahlt am", null=True, blank=True)
    zahlungsart = models.CharField(max_length=20, choices=Zahlungsart.choices, blank=True)
    notiz = models.TextField(blank=True)
    gruppe = models.ForeignKey(Gruppe, on_delete=models.SET_NULL, null=True, blank=True, related_name="teams")
    angemeldet_am = models.DateTimeField("angemeldet am", auto_now_add=True)

    # Teams mit diesem Status belegen einen der max_teams Plätze.
    STARTPLATZ_STATUS = [Status.ANGEMELDET, Status.BESTAETIGT]
    # Wer zuerst kommt: Anmeldezeit, bei gleicher Zeit (z. B. Altdaten) die laufende Nummer
    REIHENFOLGE = ["angemeldet_am", "pk"]

    objects = TeamQuerySet.as_manager()

    class Meta:
        verbose_name = "Team"
        verbose_name_plural = "Teams"
        ordering = ["turnier", "name"]
        constraints = [
            models.UniqueConstraint(fields=["turnier", "name"], name="teamname_eindeutig_pro_turnier"),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Bezahlt heißt bestätigt (Entscheidung Orga). Warteliste und Absage bleiben unberührt.
        if self.bezahlt:
            self.bezahlt_am = self.bezahlt_am or timezone.localdate()
            if self.status == self.Status.ANGEMELDET:
                self.status = self.Status.BESTAETIGT
        else:
            self.bezahlt_am = None
            if self.status == self.Status.BESTAETIGT:
                self.status = self.Status.ANGEMELDET
        super().save(*args, **kwargs)

    @property
    def hat_startplatz(self):
        return self.status in self.STARTPLATZ_STATUS

    @property
    def startplatz_nr(self):
        """Laufende Nummer unter den Teams mit Startplatz (in Anmelde-Reihenfolge)."""
        if not self.hat_startplatz:
            return None
        return self._vor_mir().filter(status__in=self.STARTPLATZ_STATUS).count() + 1

    @property
    def wartelisten_platz(self):
        """Platz auf der Warteliste (1 = rückt als Nächstes nach), sonst None."""
        if self.status != self.Status.WARTELISTE:
            return None
        return self._vor_mir().filter(status=self.Status.WARTELISTE).count() + 1

    def _vor_mir(self):
        """Teams desselben Turniers, die sich früher angemeldet haben."""
        return Team.objects.filter(turnier_id=self.turnier_id).filter(
            models.Q(angemeldet_am__lt=self.angemeldet_am) | models.Q(angemeldet_am=self.angemeldet_am, pk__lt=self.pk)
        )

    def clean(self):
        if self.gruppe_id and self.turnier_id and self.gruppe.turnier_id != self.turnier_id:
            raise ValidationError({"gruppe": "Die Gruppe gehört zu einem anderen Turnier."})


class Spieler(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="spieler")
    vorname = models.CharField(max_length=100)
    nachname = models.CharField(max_length=100)
    studiengang = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "Spieler"
        verbose_name_plural = "Spieler"
        ordering = ["team", "nachname", "vorname"]

    def __str__(self):
        return f"{self.vorname} {self.nachname}"


class Spiel(models.Model):
    class Status(models.TextChoices):
        GEPLANT = "geplant", "Geplant"
        BEENDET = "beendet", "Beendet"

    class Phase(models.TextChoices):
        GRUPPE = "gruppe", "Gruppenspiel"
        VIERTELFINALE = "viertelfinale", "Viertelfinale"
        HALBFINALE = "halbfinale", "Halbfinale"
        PLATZ_3 = "platz_3", "Spiel um Platz 3"
        FINALE = "finale", "Finale"

    turnier = models.ForeignKey(Turnier, on_delete=models.CASCADE, related_name="spiele")
    gruppe = models.ForeignKey(
        Gruppe, on_delete=models.CASCADE, null=True, blank=True, related_name="spiele",
        help_text="Leer bei K.-o.-Spielen.",
    )
    phase = models.CharField(max_length=20, choices=Phase.choices, default=Phase.GRUPPE)
    runde = models.PositiveSmallIntegerField(default=1)
    feld = models.PositiveSmallIntegerField(default=1)
    uhrzeit = models.TimeField(null=True, blank=True)
    # Wird ein Team gelöscht, bleibt das Spiel ohne Team stehen (Umplanen: siehe CLAUDE.md).
    team_a = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="Team A",
    )
    team_b = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="Team B",
    )
    # Für K.-o.-Spiele, solange die Teams noch nicht feststehen, z. B. "1. Gruppe B".
    platzhalter_a = models.CharField("Platzhalter A", max_length=50, blank=True)
    platzhalter_b = models.CharField("Platzhalter B", max_length=50, blank=True)
    saetze_a = models.PositiveSmallIntegerField("Sätze A", null=True, blank=True)
    saetze_b = models.PositiveSmallIntegerField("Sätze B", null=True, blank=True)
    # Satz-Modus: Ballpunkte gesamt (optional). Punkte-Modus: Punkte des einen Satzes.
    punkte_a = models.PositiveSmallIntegerField("Punkte A", null=True, blank=True)
    punkte_b = models.PositiveSmallIntegerField("Punkte B", null=True, blank=True)
    schiri_team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="Schiri",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.GEPLANT)

    class Meta:
        verbose_name = "Spiel"
        verbose_name_plural = "Spiele"
        ordering = ["turnier", "uhrzeit", "feld"]

    def __str__(self):
        a = self.team_a or self.platzhalter_a or "?"
        b = self.team_b or self.platzhalter_b or "?"
        return f"{a} – {b}"

    @property
    def sieger(self):
        """Siegerteam eines beendeten Spiels, sonst None."""
        if self.status != self.Status.BEENDET:
            return None
        if self.turnier.zaehlmodus == Turnier.Zaehlmodus.SAETZE:
            a, b = self.saetze_a, self.saetze_b
        else:
            a, b = self.punkte_a, self.punkte_b
        if a is None or b is None or a == b:
            return None
        return self.team_a if a > b else self.team_b

    def clean(self):
        fehler = {}
        teams = [t for t in (self.team_a, self.team_b, self.schiri_team) if t]
        if any(t.turnier_id != self.turnier_id for t in teams):
            fehler["__all__"] = "Alle Teams müssen zum Turnier des Spiels gehören."
        if self.team_a_id and self.team_a_id == self.team_b_id:
            fehler["team_b"] = "Ein Team kann nicht gegen sich selbst spielen."
        if self.schiri_team_id and self.schiri_team_id in (self.team_a_id, self.team_b_id):
            fehler["schiri_team"] = "Das Schiri-Team darf nicht selbst spielen."
        if self.gruppe_id and self.gruppe.turnier_id != self.turnier_id:
            fehler["gruppe"] = "Die Gruppe gehört zu einem anderen Turnier."
        if self.gruppe_id and self.phase != self.Phase.GRUPPE:
            fehler["gruppe"] = "K.-o.-Spiele gehören zu keiner Gruppe."
        if self.status == self.Status.BEENDET and not fehler:
            fehler.update(self._ergebnis_fehler())
        if fehler:
            raise ValidationError(fehler)

    def _ergebnis_fehler(self):
        if not (self.team_a_id and self.team_b_id):
            return {"status": "Ein beendetes Spiel braucht beide Teams."}
        if self.turnier.zaehlmodus == Turnier.Zaehlmodus.SAETZE:
            ziel = self.turnier.gewinnsaetze
            a, b = self.saetze_a, self.saetze_b
            if a is None or b is None:
                return {"saetze_a": "Bitte die Sätze beider Teams eintragen."}
            if max(a, b) != ziel or min(a, b) >= ziel:
                return {"saetze_a": f"Genau ein Team muss {ziel} Sätze gewinnen."}
        else:
            a, b = self.punkte_a, self.punkte_b
            if a is None or b is None:
                return {"punkte_a": "Bitte die Punkte beider Teams eintragen."}
            if a == b:
                return {"punkte_a": "Im Punkte-Modus gibt es kein Unentschieden."}
        return {}
