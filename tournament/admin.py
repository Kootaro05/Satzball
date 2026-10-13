from collections import defaultdict

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.template.response import TemplateResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html

from . import ko, spielplan, warteliste
from .models import Gruppe, Spiel, Spieler, Team, Turnier

def _mail_hinweis(team):
    """Für Meldungen: ging die Mail an das Team wirklich raus?"""
    return "Mail verschickt" if getattr(team, "mail_verschickt", False) else "keine Mail – E-Mail-Adresse fehlt"


admin.site.site_header = "Satzball – Orga"
admin.site.site_title = "Satzball"
admin.site.index_title = "Turnierverwaltung"


class GruppeInline(admin.TabularInline):
    model = Gruppe
    extra = 0


@admin.register(Turnier)
class TurnierAdmin(admin.ModelAdmin):
    list_display = [
        "name", "datum", "oeffentlich", "ort", "modus", "zaehlmodus", "anmeldung_offen", "anzahl_teams", "max_teams",
        "spielplan_link",
    ]
    list_filter = ["oeffentlich", "anmeldung_offen", "modus", "zaehlmodus"]
    search_fields = ["name", "ort"]
    date_hierarchy = "datum"
    inlines = [GruppeInline]
    actions = ["teamdaten_loeschen"]
    readonly_fields = ["teamdaten_geloescht_am"]

    class Media:
        js = ["js/admin_turnier.js"]  # Satz-Felder im Punkte-Modus ausgrauen
    fieldsets = [
        (None, {"fields": ["name", "oeffentlich", "datum", "beginn", "ort", "startgebuehr_eur", "zahlungsinfo"]}),
        ("Anmeldung", {"fields": [
            "anmeldung_offen", "meldeschluss", "max_teams", "warteliste_automatisch", "min_spieler", "max_spieler",
        ]}),
        ("Modus", {"fields": ["modus", "anzahl_felder", "slot_minuten", "spielplan_veroeffentlicht"]}),
        ("Zählweise", {"fields": ["zaehlmodus", "gewinnsaetze", "punkte_pro_satz", "punkte_entscheidungssatz"]}),
        ("Datenschutz", {"fields": ["teamdaten_geloescht_am"]}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_anzahl_teams=Count("teams"))

    @admin.display(description="Teams", ordering="_anzahl_teams")
    def anzahl_teams(self, obj):
        return obj._anzahl_teams

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Mehr Plätze oder Haken gerade gesetzt: Warteliste sofort nachrücken lassen
        for team in warteliste.auffuellen(obj, request):
            self.message_user(request, f"{team} ist automatisch von der Warteliste nachgerückt ({_mail_hinweis(team)}).",
                              messages.SUCCESS)

    @admin.action(description="Teamdaten löschen (Datenschutz)")
    def teamdaten_loeschen(self, request, queryset):
        """Erst nach dem Turniertag und nur nach Bestätigung."""
        heute = timezone.localdate()
        zu_frueh = [t for t in queryset if t.datum >= heute]
        for turnier in zu_frueh:
            self.message_user(request, f"{turnier}: erst nach dem Turniertag möglich.", messages.WARNING)
        turniere = [t for t in queryset if t.datum < heute]
        if not turniere:
            return None
        if request.POST.get("bestaetigt") != "ja":
            return TemplateResponse(request, "admin/tournament/turnier/teamdaten_loeschen.html", {
                **self.admin_site.each_context(request),
                "title": "Teamdaten löschen",
                "turniere": turniere,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
                "opts": self.model._meta,
            })
        for turnier in turniere:
            turnier.teamdaten_loeschen()
        self.message_user(
            request, f"Teamdaten von {len(turniere)} Turnier(en) gelöscht. Teamnamen und Ergebnisse bleiben.",
            messages.SUCCESS,
        )
        return None

    @admin.display(description="Spielplan")
    def spielplan_link(self, obj):
        return format_html('<a href="{}?turnier={}">Spielplan →</a>', reverse("orga_spielplan"), obj.pk)


class SpielerInline(admin.TabularInline):
    model = Spieler
    extra = 0


class ZahlungFilter(admin.SimpleListFilter):
    title = "Zahlung"
    parameter_name = "zahlung"

    def lookups(self, request, model_admin):
        return [("unbezahlt", "Unbezahlt (mit Startplatz)"), ("bezahlt", "Bezahlt")]

    def queryset(self, request, queryset):
        if self.value() == "unbezahlt":
            return queryset.filter(bezahlt=False, status__in=Team.STARTPLATZ_STATUS)
        if self.value() == "bezahlt":
            return queryset.filter(bezahlt=True)
        return queryset


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = [
        "name", "kapitaen_name", "turnier", "anzahl_spieler", "status", "wartelisten_platz",
        "bezahlt", "bezahlt_am", "zahlungsart", "gruppe", "angemeldet_am",
    ]
    ordering = ["turnier", *Team.REIHENFOLGE]  # wer zuerst kommt, steht oben
    list_filter = ["turnier", "status", ZahlungFilter, "zahlungsart"]
    list_editable = ["bezahlt", "zahlungsart"]
    show_facets = admin.ShowFacets.ALWAYS
    actions = ["nachruecken"]
    search_fields = ["name", "kapitaen_name", "kapitaen_email", "spieler__vorname", "spieler__nachname"]
    list_select_related = ["turnier", "gruppe"]
    readonly_fields = ["bearbeitungslink"]
    inlines = [SpielerInline]
    fieldsets = [
        (None, {"fields": ["turnier", "name", "status", "gruppe"]}),
        ("Kapitän", {"fields": ["kapitaen_name", "kapitaen_email", "bearbeitungslink"]}),
        ("Zahlung", {
            "fields": ["bezahlt", "bezahlt_am", "zahlungsart"],
            "description": "Bezahlt setzt ein angemeldetes Team automatisch auf bestätigt.",
        }),
        (None, {"fields": ["notiz"]}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_anzahl_spieler=Count("spieler", distinct=True))

    def changelist_view(self, request, extra_context=None):
        # Kennzahlen für das gefilterte Turnier, sonst für das aktuelle (Screen 06).
        turnier_id = request.GET.get("turnier__id__exact")
        turnier = Turnier.objects.filter(pk=turnier_id).first() if turnier_id else Turnier.aktuelles()
        extra_context = extra_context or {}
        if turnier:
            extra_context["uebersicht_turnier"] = turnier
            extra_context["uebersicht"] = turnier.zahlungsuebersicht()
            extra_context["freie_plaetze"] = turnier.freie_plaetze
            if not turnier.warteliste_automatisch and turnier.freie_plaetze:
                extra_context["naechster_wartend"] = (
                    turnier.teams.filter(status=Team.Status.WARTELISTE).order_by(*Team.REIHENFOLGE).first()
                )
        return super().changelist_view(request, extra_context=extra_context)

    def get_urls(self):
        return [
            path("nachruecken/<int:turnier_id>/", self.admin_site.admin_view(self.naechsten_nachruecken),
                 name="tournament_team_naechsten_nachruecken"),
            path("erinnern/<int:turnier_id>/", self.admin_site.admin_view(self.an_zahlung_erinnern),
                 name="tournament_team_an_zahlung_erinnern"),
            path("unbezahlte-warteliste/<int:turnier_id>/", self.admin_site.admin_view(self.unbezahlte_auf_warteliste),
                 name="tournament_team_unbezahlte_auf_warteliste"),
            *super().get_urls(),
        ]

    def _knopf_turnier(self, request, turnier_id):
        """Für die Knöpfe in den Kacheln: Turnier holen; nur wer Teams ändern darf, darf sie auslösen."""
        if not self.has_change_permission(request):
            raise PermissionDenied
        return get_object_or_404(Turnier, pk=turnier_id)

    def an_zahlung_erinnern(self, request, turnier_id):
        """Knopf in der Kachel "Unbezahlt" (vor dem Meldeschluss): Erinnerungsmail an alle unbezahlten Teams."""
        turnier = self._knopf_turnier(request, turnier_id)
        if request.method == "POST":
            anzahl = warteliste.an_zahlung_erinnern(turnier, request)
            self.message_user(request, f"Erinnerung an {anzahl} Team(s) verschickt.", messages.SUCCESS)
        return redirect(f"{reverse('admin:tournament_team_changelist')}?turnier__id__exact={turnier.pk}")

    def unbezahlte_auf_warteliste(self, request, turnier_id):
        """Knopf in der Kachel "Unbezahlt" (nach dem Meldeschluss): Plätze an die Warteliste geben."""
        turnier = self._knopf_turnier(request, turnier_id)
        if request.method == "POST":
            if not turnier.meldeschluss_vorbei:
                self.message_user(request, "Erst nach dem Meldeschluss möglich.", messages.WARNING)
            else:
                verschoben, nachgerueckt = warteliste.unbezahlte_auf_warteliste(turnier, request)
                mails = sum(1 for t in verschoben if t.mail_verschickt)
                self.message_user(
                    request, f"{len(verschoben)} unbezahlte(s) Team(s) ans Ende der Warteliste gesetzt, "
                             f"{mails} Mail(s) verschickt.",
                    messages.SUCCESS,
                )
                for team in nachgerueckt:
                    self.message_user(request, f"{team} ist automatisch von der Warteliste nachgerückt ({_mail_hinweis(team)}).",
                                      messages.SUCCESS)
        return redirect(f"{reverse('admin:tournament_team_changelist')}?turnier__id__exact={turnier.pk}")

    def naechsten_nachruecken(self, request, turnier_id):
        """Knopf in der Kachel "Warteliste": das erste wartende Team auf einen freien Platz holen."""
        turnier = self._knopf_turnier(request, turnier_id)
        zurueck = f"{reverse('admin:tournament_team_changelist')}?turnier__id__exact={turnier.pk}"
        if request.method != "POST":
            return redirect(zurueck)
        team = turnier.teams.filter(status=Team.Status.WARTELISTE).order_by(*Team.REIHENFOLGE).first()
        if team is None:
            self.message_user(request, "Niemand steht auf der Warteliste.", messages.WARNING)
        elif not turnier.freie_plaetze:
            self.message_user(request, "Kein Platz frei – erst beim Turnier mehr Plätze einstellen.", messages.WARNING)
        else:
            warteliste.nachruecken(team, request)
            self.message_user(request, f"{team} ist von der Warteliste nachgerückt ({_mail_hinweis(team)}).",
                              messages.SUCCESS)
        return redirect(zurueck)

    # Teams dürfen auch mit geplanten Spielen gelöscht werden; danach wird der Plan automatisch angepasst.
    def delete_model(self, request, obj):
        self.delete_queryset(request, Team.objects.filter(pk=obj.pk))

    def delete_queryset(self, request, queryset):
        betroffen = defaultdict(set)
        for turnier_id, gruppe_id in queryset.values_list("turnier_id", "gruppe_id"):
            if gruppe_id:
                betroffen[turnier_id].add(gruppe_id)
        turnier_ids = set(queryset.values_list("turnier_id", flat=True))
        super().delete_queryset(request, queryset)
        for turnier in Turnier.objects.filter(pk__in=betroffen):
            spielplan.umplanen(turnier, betroffen[turnier.pk])
        self._auffuellen(request, Turnier.objects.filter(pk__in=turnier_ids))

    @admin.action(description="Von der Warteliste nachrücken")
    def nachruecken(self, request, queryset):
        nachgerueckt = mails = 0
        for team in queryset.filter(status=Team.Status.WARTELISTE).select_related("turnier").order_by(*Team.REIHENFOLGE):
            mails += warteliste.nachruecken(team, request)  # setzt den Status und schickt die Mail
            nachgerueckt += 1
            if team.turnier.belegte_plaetze > team.turnier.max_teams:
                self.message_user(
                    request, f"{team.turnier}: Jetzt mehr Teams mit Startplatz als max. Teams "
                    f"({team.turnier.belegte_plaetze} von {team.turnier.max_teams}).", messages.WARNING,
                )
        if nachgerueckt:
            self.message_user(request, f"{nachgerueckt} Team(s) von der Warteliste nachgerückt, {mails} Mail(s) verschickt.",
                              messages.SUCCESS)
        else:
            self.message_user(request, "Keines der gewählten Teams steht auf der Warteliste.", messages.WARNING)

    @admin.display(description="Spieler", ordering="_anzahl_spieler")
    def anzahl_spieler(self, obj):
        return obj._anzahl_spieler

    @admin.display(description="Warteliste", ordering="angemeldet_am")
    def wartelisten_platz(self, obj):
        return f"#{obj.wartelisten_platz}" if obj.wartelisten_platz else ""

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Von der Orga gerade auf die Warteliste gesetzt: nicht im selben Moment wieder nachrücken lassen
        zurueckgestuft = change and obj.status == Team.Status.WARTELISTE and form.initial.get("status") != obj.status
        self._auffuellen(request, [obj.turnier], ausser=obj if zurueckgestuft else None)

    def _auffuellen(self, request, turniere, ausser=None):
        for turnier in turniere:
            for team in warteliste.auffuellen(turnier, request, ausser=ausser):
                self.message_user(request, f"{team} ist automatisch von der Warteliste nachgerückt ({_mail_hinweis(team)}).",
                                  messages.SUCCESS)

    @admin.display(description="Bearbeitungslink")
    def bearbeitungslink(self, obj):
        if not obj.pk:
            return "wird beim Speichern erzeugt"
        url = reverse("team_bearbeiten", args=[obj.edit_token])
        return format_html('<a href="{}" target="_blank">{}</a>', url, url)


@admin.register(Gruppe)
class GruppeAdmin(admin.ModelAdmin):
    list_display = ["name", "turnier"]
    list_filter = ["turnier"]


@admin.register(Spiel)
class SpielAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        for meldung in ko.aktualisieren(obj.turnier):  # K.-o.-Runde nach Ergebnis-Änderungen befüllen
            self.message_user(request, meldung, messages.INFO)

    list_display = ["__str__", "turnier", "phase", "gruppe", "runde", "uhrzeit", "feld", "ergebnis", "schiri_team", "status"]
    list_filter = ["turnier", "phase", "status", "gruppe", "feld"]
    list_select_related = ["turnier", "gruppe", "team_a", "team_b", "schiri_team"]
    search_fields = ["team_a__name", "team_b__name", "platzhalter_a", "platzhalter_b"]
    fieldsets = [
        (None, {"fields": ["turnier", "phase", "gruppe", "runde", "uhrzeit", "feld", "status"]}),
        ("Teams", {
            "fields": [("team_a", "platzhalter_a"), ("team_b", "platzhalter_b"), "schiri_team"],
            "description": "K.-o.-Spiele werden aus dem Platzhalter automatisch befüllt. "
                           "Für ein Team von Hand (z. B. nach einem Entscheidungssatz) den Platzhalter leeren.",
        }),
        ("Ergebnis", {"fields": [("saetze_a", "saetze_b"), ("punkte_a", "punkte_b")]}),
    ]

    @admin.display(description="Ergebnis")
    def ergebnis(self, obj):
        if obj.status != Spiel.Status.BEENDET:
            return "–"
        if obj.turnier.zaehlmodus == Turnier.Zaehlmodus.SAETZE:
            return f"{obj.saetze_a} : {obj.saetze_b}"
        return f"{obj.punkte_a} : {obj.punkte_b}"
