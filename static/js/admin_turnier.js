// Admin "Turnier": Im Punkte-Modus gelten Gewinnsätze und Punkte pro Satz nicht – ausgrauen.
// Bewusst nicht "disabled": gesperrte Felder würden beim Speichern nicht mitgeschickt.
document.addEventListener("DOMContentLoaded", function () {
  var modus = document.getElementById("id_zaehlmodus");
  if (!modus) return;
  var nurSatzModus = ["gewinnsaetze", "punkte_pro_satz", "punkte_entscheidungssatz"];

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
  }

  modus.addEventListener("change", aktualisieren);
  aktualisieren();
});
