// Spielerliste im Anmelde- und Bearbeitungsformular: Zeilen hinzufügen/entfernen, Zähler und Hinweis.
// Ohne JavaScript funktionieren die vorhandenen Zeilen trotzdem.
(function () {
  var box = document.querySelector("[data-spieler]");
  if (!box) return;
  var min = Number(box.dataset.min), max = Number(box.dataset.max);
  var prefix = box.dataset.prefix;
  var liste = box.querySelector(".spieler");
  var vorlage = box.querySelector("template");
  var total = box.querySelector("#id_" + prefix + "-TOTAL_FORMS");
  var hinzu = box.querySelector("[data-hinzu]");
  var zaehler = box.querySelector("[data-zaehler]");
  var hinweis = box.querySelector("[data-hinweis]");

  function zeilen() {
    return Array.prototype.filter.call(liste.querySelectorAll(".spieler-zeile"), function (z) { return !z.hidden; });
  }

  function gefuellt(zeile) {
    return Array.prototype.some.call(zeile.querySelectorAll("input[type=text]"), function (i) { return i.value.trim(); });
  }

  function aktualisieren() {
    var sichtbar = zeilen();
    var n = sichtbar.filter(gefuellt).length;
    if (zaehler) zaehler.textContent = n;
    hinzu.disabled = sichtbar.length >= max;
    if (!hinweis) return;
    hinweis.hidden = false;
    hinweis.classList.toggle("hinweis--warnung", n < min);
    hinweis.textContent = n < min ? "Mindestens " + min + " Spieler – noch " + (min - n) + " fehlen."
      : n >= max ? "Maximum von " + max + " Spielern erreicht."
      : "Passt. Bis zu " + (max - n) + " weitere möglich.";
  }

  hinzu.addEventListener("click", function () {
    var i = Number(total.value);
    var html = vorlage.innerHTML.replace(/__prefix__/g, String(i));
    liste.insertAdjacentHTML("beforeend", html);
    total.value = i + 1;
    liste.lastElementChild.querySelector("input[type=text]").focus();
    aktualisieren();
  });

  liste.addEventListener("click", function (e) {
    var knopf = e.target.closest(".entfernen");
    if (!knopf) return;
    var zeile = knopf.closest(".spieler-zeile");
    zeile.querySelector("input[name$='-DELETE']").checked = true;
    zeile.hidden = true;
    aktualisieren();
  });

  liste.addEventListener("input", aktualisieren);
  aktualisieren();
})();
