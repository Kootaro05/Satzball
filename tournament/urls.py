from django.urls import path

from . import orga, views

urlpatterns = [
    path("", views.startseite, name="startseite"),
    path("turniere/", views.turniere, name="turniere"),
    path("teams/", views.teamliste, name="teamliste"),
    path("spielplan/", views.spielplan, name="spielplan"),
    path("tabelle/", views.tabelle, name="tabelle"),
    path("anmelden/", views.anmelden, name="anmelden"),
    path("datenschutz/", views.datenschutz, name="datenschutz"),
    path("team/<str:token>/", views.team_bearbeiten, name="team_bearbeiten"),
    path("team/<str:token>/angemeldet/", views.team_angemeldet, name="team_angemeldet"),
    path("team/<str:token>/abmelden/", views.team_abmelden, name="team_abmelden"),
    path("orga/spielplan/", orga.spielplan_seite, name="orga_spielplan"),
    path("orga/spielplan/druck/", orga.spielplan_druck, name="orga_spielplan_druck"),
    path("orga/spiel/<int:pk>/", orga.ergebnis_seite, name="orga_ergebnis"),
]
