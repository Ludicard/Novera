/* En formularios con «cliente», muestra solo las casillas (equipos, órdenes) de ese cliente (data-cliente). */
(function () {
  "use strict";
  var cliente = document.querySelector('select[name="cliente"]');
  if (!cliente) return;
  var casillas = document.querySelectorAll("input[type=checkbox][data-cliente]");
  if (!casillas.length) return;
  function filtrar() {
    var grupos = new Set();
    casillas.forEach(function (c) {
      var visible = cliente.value && c.dataset.cliente === cliente.value;
      var fila = c.closest("li") || c.parentNode;
      fila.hidden = !visible;
      if (!visible && c.checked && cliente.value) c.checked = false; // no dejar marcado algo de otro cliente
      grupos.add(c.closest(".campo"));
    });
    grupos.forEach(function (g) {
      if (!g) return;
      var hay = g.querySelector("input[type=checkbox][data-cliente]:not([hidden])") &&
        Array.prototype.some.call(g.querySelectorAll("input[type=checkbox][data-cliente]"), function (c) { return !(c.closest("li") || c.parentNode).hidden; });
      var aviso = g.querySelector(".sin-opciones");
      if (!aviso) { aviso = document.createElement("small"); aviso.className = "sin-opciones tenue"; g.appendChild(aviso); }
      aviso.textContent = cliente.value ? (hay ? "" : "Este cliente no tiene opciones para elegir aquí.") : "Elige primero el cliente.";
    });
  }
  cliente.addEventListener("change", filtrar);
  filtrar();
})();
