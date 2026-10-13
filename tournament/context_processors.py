from django.conf import settings

from .models import Turnier


def satzball(request):
    return {"quellcode_url": settings.QUELLCODE_URL}


def aktuelles_turnier(request):
    """Für den Hinweis "Du siehst ein anderes Turnier" – nur auf öffentlichen Seiten gebraucht."""
    return {"aktuelles_turnier": Turnier.aktuelles}
