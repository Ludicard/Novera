/* Combobox con búsqueda para <select data-buscar>: escribe y aparecen las opciones parecidas
   (sin importar tildes ni mayúsculas). El <select> original se mantiene oculto y es el que se envía.
   Con data-texto-libre="<id de un input oculto>", si lo escrito no coincide con ninguna opción se conserva
   el texto: el <select> queda vacío y el texto va en ese input (p. ej. un cliente aún no registrado). */
(function () {
  "use strict";
  function normalizar(t) {
    return (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  }

  function mejorar(select) {
    if (select.dataset.buscadorListo) return;
    select.dataset.buscadorListo = "1";
    var id = (select.id || "buscador") + "-lista";
    var caja = document.createElement("div");
    caja.className = "combobox";
    var input = document.createElement("input");
    input.type = "text";
    input.className = "combobox-texto";
    input.autocomplete = "off";
    var libre = select.dataset.textoLibre ? document.getElementById(select.dataset.textoLibre) : null;
    input.placeholder = libre ? "Busca un cliente o escribe su nombre…" : "Escribe para buscar…";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", id);
    input.setAttribute("aria-autocomplete", "list");
    var lista = document.createElement("ul");
    lista.className = "combobox-lista";
    lista.id = id;
    lista.setAttribute("role", "listbox");
    lista.hidden = true;
    select.parentNode.insertBefore(caja, select);
    caja.appendChild(input);
    caja.appendChild(lista);
    caja.appendChild(select);
    select.classList.add("combobox-oculto");
    select.tabIndex = -1;
    var label = document.querySelector('label[for="' + select.id + '"]');
    if (label) { label.htmlFor = ""; label.addEventListener("click", function () { input.focus(); }); }
    var activo = -1, visibles = [];

    function textoSeleccionado() {
      var o = select.options[select.selectedIndex];
      return o && o.value ? o.text : "";
    }
    function sincronizar() { input.value = textoSeleccionado() || (libre ? libre.value : ""); }

    // Modo texto libre: lo escrito se queda aunque no sea una opción de la lista.
    function confirmarTexto() {
      if (!libre) return;
      var t = input.value.trim();
      if (t === textoSeleccionado()) { libre.value = ""; return; }
      var igual = Array.prototype.find.call(select.options, function (o) { return o.value && normalizar(o.text) === normalizar(t); });
      select.value = igual ? igual.value : "";
      libre.value = igual ? "" : t;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    // todas = true al abrir la lista: se ven todas las opciones aunque el campo muestre la elegida;
    // al escribir se filtra por lo escrito.
    function pintar(todas) {
      var q = todas === true ? "" : normalizar(input.value), palabras = q.split(/\s+/).filter(Boolean);
      visibles = Array.prototype.filter.call(select.options, function (o) {
        if (!o.value) return false;
        var t = normalizar(o.text);
        return palabras.every(function (p) { return t.indexOf(p) !== -1; });
      }).slice(0, 60);
      lista.innerHTML = "";
      if (!visibles.length) {
        var li = document.createElement("li");
        li.className = "combobox-vacio";
        li.textContent = "Sin coincidencias";
        lista.appendChild(li);
      }
      visibles.forEach(function (o, i) {
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        li.id = id + "-" + i;
        li.textContent = o.text;
        if (o.value === select.value) li.classList.add("elegido");
        li.addEventListener("mousedown", function (e) { e.preventDefault(); elegir(i); });
        lista.appendChild(li);
      });
      var elegida = visibles.findIndex(function (o) { return o.value === select.value; });
      activo = elegida >= 0 ? elegida : (visibles.length ? 0 : -1);
      marcar();
      abrir();
    }
    function marcar() {
      Array.prototype.forEach.call(lista.children, function (li, i) { li.classList.toggle("activo", i === activo); });
      if (activo >= 0) {
        input.setAttribute("aria-activedescendant", id + "-" + activo);
        var li = lista.children[activo];
        if (li && li.scrollIntoView) li.scrollIntoView({ block: "nearest" });
      }
    }
    function abrir() { lista.hidden = false; input.setAttribute("aria-expanded", "true"); }
    function cerrar() { lista.hidden = true; input.setAttribute("aria-expanded", "false"); }
    function elegir(i) {
      var o = visibles[i];
      if (!o) return;
      select.value = o.value;
      if (libre) libre.value = "";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      sincronizar();
      cerrar();
    }

    input.addEventListener("input", pintar);
    input.addEventListener("focus", function () { input.select(); pintar(true); });
    input.addEventListener("click", function () { if (lista.hidden) pintar(true); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); if (lista.hidden) pintar(true); activo = Math.min(activo + 1, visibles.length - 1); marcar(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); activo = Math.max(activo - 1, 0); marcar(); }
      else if (e.key === "Enter") { if (!lista.hidden && activo >= 0) { e.preventDefault(); elegir(activo); } }
      else if (e.key === "Escape") { cerrar(); sincronizar(); }
    });
    input.addEventListener("blur", function () { setTimeout(function () { cerrar(); confirmarTexto(); sincronizar(); }, 120); });
    // Al enviar el formulario (Enter o un botón) el blur aún no se ha procesado: se confirma aquí.
    if (libre && select.form) select.form.addEventListener("submit", confirmarTexto);
    select.addEventListener("change", sincronizar);  // p. ej. cliente creado desde el diálogo
    if (select.required) input.required = true;
    sincronizar();
  }

  document.querySelectorAll("select[data-buscar]").forEach(mejorar);
})();
