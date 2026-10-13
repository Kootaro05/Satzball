from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Spieler, Team


class AnmeldeForm(forms.ModelForm):
    datenschutz = forms.BooleanField(
        required=True, error_messages={"required": "Bitte bestätige die Datenschutzhinweise."},
    )

    class Meta:
        model = Team
        fields = ["name", "kapitaen_name", "kapitaen_email"]
        labels = {"name": "Teamname", "kapitaen_name": "Name", "kapitaen_email": "E-Mail"}

    def __init__(self, *args, turnier, **kwargs):
        super().__init__(*args, **kwargs)
        self.turnier = turnier

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Team.objects.filter(turnier=self.turnier, name__iexact=name).exists():
            raise ValidationError("Diesen Teamnamen gibt es schon.")
        return name


class BaseSpielerFormSet(BaseInlineFormSet):
    """Prüft min./max. Spieler des Turniers. Leere Zeilen zählen nicht."""

    def __init__(self, *args, turnier, **kwargs):
        self.turnier = turnier
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        anzahl = sum(
            1 for f in self.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE")
        )
        if anzahl < self.turnier.min_spieler:
            raise ValidationError(
                f"Mindestens {self.turnier.min_spieler} Spieler – noch {self.turnier.min_spieler - anzahl} fehlen."
            )
        if anzahl > self.turnier.max_spieler:
            raise ValidationError(f"Höchstens {self.turnier.max_spieler} Spieler erlaubt.")


def spieler_formset(turnier, extra=0):
    return inlineformset_factory(
        Team, Spieler, formset=BaseSpielerFormSet,
        # Die Obergrenze prüft clean(); entfernte Zeilen bleiben als DELETE im Formular stehen.
        fields=["vorname", "nachname"], extra=extra, can_delete=True,
        widgets={
            "vorname": forms.TextInput(attrs={"placeholder": "Vorname", "autocomplete": "off"}),
            "nachname": forms.TextInput(attrs={"placeholder": "Nachname", "autocomplete": "off"}),
        },
    )
