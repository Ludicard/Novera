/* Listado de facturas: búsqueda en vivo, filas clicables, selección múltiple y diálogos de cobro. */
(function () {
  "use strict";
  var script = document.currentScript;
  var dinero = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

  // --- Búsqueda: se aplica sola al dejar de escribir; «/» enfoca el buscador
  var form = document.getElementById("filtros-facturas");
  var buscador = form && form.querySelector("[name=q]");
  if (buscador) {
    var espera;
    var inicial = buscador.value;
    buscador.addEventListener("input", function () {
      clearTimeout(espera);
      espera = setTimeout(function () {
        if (buscador.value.trim() !== inicial.trim()) form.submit();
      }, 450);
    });
    if (inicial) {
      buscador.focus();
      buscador.setSelectionRange(inicial.length, inicial.length);
    }
    document.addEventListener("keydown", function (e) {
      var escribiendo = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
      if (e.key === "/" && !escribiendo) { e.preventDefault(); buscador.focus(); buscador.select(); }
      if (e.key === "Escape" && document.activeElement === buscador && buscador.value) {
        buscador.value = ""; form.submit();
      }
    });
    var cliente = form.querySelector("[name=cliente]");
    if (cliente) cliente.addEventListener("change", function () { form.submit(); });
  }

  // --- Fila clicable (salvo enlaces, botones y casillas)
  var tabla = document.getElementById("tabla-facturas");
  if (tabla) {
    tabla.addEventListener("click", function (e) {
      if (e.target.closest("a, button, input, label")) return;
      var fila = e.target.closest("tr.fila");
      if (!fila) return;
      if (window.getSelection().toString()) return; // estaba seleccionando texto
      if (e.ctrlKey || e.metaKey) window.open(fila.dataset.url, "_blank");
      else window.location = fila.dataset.url;
    });
  }

  // --- Diálogos
  function abrir(dlg) {
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
  }
  document.querySelectorAll("dialog [data-cerrar]").forEach(function (b) {
    b.addEventListener("click", function () { b.closest("dialog").close(); });
  });
  document.querySelectorAll("dialog").forEach(function (dlg) {
    dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); }); // clic fuera
  });

  // Cobrar una factura
  var dlgCobro = document.getElementById("dlg-cobro");
  document.querySelectorAll("button.cobrar").forEach(function (b) {
    b.addEventListener("click", function () {
      var f = document.getElementById("form-cobro");
      f.action = b.dataset.url;
      var monto = document.getElementById("cobro-monto");
      monto.value = b.dataset.saldo;
      monto.max = b.dataset.saldo;
      document.getElementById("cobro-info").textContent =
        b.dataset.numero + (b.dataset.cliente ? " · " + b.dataset.cliente : "") + " · saldo " + dinero.format(+b.dataset.saldo);
      abrir(dlgCobro);
      monto.select();
    });
  });

  // --- Selección múltiple
  var todas = document.getElementById("sel-todas");
  var casillas = Array.prototype.slice.call(document.querySelectorAll(".sel-fila"));
  var barra = document.getElementById("barra-seleccion");
  if (!todas || !barra) return;

  function seleccionadas() { return casillas.filter(function (c) { return c.checked; }); }
  function actualizar() {
    var sel = seleccionadas();
    var saldo = sel.reduce(function (s, c) { return s + (+c.dataset.saldo || 0); }, 0);
    document.getElementById("sel-n").textContent = sel.length;
    document.getElementById("sel-saldo").textContent = dinero.format(saldo);
    document.getElementById("sel-cobrar").disabled = saldo <= 0;
    barra.hidden = sel.length === 0;
    document.body.classList.toggle("con-seleccion", sel.length > 0);
    todas.checked = sel.length > 0 && sel.length === casillas.length;
    todas.indeterminate = sel.length > 0 && sel.length < casillas.length;
    casillas.forEach(function (c) { c.closest("tr").classList.toggle("seleccionada", c.checked); });
  }
  todas.addEventListener("change", function () {
    casillas.forEach(function (c) { c.checked = todas.checked; });
    actualizar();
  });
  // Mayús + clic selecciona un rango
  var ultima = null;
  casillas.forEach(function (c, i) {
    c.addEventListener("click", function (e) {
      if (e.shiftKey && ultima !== null) {
        var a = Math.min(ultima, i), b = Math.max(ultima, i);
        for (var k = a; k <= b; k++) casillas[k].checked = c.checked;
      }
      ultima = i;
      actualizar();
    });
  });
  document.getElementById("sel-limpiar").addEventListener("click", function () {
    casillas.forEach(function (c) { c.checked = false; });
    actualizar();
  });
  document.getElementById("sel-exportar").addEventListener("click", function () {
    var ids = seleccionadas().map(function (c) { return c.value; }).join(",");
    window.location = script.dataset.exportar + "?ids=" + ids;
  });
  document.getElementById("sel-cobrar").addEventListener("click", function () {
    var sel = seleccionadas().filter(function (c) { return +c.dataset.saldo > 0; });
    var total = sel.reduce(function (s, c) { return s + (+c.dataset.saldo); }, 0);
    document.getElementById("lote-ids").value = sel.map(function (c) { return c.value; }).join(",");
    document.getElementById("lote-n").textContent = sel.length;
    document.getElementById("lote-total").textContent = dinero.format(total);
    abrir(document.getElementById("dlg-lote"));
  });
  actualizar();
})();
