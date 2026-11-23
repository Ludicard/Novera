// Calcula IVA, total y fecha de cobro mientras se llena el formulario de factura.
(function () {
  const form = document.getElementById("factura-form");
  if (!form) return;
  const $ = (name) => form.querySelector(`[name="${name}"]`);
  const subtotal = $("subtotal"), pct = $("porcentaje_iva"), cliente = $("cliente");
  const emision = $("fecha_emision"), dias = $("dias_credito"), cobro = $("fecha_cobro");
  const diasClientes = JSON.parse(document.getElementById("dias-clientes").textContent);
  const dinero = (n) => "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  let cobroManual = false;

  function calcularCobro() {
    if (!emision.value) return "";
    const f = new Date(emision.value + "T12:00:00");
    f.setDate(f.getDate() + (parseInt(dias.value, 10) || 0));
    return f.toISOString().slice(0, 10);
  }

  function montos() {
    const s = parseFloat(subtotal.value) || 0;
    const iva = Math.round(s * (parseFloat(pct.value) || 0)) / 100;
    document.getElementById("r-subtotal").textContent = dinero(s);
    document.getElementById("r-iva").textContent = dinero(iva);
    document.getElementById("r-total").textContent = dinero(Math.round((s + iva) * 100) / 100);
  }

  function fechaCobro() {
    if (!cobroManual) cobro.value = calcularCobro();
  }

  subtotal.addEventListener("input", montos);
  pct.addEventListener("change", montos);
  emision.addEventListener("change", fechaCobro);
  dias.addEventListener("input", fechaCobro);
  cobro.addEventListener("input", () => { cobroManual = cobro.value !== ""; });
  cliente.addEventListener("change", () => {
    if (diasClientes[cliente.value] !== undefined) { dias.value = diasClientes[cliente.value]; fechaCobro(); }
  });
  montos();
  // Si la fecha de cobro ya escrita no es emisión + días, se respeta como manual.
  cobroManual = cobro.value !== "" && cobro.value !== calcularCobro();
  fechaCobro();

  // Alta rápida de cliente sin salir de la factura
  const dlg = document.getElementById("dlg-cliente");
  const abrir = document.getElementById("abrir-cliente");
  if (dlg && abrir) {
    const fc = document.getElementById("form-cliente");
    const errores = document.getElementById("cliente-errores");
    abrir.addEventListener("click", () => { errores.hidden = true; fc.reset(); dlg.showModal(); fc.nombre.focus(); });
    dlg.querySelector("[data-cerrar]").addEventListener("click", () => dlg.close());
    fc.addEventListener("submit", async (e) => {
      e.preventDefault();
      const r = await fetch(fc.dataset.url, { method: "POST", body: new FormData(fc), headers: { "X-Requested-With": "fetch" } });
      const datos = await r.json().catch(() => ({ errores: { __all__: ["No se pudo crear el cliente."] } }));
      if (!r.ok) {
        errores.textContent = Object.values(datos.errores || {}).flat().join(" ");
        errores.hidden = false;
        return;
      }
      const opcion = new Option(datos.nombre, datos.id, true, true);
      cliente.add(opcion);
      diasClientes[datos.id] = datos.dias_credito;
      cliente.dispatchEvent(new Event("change"));
      dlg.close();
    });
  }

  // Factura o recibo: si el número es el sugerido, cambia al siguiente del otro tipo
  const numero = $("numero");
  form.querySelectorAll('input[name="tipo"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const sigF = numero.dataset.siguienteFactura, sigR = numero.dataset.siguienteRecibo;
      if (!numero.value || numero.value === sigF || numero.value === sigR) {
        numero.value = radio.value === "RECIBO" ? sigR : sigF;
      }
    });
  });
})();
