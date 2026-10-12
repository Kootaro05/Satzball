from django.contrib import admin, messages
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from .models import Gruppe, Spiel, Spieler, Team, Turnier

admin.site.site_header = "Satzball – Orga"
admin.site.site_title = "Satzball"
admin.site.index_title = "Turnierverwaltung"


class GruppeInline(admin.TabularInline):
    model = Gruppe
    extra = 0


@admin.register(Turnier)
class TurnierAdmin(admin.ModelAdmin):
    list_display = ["name", "datum", "ort", "modus", "zaehlmodus", "anmeldung_offen", "anzahl_teams", "max_teams"]
    list_filter = ["anmeldung_offen", "modus", "zaehlmodus"]
    search_fields = ["name", "ort"]
    date_hierarchy = "datum"
    inlines = [GruppeInline]
    fieldsets = [
        (None, {"fields": ["name", "datum", "beginn", "ort", "startgebuehr_eur", "zahlungsinfo"]}),
        ("Anmeldung", {"fields": ["anmeldung_offen", "meldeschluss", "max_teams", "min_spieler", "max_spieler"]}),
        ("Modus", {"fields": ["modus", "anzahl_felder"]}),
        ("Zählweise", {"fields": ["zaehlmodus", "gewinnsaetze", "punkte_pro_satz", "punkte_entscheidungssatz"]}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_anzahl_teams=Count("teams"))

    @admin.display(description="Teams", ordering="_anzahl_teams")
    def anzahl_teams(self, obj):
        return obj._anzahl_teams


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
        "name", "kapitaen_name", "turnier", "anzahl_spieler", "status",
        "bezahlt", "bezahlt_am", "zahlungsart", "gruppe",
    ]
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
        return super().changelist_view(request, extra_context=extra_context)

    @admin.action(description="Von der Warteliste nachrücken")
    def nachruecken(self, request, queryset):
        nachgerueckt = 0
        for team in queryset.filter(status=Team.Status.WARTELISTE).select_related("turnier"):
            team.status = Team.Status.ANGEMELDET
            team.save()
            nachgerueckt += 1
            if team.turnier.belegte_plaetze > team.turnier.max_teams:
                self.message_user(
                    request, f"{team.turnier}: Jetzt mehr Teams mit Startplatz als max. Teams "
                    f"({team.turnier.belegte_plaetze} von {team.turnier.max_teams}).", messages.WARNING,
                )
        if nachgerueckt:
            self.message_user(request, f"{nachgerueckt} Team(s) von der Warteliste nachgerückt.", messages.SUCCESS)
        else:
            self.message_user(request, "Keines der gewählten Teams steht auf der Warteliste.", messages.WARNING)

    @admin.display(description="Spieler", ordering="_anzahl_spieler")
    def anzahl_spieler(self, obj):
        return obj._anzahl_spieler

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
    list_display = ["__str__", "turnier", "phase", "gruppe", "runde", "uhrzeit", "feld", "ergebnis", "schiri_team", "status"]
    list_filter = ["turnier", "phase", "status", "gruppe", "feld"]
    list_select_related = ["turnier", "gruppe", "team_a", "team_b", "schiri_team"]
    search_fields = ["team_a__name", "team_b__name", "platzhalter_a", "platzhalter_b"]
    fieldsets = [
        (None, {"fields": ["turnier", "phase", "gruppe", "runde", "uhrzeit", "feld", "status"]}),
        ("Teams", {"fields": [("team_a", "platzhalter_a"), ("team_b", "platzhalter_b"), "schiri_team"]}),
        ("Ergebnis", {"fields": [("saetze_a", "saetze_b"), ("punkte_a", "punkte_b")]}),
    ]

    @admin.display(description="Ergebnis")
    def ergebnis(self, obj):
        if obj.status != Spiel.Status.BEENDET:
            return "–"
        if obj.turnier.zaehlmodus == Turnier.Zaehlmodus.SAETZE:
            return f"{obj.saetze_a} : {obj.saetze_b}"
        return f"{obj.punkte_a} : {obj.punkte_b}"
