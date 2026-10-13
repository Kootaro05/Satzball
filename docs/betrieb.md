# Satzball – Betrieb auf dem VPS

Ein Docker-Container hinter dem vorhandenen nginx. nginx macht HTTPS und leitet an den Container weiter,
der nur lokal auf `127.0.0.1:8000` lauscht. Die SQLite-Datenbank liegt im Volume `satzball-data`.

> Noch nicht auf einem echten Server getestet – beim ersten Deployment Schritt für Schritt prüfen.

## Einmalig einrichten

```bash
# 1. Code holen und Image bauen
git clone https://github.com/Kootaro05/Satzball.git /opt/satzball
cd /opt/satzball
docker build -t satzball .

# 2. Umgebungsvariablen anlegen (Vorlage: docs/satzball.env.example)
sudo cp docs/satzball.env.example /etc/satzball.env
sudo chmod 600 /etc/satzball.env
sudo nano /etc/satzball.env

# 3. Container starten – Port nur lokal, damit niemand nginx umgehen kann
docker run -d --name satzball --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v satzball-data:/app/data \
  --env-file /etc/satzball.env \
  satzball

# 4. Orga-Zugang anlegen
docker exec -it satzball python manage.py createsuperuser
```

Der Container führt beim Start automatisch `migrate` aus.

## nginx

Erst einen einfachen Block für Port 80 anlegen, dann holt `certbot` das Zertifikat und trägt HTTPS
samt Weiterleitung selbst ein. (Eine fertige 443-Konfiguration vorab würde an noch fehlenden
Zertifikatsdateien scheitern.)

`/etc/nginx/sites-available/satzball`:

```nginx
server {
    listen 80;
    server_name volleyball.example.de;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/satzball /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d volleyball.example.de   # Weiterleitung auf HTTPS bestätigen
```

Danach `https://volleyball.example.de/admin/` aufrufen und anmelden. Vorher (nur http) klappt der
Login nicht, weil `DJANGO_HTTPS=1` die Cookies auf HTTPS beschränkt.

`X-Forwarded-Proto` ist wichtig: Daran erkennt Django, dass die Seite über HTTPS kam (sonst scheitert
der Login an der CSRF-Prüfung). Django vertraut diesem Header nur mit `DJANGO_HTTPS=1` – deshalb muss
der Container-Port an `127.0.0.1` gebunden sein, damit niemand nginx umgehen kann.
Statische Dateien liefert die App selbst aus.

## Update einspielen

```bash
cd /opt/satzball
git pull
docker build -t satzball .
docker exec satzball python manage.py sicherung   # vorher sichern
docker stop satzball && docker rm satzball
# dann den docker run-Befehl aus Schritt 3 erneut ausführen
```

Die Daten bleiben im Volume `satzball-data` erhalten.

## Sicherung

```bash
docker exec satzball python manage.py sicherung          # legt /app/data/sicherungen/db-….sqlite3 an
docker cp satzball:/app/data/sicherungen ./sicherungen    # vom Server herunterkopieren
```

Es bleiben die 14 neuesten Sicherungen (`--behalten N`, `--behalten 0` behält alle). Täglich per Cronjob, z. B.:

```cron
30 3 * * * docker exec satzball python manage.py sicherung >/dev/null
```

**Wiederherstellen** – mit dem Satzball-Image kopieren, damit die Datei dem App-Benutzer gehört
(als root hineinkopiert könnte die App sie nicht mehr schreiben):

```bash
docker exec satzball ls /app/data/sicherungen            # gewünschte Sicherung aussuchen
docker stop satzball
docker run --rm -v satzball-data:/app/data satzball cp /app/data/sicherungen/db-2026-11-14-033000.sqlite3 /app/data/db.sqlite3
docker start satzball
```

Eine heruntergeladene Sicherung vorher zurück ins Volume legen:
`docker cp db-….sqlite3 satzball:/app/data/sicherungen/` (geht auch bei gestopptem Container).

## Probelauf

```bash
docker exec satzball python manage.py testturnier --teams 10 --spielplan
```

Legt ein Turnier „Probelauf …“ für heute an: öffentlich sichtbar, 10 bezahlte Teams, 2 noch offene,
Spielplan veröffentlicht.
Mails gehen an `@example.invalid` und kommen nicht an. Das Testturnier ist bis zum Löschen das
„aktuelle“ Turnier auf der Startseite – danach im Admin löschen.

## Nach dem Turnier (Datenschutz)

Im Admin unter Turniere das Turnier auswählen → Aktion „Teamdaten löschen (Datenschutz)“.
Löscht Spieler, Kapitänsdaten, Notizen und das Admin-Änderungsprotokoll zu diesen Teams und macht die
Bearbeitungslinks ungültig; Teamnamen und Ergebnisse bleiben. Geht erst nach dem Turniertag und fragt
vorher nach.

Gut zu wissen:

- Die gelöschten Daten stecken noch in den **Sicherungen**, bis diese rotiert sind (bei täglicher
  Sicherung und `--behalten 14` also höchstens 14 Tage).
- Ohne `EMAIL_HOST` stehen die Mails samt **Bearbeitungslink** im Container-Log (`docker logs`).
  Für den echten Betrieb SMTP eintragen.

## Logs

```bash
docker logs -f satzball
```
