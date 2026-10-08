"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const state = { overview: {}, products: [], spools: [], movements: [], csvBytes: null };
const numberFormatter = new Intl.NumberFormat("en-US");
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
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(grams / 1000) + " kg";
  }
  return numberFormatter.format(grams) + " g";
}

function formatDate(value) {
  if (!value) return "–";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "–" : date.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
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
    throw new Error(description || "The request could not be completed.");
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
    showToast("Unable to load inventory data: " + error.message, true);
  }
}

function setView(viewName) {
  const titles = { dashboard: "Overview", spools: "Spools", products: "Filaments", history: "History", integrations: "Integrations" };
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
  const labels = { sealed: "Sealed", opened: "Opened", empty: "Empty" };
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
    '<small>of ', escapeHtml(formatGrams(spool.initial_g)), '</small>', progress(spool), '</div>',
    '<button type="button" class="compact-open" aria-label="Manage spool" title="Manage spool" data-action="edit-spool" data-id="',
    spool.id, '">↗</button></div>'
  ].join("")).join("") : '<div class="empty-state">No spools recorded yet.<br>Add a filament product and then a physical spool.</div>';
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
  $("#material-chart").setAttribute("aria-label", total ? "Total material inventory: " + total + " grams" : "No filament recorded");
  $("#material-legend").innerHTML = data.length ? data.map((item, index) => [
    '<div class="legend-row"><span class="legend-dot" style="background:', palette[index], '"></span>',
    '<span class="legend-label">', escapeHtml(item.label), '</span>',
    '<span class="legend-value">', Math.round(item.weight * 100 / total), '%</span></div>'
  ].join("")).join("") : '<div class="empty-state">No inventory yet.</div>';
}

function movementRow(movement, fallbackSpool) {
  const labels = { initial: "Spool registered", consume: "Consumption recorded", adjust: "Stock adjusted" };
  const icons = { initial: "+", consume: "−", adjust: "±" };
  const kind = Object.hasOwn(labels, movement.kind) ? movement.kind : "adjust";
  const brand = movement.brand || (fallbackSpool && fallbackSpool.brand) || "";
  const productName = movement.product_name || (fallbackSpool && fallbackSpool.product_name) || "";
  const deltaText = (movement.delta_g > 0 ? "+" : movement.delta_g < 0 ? "−" : "") +
    escapeHtml(formatGrams(Math.abs(movement.delta_g)));
  return [
    '<div class="timeline-entry"><span class="timeline-icon ', kind, '">', icons[kind], '</span>',
    '<div class="timeline-copy"><strong>', escapeHtml(labels[kind]), ' · ', escapeHtml(brand),
    ' ', escapeHtml(productName), '</strong><p>', escapeHtml(movement.note || "No note"),
    '</p></div><div class="timeline-trailing"><b>', deltaText, '</b><small>',
    escapeHtml(formatDate(movement.created_at)), '</small></div></div>'
  ].join("");
}

function renderHistory() {
  const empty = '<div class="empty-state">No inventory movements yet.</div>';
  $("#dashboard-history").innerHTML = state.movements.length
    ? state.movements.slice(0, 4).map(item => movementRow(item)).join("") : empty;
  $("#full-history").innerHTML = state.movements.length
    ? state.movements.map(item => movementRow(item)).join("") : empty;
}

function updateMaterialFilter() {
  const select = $("#spool-material-filter");
  const previous = select.value;
  const materials = Array.from(new Set(state.products.map(product => product.material))).sort();
  select.innerHTML = '<option value="">All materials</option>' +
    materials.map(material => '<option value="' + escapeHtml(material) + '">' + escapeHtml(material) + '</option>').join("");
  select.value = materials.includes(previous) ? previous : "";
}

function renderSpools() {
  const query = $("#spool-search").value.trim().toLocaleLowerCase("en-US");
  const material = $("#spool-material-filter").value;
  const status = $("#spool-status-filter").value;
  const visible = state.spools.filter(spool => {
    const haystack = [spool.brand, spool.product_name, spool.material, spool.color_name, spool.location, spool.notes]
      .join(" ").toLocaleLowerCase("en-US");
    return (!query || haystack.includes(query)) && (!material || spool.material === material) &&
      (!status || spool.status === status);
  });
  $("#spool-results").textContent = visible.length + " of " + state.spools.length + " spools";
  $("#spool-table-body").innerHTML = visible.length ? visible.map(spool => [
    '<tr><td>', productTitle(spool.brand, spool.product_name, spool.color_name, spool.color_hex),
    '</td><td><span class="material-tag">', escapeHtml(spool.material), '</span></td>',
    '<td><div class="stock-cell"><span>', escapeHtml(formatGrams(spool.remaining_g)),
    '</span><small>of ', escapeHtml(formatGrams(spool.initial_g)), '</small>', progress(spool),
    '</div></td><td>', statusBadge(spool.status), '</td><td>', escapeHtml(spool.location || "–"),
    '</td><td class="right-align"><div class="action-group">',
    spool.remaining_g > 0 ? '<button type="button" class="table-action" data-action="consume" data-id="' +
    spool.id + '">Record use</button>' : "",
    '<button type="button" class="table-action" data-action="label" data-uid="', escapeHtml(spool.uid), '">QR label</button>',
    '<button type="button" class="table-action" data-action="edit-spool" data-id="', spool.id,
    '">Details ↗</button></div></td></tr>'
  ].join("")).join("") : '<tr><td colspan="6" class="table-empty">No matching spools found.</td></tr>';
}

function renderProducts() {
  const query = $("#product-search").value.trim().toLocaleLowerCase("en-US");
  const visible = state.products.filter(product => [
    product.brand, product.name, product.material, product.color_name
  ].join(" ").toLocaleLowerCase("en-US").includes(query));
  $("#product-results").textContent = visible.length + " filaments";
  $("#product-table-body").innerHTML = visible.length ? visible.map(product => [
    '<tr><td>', productTitle(product.brand, product.name, product.color_name, product.color_hex),
    '</td><td><span class="material-tag">', escapeHtml(product.material), '</span><small> · ',
    numberFormatter.format(product.diameter_mm), ' mm</small></td><td>', escapeHtml(product.color_name),
    '</td><td>', product.spool_count, '</td><td>', escapeHtml(formatGrams(product.total_remaining_g)),
    '</td><td class="right-align"><div class="action-group">',
    '<button type="button" class="table-action" data-action="new-product-spool" data-id="',
    product.id, '">+ Spool</button>',
    '<button type="button" class="table-action" data-action="edit-product" data-id="',
    product.id, '">Edit</button></div></td></tr>'
  ].join("")).join("") : '<tr><td colspan="6" class="table-empty">No filaments yet. Add your first filament.</td></tr>';
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
  $("#product-dialog-title").textContent = product ? "Edit filament" : "Add filament";
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
    showToast("Create a filament product first.");
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
  $("#movement-dialog-title").textContent = correction ? "Adjust stock" : "Record consumption";
  $("#movement-amount-label").textContent = correction ? "Stock change in g (+ or −)" : "Consumed weight (g)";
  $("#movement-note-label").textContent = correction ? "Reason for adjustment (required)" : "Note (optional)";
  $("#movement-note").required = correction;
  $("#movement-note").placeholder = correction ? "e.g. corrected after weighing" : "e.g. printed a bracket";
  $("#movement-helper").textContent = correction
    ? "A negative amount reduces stock; a positive amount raises it up to the original weight."
    : "The consumed amount is deducted from remaining stock.";
}

function openMovementDialog(id, kind = "consume") {
  const spool = state.spools.find(item => item.id === id);
  if (!spool) return showToast("Spool not found.", true);
  const form = $("#movement-form");
  form.reset();
  form.elements.namedItem("spool_id").value = id;
  $("#movement-kind").value = kind;
  $("#movement-spool-label").textContent = spoolName(spool) + " · remaining " + formatGrams(spool.remaining_g);
  setMovementKind();
  $("#movement-dialog").showModal();
  $("#movement-grams").focus();
}

async function openEditSpoolDialog(id) {
  const spool = state.spools.find(item => item.id === id);
  if (!spool) return showToast("Spool not found.", true);
  const form = $("#edit-spool-form");
  form.reset();
  form.elements.namedItem("spool_id").value = id;
  form.elements.namedItem("location").value = spool.location;
  form.elements.namedItem("notes").value = spool.notes;
  form.elements.namedItem("opened").checked = spool.opened;
  $("#edit-spool-subtitle").textContent = spoolName(spool) + " · " + spool.color_name;
  $("#spool-label-link").href = "/labels/" + encodeURIComponent(spool.uid);
  $("#spool-detail-summary").innerHTML = [
    '<div><small>REMAINING</small><strong>', escapeHtml(formatGrams(spool.remaining_g)),
    '</strong></div><div><small>ORIGINAL WEIGHT</small><strong>',
    escapeHtml(formatGrams(spool.initial_g)), '</strong></div><div><small>STATUS</small>',
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
    showToast(id ? "Filament updated." : "Filament added.");
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
    showToast("Spool created.");
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
    showToast("Movement saved. Remaining: " + formatGrams(result.remaining_g));
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
    showToast("Spool details saved.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setSubmitting(form, false);
  }
}

async function archiveSpool() {
  const id = Number($("#edit-spool-form").elements.namedItem("spool_id").value);
  if (!window.confirm("Archive this spool? Its movement history will be retained.")) return;
  try {
    await payloadRequest("POST", "/api/spools/" + id + "/archive");
    $("#edit-spool-dialog").close();
    await refresh();
    showToast("Spool archived.");
  } catch (error) {
    showToast(error.message, true);
  }
}

function openCSVDialog() {
  const form = $("#csv-form");
  form.reset();
  state.csvBytes = null;
  $("#csv-import-submit").disabled = true;
  $("#csv-preview").textContent = "Select a CSV inventory v1 file. Existing spool and product UUIDs will not be overwritten.";
  $("#csv-dialog").showModal();
}

async function previewCSV() {
  const input = $("#csv-file");
  const file = input.files && input.files[0];
  state.csvBytes = null;
  $("#csv-import-submit").disabled = true;
  if (!file) {
    $("#csv-preview").textContent = "No file selected.";
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    $("#csv-preview").textContent = "The file exceeds the 2 MiB import limit.";
    return;
  }
  $("#csv-preview").textContent = "Validating CSV …";
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const result = await api("/api/import/inventory.csv?dry_run=true", {
      method: "POST", headers: { "Content-Type": "text/csv" }, body: bytes
    });
    // Discard a stale response if the user has selected a different file.
    if (input.files[0] !== file) return;
    state.csvBytes = bytes;
    $("#csv-preview").textContent =
      "Preview: " + result.products_created + " new filament products, " +
      result.spools_created + " new spools. Skipped: " +
      result.products_skipped + " known products, " +
      result.spools_skipped + " known spools. Existing inventory will not be overwritten.";
    $("#csv-import-submit").disabled = false;
  } catch (error) {
    $("#csv-preview").textContent = "Import validation failed: " + error.message;
    showToast("CSV validation failed: " + error.message, true);
  }
}

async function submitCSV(event) {
  event.preventDefault();
  if (!state.csvBytes) return;
  if (!window.confirm("Import the previewed inventory? Existing records are never overwritten.")) return;
  const form = event.currentTarget;
  setSubmitting(form, true);
  try {
    const result = await api("/api/import/inventory.csv?dry_run=false", {
      method: "POST", headers: { "Content-Type": "text/csv" }, body: state.csvBytes
    });
    $("#csv-dialog").close();
    state.csvBytes = null;
    await refresh();
    showToast("Imported " + result.products_created + " products and " +
      result.spools_created + " spools. Existing items skipped.");
    setView("spools");
  } catch (error) {
    showToast("Import failed: " + error.message, true);
  } finally {
    setSubmitting(form, false);
  }
}

async function openScannedSpool() {
  const uid = new URLSearchParams(window.location.search).get("spool");
  if (!uid) return;
  history.replaceState(null, "", window.location.pathname);
  const spool = state.spools.find(item => item.uid === uid);
  if (!spool) {
    showToast("This spool is unavailable or archived.", true);
    return;
  }
  setView("spools");
  await openEditSpoolDialog(spool.id);
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
      case "import-csv": openCSVDialog(); break;
      case "label": window.open("/labels/" + encodeURIComponent(action.dataset.uid), "_blank", "noopener"); break;
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
  $("#csv-file").addEventListener("change", previewCSV);
  $("#csv-form").addEventListener("submit", submitCSV);
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
  refresh().then(openScannedSpool);
}

document.addEventListener("DOMContentLoaded", initialize);
