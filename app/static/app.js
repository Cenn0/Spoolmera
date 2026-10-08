"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const state = { overview: {}, products: [], spools: [], movements: [] };
const numberFormatter = new Intl.NumberFormat("de-DE");
let toastTimeout;

function escapeHtml(value) {
  const replacements = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, character => replacements[character]);
}

function safeColor(value) {
  return /^#[0-9a-fA-F]{6}$/.test(String(value)) ? value : "#64748b";
}

function formatGrams(value) {
  const grams = Number(value) || 0;
  if (Math.abs(grams) >= 1000) {
    return new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 }).format(grams / 1000) + " kg";
  }
  return numberFormatter.format(grams) + " g";
}

function formatDate(value) {
  if (!value) return "–";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "–" : date.toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" });
}

function spoolName(spool) {
  return spool.brand + " · " + spool.product_name;
}

function showToast(message, error = false) {
  const toast = $("#toast");
  clearTimeout(toastTimeout);
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.hidden = false;
  toastTimeout = setTimeout(() => { toast.hidden = true; }, 4500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { "Accept": "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
    ...options
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && payload.detail;
    const description = Array.isArray(detail)
      ? detail.map(item => (item.loc || []).slice(1).join(".") + ": " + item.msg).join(" · ")
      : detail;
    throw new Error(description || "Die Anfrage konnte nicht abgeschlossen werden.");
  }
  return payload;
}

function payloadRequest(method, path, body) {
  return api(path, { method, body: JSON.stringify(body) });
}

async function refresh() {
  try {
    const [overview, products, spools, movements] = await Promise.all([
      api("/api/overview"), api("/api/products"), api("/api/spools"), api("/api/movements?limit=200")
    ]);
    state.overview = overview;
    state.products = products;
    state.spools = spools;
    state.movements = movements;
    render();
  } catch (error) {
    showToast("Bestandsdaten konnten nicht geladen werden: " + error.message, true);
  }
}

function setView(viewName) {
  const titles = { dashboard: "Übersicht", spools: "Rollen", products: "Filamente", history: "Verlauf" };
  if (!Object.hasOwn(titles, viewName)) return;
  $$(".view").forEach(section => {
    const visible = section.id === "view-" + viewName;
    section.hidden = !visible;
    section.classList.toggle("is-visible", visible);
  });
  $$(".nav-item").forEach(button => {
    const active = button.dataset.view === viewName;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("#route-title").textContent = titles[viewName];
  document.title = titles[viewName] + " — Filament Manager";
  window.scrollTo({ top: 0, behavior: "auto" });
}

function statusBadge(status) {
  const labels = { sealed: "Ungeöffnet", opened: "Angebrochen", empty: "Leer" };
  const safeStatus = Object.hasOwn(labels, status) ? status : "empty";
  return '<span class="status-tag ' + safeStatus + '">' + labels[safeStatus] + "</span>";
}

function progress(spool) {
  const percentage = Math.max(0, Math.min(100, spool.remaining_g / spool.initial_g * 100));
  return '<div class="tiny-progress' + (percentage <= 20 ? " low" : "") +
    '"><span style="width:' + percentage.toFixed(2) + '%"></span></div>';
}

function productTitle(brand, name, colorName, hex) {
  return '<span class="product-primary"><span class="color-swatch" style="background:' + safeColor(hex) +
    '"></span><span><strong>' + escapeHtml(brand) + ' · ' + escapeHtml(name) +
    '</strong><small>' + escapeHtml(colorName) + '</small></span></span>';
}

function renderStats() {
  const o = state.overview;
  $("#stat-spools").textContent = numberFormatter.format(o.total_spools || 0);
  $("#stat-weight").innerHTML = escapeHtml(formatGrams(o.remaining_g || 0)).replace(" kg", " <small>kg</small>").replace(" g", " <small>g</small>");
  $("#stat-open").textContent = numberFormatter.format(o.opened_spools || 0);
  $("#stat-low").textContent = numberFormatter.format(o.low_spools || 0);
  $("#nav-spool-count").textContent = o.total_spools || 0;
}

function renderCompactSpools() {
  const current = state.spools.filter(spool => spool.remaining_g > 0);
  current.sort((a, b) => a.remaining_g - b.remaining_g || b.id - a.id);
  const visible = (current.length ? current : state.spools).slice(0, 5);
  $("#dashboard-spools").innerHTML = visible.length ? visible.map(spool => [
    '<div class="compact-row">',
    '<span class="color-swatch" style="background:', safeColor(spool.color_hex), '"></span>',
    '<div class="compact-copy"><strong>', escapeHtml(spoolName(spool)), '</strong><small>',
    escapeHtml(spool.material), ' · ', escapeHtml(spool.color_name), '</small></div>',
    '<div class="compact-stock"><b>', escapeHtml(formatGrams(spool.remaining_g)), '</b>',
    '<small>von ', escapeHtml(formatGrams(spool.initial_g)), '</small>', progress(spool), '</div>',
    '<button type="button" class="compact-open" aria-label="Rolle verwalten" title="Rolle verwalten" data-action="edit-spool" data-id="',
    spool.id, '">↗</button></div>'
  ].join("")).join("") : '<div class="empty-state">Noch keine Rollen erfasst.<br>Lege zuerst ein Filament an und erfasse eine Rolle.</div>';
}

function renderDistribution() {
  const byMaterial = new Map();
  for (const spool of state.spools) {
    if (spool.remaining_g > 0) {
      byMaterial.set(spool.material, (byMaterial.get(spool.material) || 0) + spool.remaining_g);
    }
  }
  const sorted = Array.from(byMaterial, ([label, weight]) => ({ label, weight }))
    .sort((a, b) => b.weight - a.weight);
  let data = sorted.slice(0, 4);
  if (sorted.length > 4) {
    data = [...data, { label: "Weitere", weight: sorted.slice(4).reduce((sum, row) => sum + row.weight, 0) }];
  }
  const total = sorted.reduce((sum, item) => sum + item.weight, 0);
  $("#donut-total").textContent = numberFormatter.format(total);
  const palette = ["#C78264", "#6F94A7", "#91A88B", "#E3BB7A", "#A293B5"];
  let start = 0;
  const segments = data.map((item, index) => {
    const end = start + 100 * item.weight / total;
    const segment = palette[index] + " " + start.toFixed(2) + "% " + end.toFixed(2) + "%";
    start = end;
    return segment;
  });
  $("#material-chart").style.background = segments.length ? "conic-gradient(" + segments.join(", ") + ")" : "#e9eeeb";
  $("#material-chart").setAttribute("aria-label", total ? "Materialbestand insgesamt " + total + " Gramm" : "Kein Material erfasst");
  $("#material-legend").innerHTML = data.length ? data.map((item, index) => [
    '<div class="legend-row"><span class="legend-dot" style="background:', palette[index], '"></span>',
    '<span class="legend-label">', escapeHtml(item.label), '</span>',
    '<span class="legend-value">', Math.round(item.weight * 100 / total), '%</span></div>'
  ].join("")).join("") : '<div class="empty-state">Noch kein Bestand.</div>';
}

function movementRow(movement, fallbackSpool) {
  const labels = { initial: "Rolle erfasst", consume: "Verbrauch gebucht", adjust: "Bestand korrigiert" };
  const icons = { initial: "+", consume: "−", adjust: "±" };
  const kind = Object.hasOwn(labels, movement.kind) ? movement.kind : "adjust";
  const brand = movement.brand || (fallbackSpool && fallbackSpool.brand) || "";
  const productName = movement.product_name || (fallbackSpool && fallbackSpool.product_name) || "";
  const deltaText = (movement.delta_g > 0 ? "+" : movement.delta_g < 0 ? "−" : "") +
    escapeHtml(formatGrams(Math.abs(movement.delta_g)));
  return [
    '<div class="timeline-entry"><span class="timeline-icon ', kind, '">', icons[kind], '</span>',
    '<div class="timeline-copy"><strong>', escapeHtml(labels[kind]), ' · ', escapeHtml(brand),
    ' ', escapeHtml(productName), '</strong><p>', escapeHtml(movement.note || "Ohne Notiz"),
    '</p></div><div class="timeline-trailing"><b>', deltaText, '</b><small>',
    escapeHtml(formatDate(movement.created_at)), '</small></div></div>'
  ].join("");
}

function renderHistory() {
  const empty = '<div class="empty-state">Noch keine Bestandsbewegungen vorhanden.</div>';
  $("#dashboard-history").innerHTML = state.movements.length
    ? state.movements.slice(0, 4).map(item => movementRow(item)).join("") : empty;
  $("#full-history").innerHTML = state.movements.length
    ? state.movements.map(item => movementRow(item)).join("") : empty;
}

function updateMaterialFilter() {
  const select = $("#spool-material-filter");
  const previous = select.value;
  const materials = Array.from(new Set(state.products.map(product => product.material))).sort();
  select.innerHTML = '<option value="">Alle Materialien</option>' +
    materials.map(material => '<option value="' + escapeHtml(material) + '">' + escapeHtml(material) + '</option>').join("");
  select.value = materials.includes(previous) ? previous : "";
}

function renderSpools() {
  const query = $("#spool-search").value.trim().toLocaleLowerCase("de-DE");
  const material = $("#spool-material-filter").value;
  const status = $("#spool-status-filter").value;
  const visible = state.spools.filter(spool => {
    const haystack = [spool.brand, spool.product_name, spool.material, spool.color_name, spool.location, spool.notes]
      .join(" ").toLocaleLowerCase("de-DE");
    return (!query || haystack.includes(query)) && (!material || spool.material === material) &&
      (!status || spool.status === status);
  });
  $("#spool-results").textContent = visible.length + " von " + state.spools.length + " Rollen";
  $("#spool-table-body").innerHTML = visible.length ? visible.map(spool => [
    '<tr><td>', productTitle(spool.brand, spool.product_name, spool.color_name, spool.color_hex),
    '</td><td><span class="material-tag">', escapeHtml(spool.material), '</span></td>',
    '<td><div class="stock-cell"><span>', escapeHtml(formatGrams(spool.remaining_g)),
    '</span><small>von ', escapeHtml(formatGrams(spool.initial_g)), '</small>', progress(spool),
    '</div></td><td>', statusBadge(spool.status), '</td><td>', escapeHtml(spool.location || "–"),
    '</td><td class="right-align"><div class="action-group">',
    spool.remaining_g > 0 ? '<button type="button" class="table-action" data-action="consume" data-id="' +
    spool.id + '">Verbrauch</button>' : "",
    '<button type="button" class="table-action" data-action="edit-spool" data-id="', spool.id,
    '">Details ↗</button></div></td></tr>'
  ].join("")).join("") : '<tr><td colspan="6" class="table-empty">Keine passenden Rollen gefunden.</td></tr>';
}

function renderProducts() {
  const query = $("#product-search").value.trim().toLocaleLowerCase("de-DE");
  const visible = state.products.filter(product => [
    product.brand, product.name, product.material, product.color_name
  ].join(" ").toLocaleLowerCase("de-DE").includes(query));
  $("#product-results").textContent = visible.length + " Filamente";
  $("#product-table-body").innerHTML = visible.length ? visible.map(product => [
    '<tr><td>', productTitle(product.brand, product.name, product.color_name, product.color_hex),
    '</td><td><span class="material-tag">', escapeHtml(product.material), '</span><small> · ',
    numberFormatter.format(product.diameter_mm), ' mm</small></td><td>', escapeHtml(product.color_name),
    '</td><td>', product.spool_count, '</td><td>', escapeHtml(formatGrams(product.total_remaining_g)),
    '</td><td class="right-align"><div class="action-group">',
    '<button type="button" class="table-action" data-action="new-product-spool" data-id="',
    product.id, '">+ Rolle</button>',
    '<button type="button" class="table-action" data-action="edit-product" data-id="',
    product.id, '">Bearbeiten</button></div></td></tr>'
  ].join("")).join("") : '<tr><td colspan="6" class="table-empty">Keine Filamente gefunden. Lege dein erstes Filament an.</td></tr>';
}

function render() {
  renderStats();
  renderCompactSpools();
  renderDistribution();
  renderHistory();
  updateMaterialFilter();
  renderSpools();
  renderProducts();
}

function openProductDialog(id) {
  const form = $("#product-form");
  form.reset();
  const product = state.products.find(item => item.id === id);
  $("#product-dialog-title").textContent = product ? "Filament bearbeiten" : "Filament anlegen";
  if (product) {
    ["id", "brand", "name", "material", "color_name", "color_hex", "diameter_mm", "notes"]
      .forEach(name => { form.elements.namedItem(name).value = product[name] ?? ""; });
  } else {
    form.elements.namedItem("id").value = "";
    form.elements.namedItem("color_hex").value = "#64748b";
  }
  $("#product-dialog").showModal();
  form.elements.namedItem("brand").focus();
}

function openSpoolDialog(productId) {
  if (!state.products.length) {
    showToast("Lege zuerst ein Filamentprodukt an.");
    openProductDialog();
    return;
  }
  const form = $("#spool-form");
  form.reset();
  const select = $("#spool-product-select");
  select.innerHTML = state.products.map(product => (
    '<option value="' + product.id + '">' + escapeHtml(product.brand + " · " + product.name +
    " · " + product.material + " · " + product.color_name) + "</option>"
  )).join("");
  if (productId) select.value = String(productId);
  $("#spool-dialog").showModal();
}

function setMovementKind() {
  const correction = $("#movement-kind").value === "adjust";
  const amount = $("#movement-grams");
  amount.min = correction ? "-100000" : "1";
  amount.value = "";
  $("#movement-dialog-title").textContent = correction ? "Bestand korrigieren" : "Verbrauch buchen";
  $("#movement-amount-label").textContent = correction ? "Bestandsänderung in g (+ oder −)" : "Verbrauchte Menge (g)";
  $("#movement-note-label").textContent = correction ? "Grund der Korrektur (Pflichtfeld)" : "Notiz (optional)";
  $("#movement-note").required = correction;
  $("#movement-note").placeholder = correction ? "z. B. Nach dem Wiegen berichtigt" : "z. B. Halterung gedruckt";
  $("#movement-helper").textContent = correction
    ? "Eine negative Menge reduziert den Bestand, eine positive Menge erhöht ihn bis maximal zum Startbestand."
    : "Die verbrauchte Menge wird vom Restbestand abgezogen.";
}

function openMovementDialog(id, kind = "consume") {
  const spool = state.spools.find(item => item.id === id);
  if (!spool) return showToast("Rolle nicht gefunden.", true);
  const form = $("#movement-form");
  form.reset();
  form.elements.namedItem("spool_id").value = id;
  $("#movement-kind").value = kind;
  $("#movement-spool-label").textContent = spoolName(spool) + " · aktuell " + formatGrams(spool.remaining_g);
  setMovementKind();
  $("#movement-dialog").showModal();
  $("#movement-grams").focus();
}

async function openEditSpoolDialog(id) {
  const spool = state.spools.find(item => item.id === id);
  if (!spool) return showToast("Rolle nicht gefunden.", true);
  const form = $("#edit-spool-form");
  form.reset();
  form.elements.namedItem("spool_id").value = id;
  form.elements.namedItem("location").value = spool.location;
  form.elements.namedItem("notes").value = spool.notes;
  form.elements.namedItem("opened").checked = spool.opened;
  $("#edit-spool-subtitle").textContent = spoolName(spool) + " · " + spool.color_name;
  $("#spool-detail-summary").innerHTML = [
    '<div><small>RESTBESTAND</small><strong>', escapeHtml(formatGrams(spool.remaining_g)),
    '</strong></div><div><small>STARTBESTAND</small><strong>',
    escapeHtml(formatGrams(spool.initial_g)), '</strong></div><div><small>ZUSTAND</small>',
    statusBadge(spool.status), '</div>'
  ].join("");
  try {
    const movements = await api("/api/spools/" + id + "/movements");
    $("#spool-history").innerHTML = movements.map(item => movementRow(item, spool)).join("");
    $("#edit-spool-dialog").showModal();
  } catch (error) {
    showToast(error.message, true);
  }
}

function setSubmitting(form, busy) {
  const button = form.querySelector('button[type="submit"]');
  if (button) button.disabled = busy;
}

async function submitProduct(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = Number(form.elements.namedItem("id").value);
  const body = {};
  ["brand", "name", "material", "color_name", "color_hex", "notes"].forEach(name => {
    body[name] = form.elements.namedItem(name).value;
  });
  body.diameter_mm = Number(form.elements.namedItem("diameter_mm").value);
  setSubmitting(form, true);
  try {
    const result = await payloadRequest(id ? "PUT" : "POST", id ? "/api/products/" + id : "/api/products", body);
    $("#product-dialog").close();
    await refresh();
    showToast(id ? "Filament aktualisiert." : "Filament angelegt.");
    if (!id) openSpoolDialog(result.id);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setSubmitting(form, false);
  }
}

async function submitSpool(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const remaining = form.elements.namedItem("remaining_g").value;
  const body = {
    product_id: Number(form.elements.namedItem("product_id").value),
    initial_g: Number(form.elements.namedItem("initial_g").value),
    remaining_g: remaining.trim() === "" ? null : Number(remaining),
    opened: form.elements.namedItem("opened").checked,
    location: form.elements.namedItem("location").value,
    notes: form.elements.namedItem("notes").value
  };
  setSubmitting(form, true);
  try {
    await payloadRequest("POST", "/api/spools", body);
    $("#spool-dialog").close();
    await refresh();
    showToast("Rolle wurde erfasst.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setSubmitting(form, false);
  }
}

async function submitMovement(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = Number(form.elements.namedItem("spool_id").value);
  const body = {
    kind: $("#movement-kind").value,
    grams: Number(form.elements.namedItem("grams").value),
    note: form.elements.namedItem("note").value
  };
  setSubmitting(form, true);
  try {
    const result = await payloadRequest("POST", "/api/spools/" + id + "/movements", body);
    $("#movement-dialog").close();
    await refresh();
    showToast("Buchung gespeichert. Restbestand: " + formatGrams(result.remaining_g));
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setSubmitting(form, false);
  }
}

async function submitSpoolDetails(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = Number(form.elements.namedItem("spool_id").value);
  const body = {
    location: form.elements.namedItem("location").value,
    notes: form.elements.namedItem("notes").value,
    opened: form.elements.namedItem("opened").checked
  };
  setSubmitting(form, true);
  try {
    await payloadRequest("PATCH", "/api/spools/" + id, body);
    $("#edit-spool-dialog").close();
    await refresh();
    showToast("Rollendaten gespeichert.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setSubmitting(form, false);
  }
}

async function archiveSpool() {
  const id = Number($("#edit-spool-form").elements.namedItem("spool_id").value);
  if (!window.confirm("Rolle wirklich archivieren? Ihre Buchungshistorie bleibt erhalten.")) return;
  try {
    await payloadRequest("POST", "/api/spools/" + id + "/archive");
    $("#edit-spool-dialog").close();
    await refresh();
    showToast("Rolle archiviert.");
  } catch (error) {
    showToast(error.message, true);
  }
}

function bindEvents() {
  document.addEventListener("click", event => {
    const close = event.target.closest("[data-close-dialog]");
    if (close) {
      close.closest("dialog").close();
      return;
    }
    const navigation = event.target.closest("[data-view]");
    if (navigation) {
      setView(navigation.dataset.view);
      return;
    }
    const action = event.target.closest("[data-action]");
    if (!action) return;
    const id = Number(action.dataset.id);
    switch (action.dataset.action) {
      case "new-product": openProductDialog(); break;
      case "edit-product": openProductDialog(id); break;
      case "new-spool": openSpoolDialog(); break;
      case "new-product-spool": openSpoolDialog(id); break;
      case "edit-spool": openEditSpoolDialog(id); break;
      case "consume": openMovementDialog(id); break;
      default: break;
    }
  });
  $("#spool-search").addEventListener("input", renderSpools);
  $("#spool-material-filter").addEventListener("change", renderSpools);
  $("#spool-status-filter").addEventListener("change", renderSpools);
  $("#product-search").addEventListener("input", renderProducts);
  $("#movement-kind").addEventListener("change", setMovementKind);
  $("#product-form").addEventListener("submit", submitProduct);
  $("#spool-form").addEventListener("submit", submitSpool);
  $("#movement-form").addEventListener("submit", submitMovement);
  $("#edit-spool-form").addEventListener("submit", submitSpoolDetails);
  $("#archive-spool-button").addEventListener("click", archiveSpool);
  $("#adjust-spool-button").addEventListener("click", () => {
    const id = Number($("#edit-spool-form").elements.namedItem("spool_id").value);
    $("#edit-spool-dialog").close();
    openMovementDialog(id, "adjust");
  });
}

function initialize() {
  $("#current-year").textContent = new Date().getFullYear();
  bindEvents();
  setView("dashboard");
  refresh();
}

document.addEventListener("DOMContentLoaded", initialize);
