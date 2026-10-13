# CLAUDE.md – Satzball

WebApp für interne Volleyball-Turniere an Hochschulen (entstanden an der DHSN Leipzig).
Open Source unter AGPL-3.0: Im Code und in den Seiten keine DHSN-spezifischen Texte, damit andere
Hochschulen Satzball nutzen können. Fußzeile verlinkt den Quellcode (`SATZBALL_QUELLCODE_URL`).

**Verbindlich:** `docs/konzept.md` (Anforderungen, Datenmodell, Spielplan-Logik) und
`docs/design.html` (UI-Entwurf, 8 Screens). Vor größeren Änderungen dort nachlesen.
Bei Unklarheiten oder Widersprüchen nachfragen statt annehmen.

## Leitprinzip

Einfach, kein Overengineering. Eine Person baut und betreibt das nebenher.
Jede Funktion muss sich gegen "geht auch mit einem Zettel" behaupten.

## Stack (fest)

- Python + Django, SQLite
- Server-gerenderte Django-Templates (`templates/`), schlankes CSS, optional htmx
- Django Admin als Orga-Backend
- Kein SPA-Framework, keine separate API, keine Nutzerkonten für Spieler
- Kapitäne bearbeiten ihr Team über einen geheimen Link (`Team.edit_token`)
- Deployment: ein Docker-Container auf privatem VPS, Gunicorn + WhiteNoise

## Struktur

- `config/` – Django-Projekt (Settings, URLs)
- `tournament/` – die eine App: Models, Admin, Views, Spielplan-Logik, Tests
- `templates/` – Seiten (`base.html`, `tournament/`, `mail/`)
- `static/` – `css/satzball.css` (Farben/Typo aus dem Design, Light + Dark), `js/spieler.js`,
  `fonts/` (Barlow, lokal statt Google Fonts – Datenschutz)
- `data/` – SQLite-Datei (`db.sqlite3`) und generierter `secret_key`; im Container
  `/app/data`, dort liegt das Volume `satzball-data`. Nicht ins Git.

Umgebungsvariablen (alle optional): `DJANGO_DEBUG` (lokal Standard `1`, im Container `0`),
`DJANGO_SECRET_KEY` (sonst aus `data/secret_key`), `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CSRF_TRUSTED_ORIGINS` (z. B. `https://volleyball.example.de`, nötig hinter HTTPS-Proxy),
`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`
(ohne `EMAIL_HOST` werden Mails nur in die Konsole/das Log geschrieben).
`DJANGO_HTTPS=1` (nur auf dem Server hinter nginx: vertraut `X-Forwarded-Proto`, Cookies nur über HTTPS).
Betrieb (nginx, Update, Sicherung, Probelauf): `docs/betrieb.md`, Vorlage `docs/satzball.env.example`.

## Fachliche Regeln

- Turniermodus pro Turnier: `jeder_gegen_jeden` oder `gruppen_ko`
- Zählmodus pro Turnier:
  - `saetze`: `gewinnsaetze` 1/2/3 = Best of 1/3/5, `punkte_pro_satz`, `punkte_entscheidungssatz`
  - `punkte`: keine Sätze und keine Zielpunktzahl (z. B. auf Zeit), mehr Punkte gewinnt, kein Unentschieden.
    „Ein Satz bis 25“ ist Satz-Modus mit Best of 1. Im Admin graut `admin_turnier.js` die Satz-Felder aus.
- Spiel speichert `saetze_a/b` und `punkte_a/b` (Satz-Modus: Ballpunkt-Summe, optional).
  Keine Punkte je Satz (bewusst entschieden).
- K.-o.-Spiele dürfen ohne Teams angelegt werden; dann zeigen `platzhalter_a/b`
  z. B. "1. Gruppe B". Ein beendetes Spiel braucht beide Teams.
- Die Tabelle wird **nie gespeichert**, sondern aus beendeten Spielen berechnet.
- Tabellenwertung:
  - Satz-Modus: Siege, Satzdifferenz, Ballpunktdifferenz, direkter Vergleich
  - Punkte-Modus: Siege, Punktdifferenz, erzielte Punkte, direkter Vergleich
- Paarungen per Kreismethode. Ungerade Teamzahl → "spielfrei"; das spielfreie Team pfeift.
  2 Felder, kein Team doppelt im selben Slot.
- Nur bestätigte **und** bezahlte Teams kommen in den Spielplan (`Team.objects.im_spielplan()`).
- Team-Status: Anmeldung → `angemeldet` (Platz frei) oder `warteliste` (voll).
  **Bezahlt = bestätigt:** Setzt die Orga `bezahlt`, wird ein angemeldetes Team automatisch
  `bestaetigt` (in `Team.save()`); wird `bezahlt` zurückgenommen, wieder `angemeldet`.
  Warteliste und Absage ändert das nicht. Kapitän kann bis Meldeschluss abmelden (`abgesagt`).
  Nachrücken von der Warteliste entscheidet die Orga per Klick (nicht automatisch).
- Zahlungs-Tracking im Admin (Teamliste): Haken "bezahlt" und Zahlungsart direkt in der Liste,
  Kennzahlen aus `Turnier.zahlungsuebersicht()` (erwartet = Gebühr × Teams mit Startplatz),
  Filter "Unbezahlt (mit Startplatz)", Aktion "Von der Warteliste nachrücken".
- Sichtbarkeit: Besucher sehen nur Turniere mit `Turnier.oeffentlich` (Standard aus, die Orga schaltet frei).
  Öffentliche Seiten nutzen `Turnier.aktuelles(nur_oeffentliche=True)`, Orga/Admin sehen alle.
- Turnier-Wahl (öffentlich): `views.gewaehltes_turnier(request)` – `?turnier=<id>` (in der Session gemerkt),
  sonst das aktuelle öffentliche Turnier. Liste unter `/turniere/`; bei einem anderen als dem aktuellen Turnier zeigt
  `base.html` einen Hinweis (Block `banner`, auf Orga- und Kapitänsseiten leer).
- Admin-Optik: `templates/admin/base_site.html` + `static/css/admin.css` (nur Django-CSS-Variablen,
  Schrift, Rundungen). Turnier im Punkte-Modus: `static/js/admin_turnier.js` graut Satz-Felder aus
  (bewusst nicht `disabled`, sonst fehlen die Werte beim Speichern).
- Spielerzahl: Pflicht sind mindestens `MIN_SPIELER` = 2, höchstens `max_spieler`. `min_spieler` am Turnier
  ist nur eine **Empfehlung** (gelber Hinweis im Formular, keine Ablehnung).
- Spielernamen sind **öffentlich** (Teamliste). E-Mail und Zahlungsstatus sehen nur Orga und Kapitän.
- Spiel-Phase (`Spiel.phase`): Gruppenspiel, Viertelfinale, Halbfinale, Spiel um Platz 3, Finale.
  K.-o.-Spiele haben keine Gruppe.
- Spielplan (`tournament/spielplan.py`, Orga-Seite `/orga/spielplan/`):
  - Jeder gegen jeden = eine Gruppe "A". Gruppen + K.-o.: 2–4 Gruppen, Vorschlag max. 5 Teams pro Gruppe,
    Orga wählt; Teams werden zufällig gelost.
  - K.-o.: 2 Gruppen → Halbfinale 1. A–2. B, 1. B–2. A; 3 Gruppen → Gruppensieger + bester Zweiter
    ins Halbfinale; 4 Gruppen → Top 2 ins Viertelfinale. Danach Spiel um Platz 3 und Finale (ein Slot).
    K.-o.-Spiele haben Platzhalter; die Teams trägt die Orga im Admin ein.
  - Slots: Startzeit (`Turnier.beginn`) + Index × `slot_minuten`; Gruppen rundenweise verzahnt.
  - Schiri: bevorzugt das spielfreie Team der Runde, sonst ein Team der Gruppe, das im Slot frei ist.
    Nach jedem Verschieben werden die Schiris der offenen Spiele neu verteilt (`schiris_neu`).
  - Neu erzeugen nur, solange es keine Ergebnisse gibt; zieht die Veröffentlichung zurück.
- Team löschen (im Admin) → `spielplan.umplanen`: Beendete Spiele bleiben (zählen aber nicht mehr in
  der Tabelle), offene Spiele der betroffenen Gruppe werden ohne das Team neu gepaart, alle offenen
  Spiele rücken ab dem nächsten freien Slot lückenlos auf, K.-o. danach.
- Tabelle: `tournament/tabelle.py` (`berechnen`, `gruppentabellen`), zählt nur beendete Gruppenspiele.
- Öffentlich `/spielplan/` (Screen 05): Spiele nach Uhrzeit und Feld, Ergebnisse. Gruppentabellen auf
  eigener Seite `/tabelle/` (Abweichung vom Design, damit der Menüpunkt aktiv markiert wird).
  Untere Navigation mit Inline-SVG-Symbolen. "Läuft" = erster Slot mit offenen Spielen, sobald seine Startzeit am Spieltag erreicht ist
  (folgt dem echten Stand, nicht nur der Uhr). Nur sichtbar, wenn
  `Turnier.spielplan_veroeffentlicht`. Keine E-Mails oder Zahlungsdaten auf öffentlichen Seiten.
- Datenschutz nach dem Turnier: Admin-Aktion "Teamdaten löschen" (`Turnier.teamdaten_loeschen`), erst nach
  dem Turniertag, mit Bestätigung. Löscht Spieler, Kapitänsdaten, Notizen und das Admin-Protokoll
  dazu, macht Links ungültig;
  Teamnamen und Ergebnisse bleiben. Deshalb sind `kapitaen_name/-email` im Model optional
  (im Anmeldeformular Pflicht).
- Befehle: `testturnier [--teams N] [--spielplan]` (Probelauf), `sicherung [--behalten N]`
  (SQLite-Backup nach `data/sicherungen/`).
- Ergebnis eintragen: `/orga/spiel/<id>/`, Satz-Modus Sätze (+ optional Ballpunkte gesamt),
  Punkte-Modus Punktzähler.
- Abweichung vom Design: "Ergebnis eintragen" zeigt im Punkte-Modus Punktzähler
  (z. B. 25 : 21 mit +/- Buttons) statt Sätzen.

## Konventionen

- Fachbegriffe und Feldnamen auf Deutsch wie im Konzept (ohne Umlaute: `kapitaen`, `bestaetigt`).
- Validierung in `Model.clean()`, damit Admin und Formulare sie gemeinsam nutzen.
- Spielplan- und Tabellenlogik als reine Funktionen mit Unit-Tests.

## Abhängigkeiten und CI

- `requirements.txt` mit **exakten** Versionen. Updates kommen als Dependabot-PR (`.github/dependabot.yml`,
  monatlich gebündelt; Django bleibt auf LTS 5.2).
- `.github/workflows/tests.yml` läuft bei jedem PR und Push auf `main`: Docker-Image bauen, Tests im Image,
  Container starten und Seiten abrufen. Nur mergen, wenn der Lauf grün ist.

## Befehle

```bash
python manage.py runserver
python manage.py makemigrations tournament
python manage.py test
docker build -t satzball .
docker run -p 8000:8000 -v satzball-data:/app/data satzball
```
