/* Filas dinámicas de formsets de Django: «+ Añadir línea» y «Quitar». Total de proforma en vivo. */
(function () {
  "use strict";
  document.querySelectorAll("[data-formset]").forEach(function (bloque) {
    var prefijo = bloque.dataset.formset;
    var total = document.getElementById("id_" + prefijo + "-TOTAL_FORMS");
    var cuerpo = bloque.querySelector("[data-filas]");
    var plantilla = document.getElementById(prefijo + "-vacio");

    function quitar(fila) {
      var borrar = fila.querySelector('input[name$="-DELETE"]');
      if (borrar && fila.dataset.existente === "1") { borrar.checked = true; fila.hidden = true; }
      else fila.remove(); // fila nueva aún no guardada: se descarta (el contador no se toca: Django ignora vacías)
      recalcular();
    }
    bloque.addEventListener("click", function (e) {
      var b = e.target.closest("[data-quitar]");
      if (b) { e.preventDefault(); quitar(b.closest("[data-fila]")); }
    });
    bloque.querySelector("[data-agregar]").addEventListener("click", function () {
      var n = parseInt(total.value, 10);
      var html = plantilla.innerHTML.replace(/__prefix__/g, n);
      cuerpo.insertAdjacentHTML("beforeend", html);
      total.value = n + 1;
      var nueva = cuerpo.lastElementChild;
      var foco = nueva.querySelector('input[name$="descripcion"]');
      if (foco) foco.focus();
    });

    // Total de la proforma
    var dinero = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
    function recalcular() {
      var resumen = document.getElementById("resumen-proforma");
      if (!resumen) return;
      var sub = 0;
      cuerpo.querySelectorAll("[data-fila]").forEach(function (f) {
        if (f.hidden) return;
        var c = parseFloat((f.querySelector('[name$="-cantidad"]') || {}).value) || 0;
        var p = parseFloat((f.querySelector('[name$="-precio_unitario"]') || {}).value) || 0;
        var imp = Math.round(c * p * 100) / 100;
        var celda = f.querySelector("[data-importe]");
        if (celda) celda.textContent = dinero.format(imp);
        sub += imp;
      });
      var pct = parseFloat((document.querySelector('[name="porcentaje_iva"]') || {}).value) || 0;
      var iva = Math.round(sub * pct) / 100;
      document.getElementById("r-subtotal").textContent = dinero.format(sub);
      document.getElementById("r-iva").textContent = dinero.format(iva);
      document.getElementById("r-total").textContent = dinero.format(Math.round((sub + iva) * 100) / 100);
    }
    bloque.addEventListener("input", recalcular);
    var iva = document.querySelector('[name="porcentaje_iva"]');
    if (iva) iva.addEventListener("change", recalcular);
    recalcular();
  });
})();
