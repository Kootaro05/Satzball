from django.conf import settings

from .models import Turnier


def satzball(request):
    return {"quellcode_url": settings.QUELLCODE_URL}


def aktuelles_turnier(request):
    """Für den Hinweis "Du siehst ein anderes Turnier" – nur auf öffentlichen Seiten gebraucht.
    Als Funktion übergeben, damit die Abfrage nur läuft, wenn das Template sie wirklich nutzt."""
    return {"aktuelles_turnier": lambda: Turnier.aktuelles(nur_oeffentliche=True)}
