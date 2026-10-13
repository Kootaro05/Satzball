# Satzball – Betrieb auf dem VPS

Ein Docker-Container hinter nginx. nginx macht HTTPS (Zertifikat von Let's Encrypt über certbot) und leitet
an den Container weiter, der nur lokal auf `127.0.0.1:8000` lauscht. Die SQLite-Datenbank liegt im Volume
`satzball-data`.

Erprobt auf Debian 12 mit nginx und certbot. Als `root` angemeldet entfällt das `sudo` vor den Befehlen.

> **Tipp zum Einfügen ins Terminal:** Befehle einzeln einfügen. Dateien mit `nano` bearbeiten statt mit
> `cat > datei <<'EOF' … EOF` – beim Einfügen gehen dort oft die Zeilenumbrüche verloren, die Shell wartet
> dann mit `>` auf ein `EOF`, das nie kommt. Mit **Strg + C** abbrechen, es wird nichts geschrieben.

## Voraussetzungen

- Ein **DNS-Eintrag (Typ A)** für die Domain, der auf die IP des Servers zeigt. Prüfen:
  `getent hosts volleyball.example.de` muss die Server-IP zeigen, sonst scheitert certbot.
- Pakete (Debian/Ubuntu):

```bash
sudo apt update
```

```bash
sudo apt install -y docker.io git nginx certbot python3-certbot-nginx
```

```bash
sudo systemctl enable --now docker
```

## Einmalig einrichten

**1. Code holen und Image bauen**

```bash
sudo git clone https://github.com/Kootaro05/Satzball.git /opt/satzball
```

```bash
cd /opt/satzball && sudo docker build -t satzball .
```

**2. Umgebungsvariablen anlegen** (Vorlage: `docs/satzball.env.example`)

```bash
sudo cp docs/satzball.env.example /etc/satzball.env && sudo chmod 600 /etc/satzball.env
```

```bash
sudo nano /etc/satzball.env
```

Werte eintragen, speichern mit **Strg + O**, **Enter**, beenden mit **Strg + X**. Zwei Stolperfallen:

- **Keine Anführungszeichen.** Docker liest die Datei wörtlich, Anführungszeichen werden Teil des Werts.
- **Absender** in der Form `DEFAULT_FROM_EMAIL=Name <adresse@domain>` – mit `@` und spitzen Klammern.
  Als Adresse das Postfach von `EMAIL_HOST_USER` nehmen, fremde Absender lehnen die meisten Anbieter ab.

**3. Container starten** – Port nur lokal, damit niemand nginx umgehen kann

```bash
sudo docker run -d --name satzball --restart unless-stopped -p 127.0.0.1:8000:8000 -v satzball-data:/app/data --env-file /etc/satzball.env satzball
```

Prüfen (Domain ersetzen), erwartet `HTTP/1.1 200 OK`:

```bash
curl -sI -H "Host: volleyball.example.de" http://127.0.0.1:8000/ | head -1
```

Der Container führt beim Start automatisch `migrate` aus.

**4. Orga-Zugang anlegen** (Benutzername und Passwort vergibst du selbst)

```bash
sudo docker exec -it satzball python manage.py createsuperuser
```

## nginx und HTTPS

Erst einen einfachen Block für Port 80 anlegen; certbot holt danach das Zertifikat und trägt HTTPS samt
Weiterleitung selbst ein. (Eine fertige 443-Konfiguration vorab würde an noch fehlenden Zertifikatsdateien
scheitern.)

```bash
sudo nano /etc/nginx/sites-available/satzball
```

Inhalt (Domain ersetzen):

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

Aktivieren, prüfen, neu laden:

```bash
sudo ln -s /etc/nginx/sites-available/satzball /etc/nginx/sites-enabled/satzball
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Zertifikat holen; `--redirect` leitet danach alle `http://`-Aufrufe auf `https://` um. certbot fragt nach
einer E-Mail-Adresse (für Warnungen zum Ablauf) und nach der Zustimmung zu den Nutzungsbedingungen.

```bash
sudo certbot --nginx --redirect -d volleyball.example.de
```

Automatische Verlängerung prüfen – erwartet „all simulated renewals succeeded“:

```bash
sudo certbot renew --dry-run
```

Prüfen, dass der Container nur lokal erreichbar ist – bei `8000` muss `127.0.0.1:8000` stehen, nicht
`0.0.0.0:8000`:

```bash
sudo ss -tlnp | grep -E ':(80|443|8000) '
```

Danach `https://volleyball.example.de/admin/` aufrufen und anmelden. Vor dem Zertifikat (nur http) klappt
der Login nicht, weil `DJANGO_HTTPS=1` die Cookies auf HTTPS beschränkt.

`X-Forwarded-Proto` ist wichtig: Daran erkennt Django, dass die Seite über HTTPS kam (sonst scheitert
der Login an der CSRF-Prüfung). Django vertraut diesem Header nur mit `DJANGO_HTTPS=1` – deshalb muss
der Container-Port an `127.0.0.1` gebunden sein. Statische Dateien liefert die App selbst aus.

## Mailversand prüfen

```bash
sudo docker exec satzball python manage.py sendtestemail deine-adresse@example.de
```

Kommt die Mail an, funktioniert SMTP. Danach einmal ein Testteam über die Seite anmelden: Die Mail mit
dem Bearbeitungslink muss ankommen. Landen Mails im Spam, fehlen meist SPF/DKIM-Einträge der
Absender-Domain (Hilfe des Mail-Anbieters).

Typischer Fehler: `SMTPSenderRefused … MAIL command parameter unrecognized` → `DEFAULT_FROM_EMAIL` hat
nicht die Form `Name <adresse@domain>` oder enthält Anführungszeichen (siehe Schritt 2). Nach jeder
Änderung an `/etc/satzball.env` den Container neu erstellen (wie bei „Update einspielen“).

## Update einspielen

```bash
cd /opt/satzball && sudo git pull
```

```bash
sudo docker build -t satzball .
```

```bash
sudo docker exec satzball python manage.py sicherung
```

```bash
sudo docker stop satzball && sudo docker rm satzball
```

```bash
sudo docker run -d --name satzball --restart unless-stopped -p 127.0.0.1:8000:8000 -v satzball-data:/app/data --env-file /etc/satzball.env satzball
```

Die Daten bleiben im Volume `satzball-data` erhalten. Vor dem Update auf GitHub prüfen, dass der
Testlauf („Tests“ unter *Actions*) für `main` grün ist.

## Sicherung

```bash
sudo docker exec satzball python manage.py sicherung
```

```bash
sudo docker cp satzball:/app/data/sicherungen ./sicherungen
```

Der erste Befehl legt `/app/data/sicherungen/db-….sqlite3` an, der zweite kopiert die Sicherungen vom
Container auf den Server. Es bleiben die 14 neuesten Sicherungen (`--behalten N`, `--behalten 0` behält
alle). Täglich per Cronjob (`sudo crontab -e`), z. B.:

```cron
30 3 * * * docker exec satzball python manage.py sicherung >/dev/null
```

**Wiederherstellen** – mit dem Satzball-Image kopieren, damit die Datei dem App-Benutzer gehört
(als root hineinkopiert könnte die App sie nicht mehr schreiben):

```bash
sudo docker exec satzball ls /app/data/sicherungen
```

```bash
sudo docker stop satzball
```

```bash
sudo docker run --rm -v satzball-data:/app/data satzball cp /app/data/sicherungen/db-2026-11-14-033000.sqlite3 /app/data/db.sqlite3
```

```bash
sudo docker start satzball
```

Eine heruntergeladene Sicherung vorher zurück ins Volume legen:
`sudo docker cp db-….sqlite3 satzball:/app/data/sicherungen/` (geht auch bei gestopptem Container).

## Probelauf

```bash
sudo docker exec satzball python manage.py testturnier --teams 10 --spielplan
```

Legt ein Turnier „Probelauf …“ für heute an: öffentlich sichtbar, 10 bezahlte Teams, 2 noch offene,
Spielplan veröffentlicht. Für „Gruppen + K.-o.“ braucht es mindestens 6 Teams.
Mails gehen an `@example.invalid` und kommen nicht an. Das Testturnier ist bis zum Löschen das
„aktuelle“ Turnier auf der Startseite – danach im Admin löschen.

## Neues Turnier

Im Admin anlegen und **„öffentlich sichtbar“** anhaken – sonst sehen Besucher es nicht
(Entwürfe bleiben so unsichtbar).

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
sudo docker logs -f satzball
```
