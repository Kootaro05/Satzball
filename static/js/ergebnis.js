// +/- Knöpfe der Ergebnis-Eingabe. Ohne JavaScript lassen sich die Zahlen direkt eintippen.
document.addEventListener("click", function (e) {
  var knopf = e.target.closest("[data-schritt]");
  if (!knopf) return;
  var feld = knopf.closest(".zaehler").querySelector("input");
  var wert = (Number(feld.value) || 0) + Number(knopf.dataset.schritt);
  var max = feld.max ? Number(feld.max) : Infinity;
  feld.value = Math.min(Math.max(wert, 0), max);
});
