# 🏐 Satzball

**Turnierplanung für interne Volleyball-Turniere an Hochschulen – ohne Excel-Liste und WhatsApp-Chaos.**

Teams melden sich online an, die Orga sieht auf einen Blick, wer die Startgebühr bezahlt hat, und am Spieltag haben alle Spielplan, Ergebnisse und Tabelle auf dem Handy.

---

## ✨ Features

| | |
|---|---|
| 📝 **Anmeldung ohne Konto** | Teams melden sich mit Spielerliste an und bekommen einen Bearbeitungslink per Mail |
| 💶 **Zahlungs-Tracking** | Startgebühr abhaken, Zahlungsart notieren, offene Beträge auf einen Blick |
| 🗓️ **Spielplan per Knopfdruck** | Jeder gegen jeden oder Gruppen + K.-o., automatisch auf 2 Felder verteilt, danach per Drag & Drop anpassbar |
| 🔢 **Flexibler Zählmodus** | Satz-Modus (Best of 1 / 3 / 5) oder Punkte-Modus (ein Satz auf X Punkte) |
| 📊 **Live-Tabelle** | Berechnet sich automatisch aus den eingetragenen Ergebnissen |
| 📱 **Mobile-first** | Ergebnis-Eingabe am Spielfeldrand mit großen Buttons |

## 👥 Rollen

- **Orga** – verwaltet Turniere, Teams, Zahlungen, Spielplan und Ergebnisse (Login)
- **Teamkapitän** – bearbeitet das eigene Team über einen geheimen Link (kein Login)
- **Alle anderen** – sehen Teamliste, Spielplan, Ergebnisse und Tabelle

## 🛠️ Tech-Stack

Bewusst einfach gehalten:

- **Python & Django** mit Django Admin als Orga-Backend
- **SQLite** als Datenbank – Backup heißt Datei kopieren
- **Server-gerenderte Templates**, optional htmx
- **Docker** für das Deployment auf einem kleinen VPS

## 🚀 Lokal starten

```bash
# Repository klonen
git clone <repo-url> satzball
cd satzball

# Virtuelle Umgebung anlegen und Abhängigkeiten installieren
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Datenbank anlegen und Orga-Zugang erstellen
python manage.py migrate
python manage.py createsuperuser

# Entwicklungsserver starten
python manage.py runserver
```

Danach erreichbar unter:

- App: http://localhost:8000
- Orga-Backend: http://localhost:8000/admin

## 🐳 Mit Docker

```bash
docker build -t satzball .
docker run -p 8000:8000 -v satzball-data:/app/data satzball
```

Die SQLite-Datenbank liegt im Volume `satzball-data` und bleibt bei Updates erhalten.

## 🧪 Tests

```bash
python manage.py test
```

Besonders abgesichert sind die Spielplan-Erzeugung (Kreismethode, Felder, Schiri-Zuteilung) und die Tabellenberechnung für beide Zählmodi.

## 📁 Projektstruktur

```
satzball/
├── docs/
│   ├── konzept.md      # Anforderungen, Datenmodell, Spielplan-Logik
│   └── design.html     # UI-Entwurf der Screens
├── tournament/         # Django-App: Models, Views, Spielplan-Logik
├── templates/          # Server-gerenderte Seiten
├── Dockerfile
├── CLAUDE.md
└── README.md
```

## 🔒 Datenschutz

Gespeichert wird nur das Nötigste: Spielernamen und eine E-Mail-Adresse pro Team. Öffentlich sichtbar sind Teamnamen, Spielernamen und Ergebnisse; E-Mail-Adresse und Zahlungsstatus sieht nur die Orga. Teamdaten werden nach einer festen Frist nach dem Turnier gelöscht.

## 🗺️ Roadmap

- [ ] Grundgerüst, Datenmodell, Admin
- [ ] Anmeldung mit Bearbeitungslink
- [ ] Zahlungs-Tracking
- [ ] Spielplan-Generator und Ergebnis-Eingabe
- [ ] Öffentliche Seiten (Spielplan, Tabelle)
- [ ] Probelauf, dann erstes echtes Turnier 🎉

## 📜 Lizenz

Satzball ist Open Source unter der [GNU Affero General Public License v3.0](LICENSE).
Andere Hochschulen dürfen Satzball nutzen und anpassen. Wer eine veränderte Version als Webseite
betreibt, muss den Nutzern den geänderten Quellcode zugänglich machen – dafür gibt es den Link
„Quellcode“ in der Fußzeile (`SATZBALL_QUELLCODE_URL`).

---

Entstanden für die Volleyball-Community der DHSN Leipzig.
