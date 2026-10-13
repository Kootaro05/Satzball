// Drag & Drop im Orga-Spielplan: Spiel auf ein anderes Spiel ziehen tauscht beide,
// auf ein leeres Feld ziehen verschiebt es dorthin. Gespeichert wird per normalem Formular.
(function () {
  var form = document.getElementById("verschieben");
  if (!form) return;
  var gezogen = null;

  function markierungWeg() {
    document.querySelectorAll(".spiel--ziel").forEach(function (el) { el.classList.remove("spiel--ziel"); });
  }

  function ziel(e) {
    var z = e.target.closest("[data-spiel], .spiel--leer");
    return z && z.dataset.spiel !== gezogen ? z : null;
  }

  document.addEventListener("dragstart", function (e) {
    var spiel = e.target.closest("[data-spiel]");
    if (!spiel) return;
    gezogen = spiel.dataset.spiel;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", gezogen);
  });

  document.addEventListener("dragover", function (e) {
    var z = gezogen && ziel(e);
    if (!z) return;
    e.preventDefault();
    markierungWeg();
    z.classList.add("spiel--ziel");
  });

  document.addEventListener("drop", function (e) {
    var z = gezogen && ziel(e);
    if (!z) return;
    e.preventDefault();
    form.elements.spiel.value = gezogen;
    form.elements.ziel_spiel.value = z.dataset.spiel || "";
    form.elements.ziel_zeit.value = z.dataset.zeit || "";
    form.elements.ziel_feld.value = z.dataset.feld || "";
    form.submit();
  });

  document.addEventListener("dragend", function () {
    gezogen = null;
    markierungWeg();
  });
})();
