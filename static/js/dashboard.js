/* Panel de inicio: filtros y gráficos (Chart.js servido desde static/vendor). */
(function () {
  "use strict";

  // --- Filtros: el periodo se aplica al cambiarlo; el rango personalizado muestra sus fechas
  var form = document.getElementById("filtros");
  if (form) {
    var periodo = form.querySelector("[name=periodo]");
    var rangos = form.querySelectorAll(".rango");
    var boton = document.getElementById("aplicar");
    function actualizarRango() {
      var personalizado = periodo.value === "rango";
      rangos.forEach(function (el) { el.hidden = !personalizado; });
      boton.hidden = !personalizado;
    }
    actualizarRango();
    periodo.addEventListener("change", function () {
      actualizarRango();
      if (periodo.value !== "rango") form.submit();
    });
    form.querySelector("[name=cliente]").addEventListener("change", function () { form.submit(); });
  }

  var nodo = document.getElementById("datos-panel");
  if (!nodo || !window.Chart) return;
  var datos = JSON.parse(nodo.textContent);
  var script = document.currentScript || document.querySelector("script[data-lista]");
  var urlLista = script.dataset.lista;
  var filtro = script.dataset.filtro;
  var urlCliente = script.dataset.cliente; // termina en /0/

  // --- Paleta (validada: categórica slots 1 y aqua, rampa azul secuencial, colores de estado)
  var C = {
    facturado: "#2a78d6",
    cobrado: "#1baf7a",
    rampa: ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#104281"],
    estado: { PAGADA: "#0ca30c", PARCIAL: "#fab219", PENDIENTE: "#8a94a3", VENCIDA: "#d03b3b" },
    texto: "#52514e",
    rejilla: "#eceef1",
  };

  var dinero = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
  function compacto(v) {
    var a = Math.abs(v);
    if (a >= 1e6) return "$" + (v / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (a >= 1e3) return "$" + (v / 1e3).toFixed(a >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "k";
    return "$" + v;
  }
  function plural(n, s) { return n + " " + s + (n === 1 ? "" : "s"); }
  function recortar(s, n) { return s.length > n ? s.slice(0, n - 1) + "…" : s; }

  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 12;
  Chart.defaults.color = C.texto;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.animation.duration = 350;
  Chart.defaults.plugins.tooltip.backgroundColor = "#1d2733";
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 6;
  Chart.defaults.plugins.tooltip.boxPadding = 4;

  var ejeDinero = {
    beginAtZero: true,
    border: { display: false },
    grid: { color: C.rejilla },
    ticks: { callback: compacto, maxTicksLimit: 6 },
  };
  var ejeCategoria = { grid: { display: false }, border: { color: "#dfe4ea" } };
  var punta = { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 };
  var puntaH = { topRight: 4, bottomRight: 4, topLeft: 0, bottomLeft: 0 };

  function vacio(id, texto) {
    var canvas = document.getElementById(id);
    var p = document.createElement("p");
    p.className = "tenue grafico-vacio";
    p.textContent = texto;
    canvas.parentNode.replaceWith(p);
  }
  function cursor(evt, elementos) {
    evt.native.target.style.cursor = elementos.length ? "pointer" : "default";
  }

  // --- 1. Facturado vs. cobrado por mes
  var mensual = datos.mensual;
  if (!mensual.some(function (m) { return m.facturado || m.cobrado; })) {
    vacio("g-mensual", "Sin facturas ni cobros en este periodo.");
  } else {
    new Chart(document.getElementById("g-mensual"), {
      type: "bar",
      data: {
        labels: mensual.map(function (m) { return m.mes; }),
        datasets: [
          { label: "Facturado", data: mensual.map(function (m) { return m.facturado; }), backgroundColor: C.facturado },
          { label: "Cobrado", data: mensual.map(function (m) { return m.cobrado; }), backgroundColor: C.cobrado },
        ].map(function (d) {
          return Object.assign(d, { borderRadius: punta, borderSkipped: false, barPercentage: 0.9, categoryPercentage: 0.7, maxBarThickness: 28 });
        }),
      },
      options: {
        interaction: { mode: "index", intersect: false },
        scales: { x: ejeCategoria, y: ejeDinero },
        plugins: {
          legend: { position: "top", align: "end", labels: { usePointStyle: true, pointStyle: "rectRounded", boxWidth: 10, padding: 16 } },
          tooltip: {
            callbacks: {
              title: function (items) { var m = mensual[items[0].dataIndex].mes_largo; return m.charAt(0).toUpperCase() + m.slice(1); },
              label: function (c) { return " " + c.dataset.label + ": " + dinero.format(c.parsed.y); },
            },
          },
        },
      },
    });
  }

  // --- 2. Antigüedad de lo pendiente
  var tramos = datos.tramos;
  if (!tramos.some(function (t) { return t.monto; })) {
    vacio("g-tramos", "No hay saldo pendiente en este periodo.");
  } else {
    new Chart(document.getElementById("g-tramos"), {
      type: "bar",
      data: {
        labels: tramos.map(function (t) { return t.tramo; }),
        datasets: [{
          label: "Saldo pendiente",
          data: tramos.map(function (t) { return t.monto; }),
          backgroundColor: C.rampa,
          borderRadius: punta, borderSkipped: false, maxBarThickness: 56,
        }],
      },
      options: {
        scales: { x: Object.assign({}, ejeCategoria, { ticks: { autoSkip: false } }), y: ejeDinero },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (c) { return " " + dinero.format(c.parsed.y) + " · " + plural(tramos[c.dataIndex].n, "factura"); } } },
        },
      },
    });
  }

  // --- 3. Facturas por estado
  var estados = datos.estados;
  if (!estados.some(function (e) { return e.n; })) {
    vacio("g-estados", "Sin facturas en este periodo.");
  } else {
    new Chart(document.getElementById("g-estados"), {
      type: "bar",
      data: {
        labels: estados.map(function (e) { return e.estado + " (" + e.n + ")"; }),
        datasets: [{
          label: "Facturado",
          data: estados.map(function (e) { return e.monto; }),
          backgroundColor: estados.map(function (e) { return C.estado[e.clave]; }),
          borderRadius: puntaH, borderSkipped: false, maxBarThickness: 34,
        }],
      },
      options: {
        indexAxis: "y",
        scales: { x: ejeDinero, y: { grid: { display: false }, border: { color: "#dfe4ea" } } },
        onHover: cursor,
        onClick: function (evt, el) {
          if (el.length) window.location = urlLista + "?estado=" + estados[el[0].index].clave + "&" + filtro;
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (c) { return " " + dinero.format(c.parsed.x) + " · " + plural(estados[c.dataIndex].n, "factura"); } } },
        },
      },
    });
  }

  // --- 4. Clientes con más facturación
  var clientes = datos.clientes;
  if (!clientes.length) {
    vacio("g-clientes", "Sin facturas en este periodo.");
  } else {
    new Chart(document.getElementById("g-clientes"), {
      type: "bar",
      data: {
        labels: clientes.map(function (c) { return recortar(c.nombre, 28); }),
        datasets: [{
          label: "Facturado",
          data: clientes.map(function (c) { return c.facturado; }),
          backgroundColor: C.facturado,
          borderRadius: puntaH, borderSkipped: false, maxBarThickness: 26,
        }],
      },
      options: {
        indexAxis: "y",
        scales: { x: ejeDinero, y: { grid: { display: false }, border: { color: "#dfe4ea" } } },
        onHover: cursor,
        onClick: function (evt, el) {
          var c = el.length && clientes[el[0].index];
          if (c && c.id) window.location = urlCliente.replace(/0\/$/, c.id + "/");
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function (items) { return clientes[items[0].dataIndex].nombre; },
              label: function (c) {
                var cl = clientes[c.dataIndex];
                return [" Facturado: " + dinero.format(cl.facturado) + " (" + plural(cl.n, "factura") + ")", " Pendiente: " + dinero.format(cl.saldo)];
              },
            },
          },
        },
      },
    });
  }
})();
