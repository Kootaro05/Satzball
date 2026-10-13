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

Beispiel für `/etc/nginx/sites-available/satzball` (Zertifikat z. B. mit `certbot --nginx -d volleyball.example.de`):

```nginx
server {
    listen 80;
    server_name volleyball.example.de;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name volleyball.example.de;

    ssl_certificate     /etc/letsencrypt/live/volleyball.example.de/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/volleyball.example.de/privkey.pem;

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
```

`X-Forwarded-Proto` ist wichtig: Daran erkennt Django, dass die Seite über HTTPS kam
(sonst scheitert der Admin-Login an der CSRF-Prüfung). Statische Dateien liefert die App selbst aus.

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

Es bleiben die 14 neuesten Sicherungen (`--behalten N` ändert das). Täglich per Cronjob, z. B.:

```cron
30 3 * * * docker exec satzball python manage.py sicherung >/dev/null
```

Wiederherstellen: Container stoppen, gewünschte Sicherung als `/app/data/db.sqlite3` ins Volume kopieren,
Container starten.

## Probelauf

```bash
docker exec satzball python manage.py testturnier --teams 10 --spielplan
```

Legt ein Turnier „Probelauf …“ für heute an: 10 bezahlte Teams, 2 noch offene, Spielplan veröffentlicht.
Mails gehen an `@example.invalid` und kommen nicht an. Das Testturnier ist bis zum Löschen das
„aktuelle“ Turnier auf der Startseite – danach im Admin löschen.

## Nach dem Turnier (Datenschutz)

Im Admin unter Turniere das Turnier auswählen → Aktion „Teamdaten löschen (Datenschutz)“.
Löscht Spieler, Kapitänsdaten und Notizen und macht die Bearbeitungslinks ungültig; Teamnamen und
Ergebnisse bleiben. Geht erst nach dem Turniertag und fragt vorher nach.

## Logs

```bash
docker logs -f satzball
```
