// Admin "Turnier": Im Punkte-Modus gelten Gewinnsätze und Entscheidungssatz nicht – ausgrauen.
// Bewusst nicht "disabled": gesperrte Felder würden beim Speichern nicht mitgeschickt.
document.addEventListener("DOMContentLoaded", function () {
  var modus = document.getElementById("id_zaehlmodus");
  if (!modus) return;
  var nurSatzModus = ["gewinnsaetze", "punkte_entscheidungssatz"];
  var punkteLabel = document.querySelector("label[for=id_punkte_pro_satz]");
  var punkteText = punkteLabel ? punkteLabel.textContent : "";

  function aktualisieren() {
    var punkte = modus.value === "punkte";
    nurSatzModus.forEach(function (name) {
      var feld = document.getElementById("id_" + name);
      if (!feld) return;
      feld.setAttribute("aria-disabled", punkte ? "true" : "false");
      feld.tabIndex = punkte ? -1 : 0;
      var zeile = feld.closest(".form-row") || feld.closest(".fieldBox");
      if (zeile) zeile.classList.toggle("satzball-aus", punkte);
    });
    if (punkteLabel) punkteLabel.textContent = punkte ? "Zielpunktzahl (ein Satz):" : punkteText;
  }

  modus.addEventListener("change", aktualisieren);
  aktualisieren();
});
