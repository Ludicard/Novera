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
})();
