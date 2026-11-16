/* IPO Form Filler — single-page front end (no build step, no dependencies). */
"use strict";

// ------------------------------------------------------------------ helpers
const app = document.getElementById("app");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

let toastTimer;
function toast(msg, isError = false) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2800);
}

const getPath = (obj, path) => path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
function setPath(obj, path, value) {
  const keys = path.split(".");
  let o = obj;
  keys.slice(0, -1).forEach((k, i) => {
    if (o[k] == null) o[k] = /^\d+$/.test(keys[i + 1]) ? [] : {};
    o = o[k];
  });
  o[keys[keys.length - 1]] = value;
}

const fmtDate = (iso) => (iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split("-").reverse().join("/") : iso || "");
const clientName = (c) => {
  const names = (c.applicants || []).map((a) => a.name).filter(Boolean);
  if (!names.length) return "Unnamed client";
  return names[0] + (names.length > 1 ? ` + ${names.length - 1} more` : "");
};

let formsCache = null;
async function getForms() {
  if (!formsCache) formsCache = await api("GET", "/api/forms");
  return formsCache;
}

// ------------------------------------------------------------------ constants
const CATEGORIES = [
  ["natural_person", "Natural person (individual)"],
  ["startup", "Startup"],
  ["small_entity", "Small entity"],
  ["educational_institution", "Educational institution"],
  ["other", "Other than natural person (company / others)"],
];
const CATEGORY_LABEL = Object.fromEntries(CATEGORIES);
const APP_TYPES = [
  ["ordinary", "Ordinary"], ["convention", "Convention"], ["pct_np", "PCT National Phase"],
  ["pph", "PPH"], ["divisional", "Divisional"], ["patent_of_addition", "Patent of Addition"],
];
const GENDERS = [["", "—"], ["male", "Male"], ["female", "Female"], ["others", "Others"], ["not_disclosed", "Prefer not to disclose"]];
const OFFICES = [["", "— Select —"], ["delhi", "Delhi"], ["mumbai", "Mumbai"], ["chennai", "Chennai"], ["kolkata", "Kolkata"]];
// Territorial jurisdiction of the four patent offices (Patents Rules, rule 4).
const OFFICE_BY_STATE = {
  delhi: ["haryana", "himachal pradesh", "jammu", "kashmir", "ladakh", "punjab", "rajasthan", "uttar pradesh", "uttarakhand", "uttaranchal", "delhi", "chandigarh"],
  mumbai: ["gujarat", "maharashtra", "madhya pradesh", "goa", "chhattisgarh", "dadra", "daman", "diu"],
  chennai: ["andhra pradesh", "telangana", "karnataka", "kerala", "tamil nadu", "puducherry", "pondicherry", "lakshadweep"],
  kolkata: ["bihar", "jharkhand", "odisha", "orissa", "west bengal", "sikkim", "assam", "arunachal", "manipur", "meghalaya", "mizoram", "nagaland", "tripura", "andaman", "nicobar"],
};
function suggestOffice(state) {
  const s = (state || "").toLowerCase().trim();
  if (!s) return "";
  for (const [office, states] of Object.entries(OFFICE_BY_STATE)) {
    if (states.some((x) => s.includes(x))) return office;
  }
  return "";
}

const blankAddress = () => ({ house_no: "", street: "", city: "", state: "", pin_code: "", country: "India" });
const blankPerson = (kind = "individual") => ({ kind, name: "", gender: "", age: "", nationality: "India", country_of_residence: "India",
  email: "", mobile: "", telephone: "", address: blankAddress() });
const blankProject = () => ({ id: "", name: "", invention_title: "", application_number: "", filing_date: "",
  patent_number: "", grant_date: "", application_type: [], inventors: [] });
const blankClient = () => ({
  client_type: "individual", applicant_category: "",
  applicants: [blankPerson()], projects: [blankProject()],
  agent: { name: "", inpa_number: "", mobile: "", email: "", address: blankAddress() },
  service: { name: "", telephone: "", mobile: "", fax: "", email: "", address: blankAddress() },
  signatory: { name: "", designation: "" },
  patent_office: "", notes: "",
});
function normalise(c) {
  const b = blankClient();
  const out = { ...b, ...c };
  for (const k of ["agent", "service", "signatory"]) out[k] = { ...b[k], ...(c[k] || {}) };
  for (const k of ["agent", "service"]) out[k].address = { ...blankAddress(), ...((c[k] || {}).address || {}) };
  const person = (p) => ({ ...blankPerson(), ...p, address: { ...blankAddress(), ...(p.address || {}) } });
  const defaultKind = c.client_type === "organisation" ? "organisation" : "individual";
  out.applicants = (c.applicants && c.applicants.length ? c.applicants : [blankPerson(defaultKind)])
    .map((p) => person({ kind: defaultKind, ...p }));
  out.projects = (c.projects || []).map((p) => ({ ...blankProject(), ...p,
    application_type: p.application_type || [], inventors: (p.inventors || []).map(person) }));
  return out;
}

const projectLabel = (p) => p.name || p.invention_title || p.application_number || "Untitled project";
const pickProject = (c, pid) => (c.projects || []).find((p) => p.id === pid) || (pid === "none" ? null : (c.projects || [])[0] || null);
const projectQuery = (p) => `?p=${p ? p.id : "none"}`;
// A link can name a project that has since been removed: say so rather than
// silently showing a different one.
function noteMissingProject(c, proj) {
  const asked = query.get("p");
  if (asked && asked !== "none" && (!proj || proj.id !== asked)) {
    toast(proj ? `That project no longer exists — showing "${projectLabel(proj)}" instead.`
      : "That project no longer exists — showing client details only.", true);
  }
}

function projectSelect(c, current) {
  if (!(c.projects || []).length) return '<span class="muted small">No projects saved — only client details will be filled.</span>';
  const opts = c.projects.map((p) => `<option value="${p.id}"${current && current.id === p.id ? " selected" : ""}>${esc(projectLabel(p))}${p.application_number ? " (" + esc(p.application_number) + ")" : ""}</option>`).join("");
  return `<label class="field project-pick">Project / invention
    <select id="project">${opts}<option value="none"${current ? "" : " selected"}>No specific project (client details only)</option></select></label>`;
}

// ------------------------------------------------------------------ router
const routes = [
  [/^#?\/?$/, pageHome],
  [/^#\/client\/new$/, () => pageClientForm(null)],
  [/^#\/client\/(c_[0-9a-f]{8})\/edit$/, (id) => pageClientForm(id)],
  [/^#\/client\/(c_[0-9a-f]{8})\/forms$/, pageFormPicker],
  [/^#\/client\/(c_[0-9a-f]{8})\/form\/(form_[0-9a-z]+)$/, pagePreview],
];
let returnTo = null;   // where the client form goes back to after Save/Cancel
let query = new URLSearchParams();
let routeSeq = 0;   // pages that finish loading after a newer navigation are discarded

// Unsaved edits on the client page: leaving asks first.
let dirty = false;
let currentHash = location.hash;
let skipNextRoute = false;
const markDirty = () => {
  dirty = true;
  const s = document.getElementById("save-status");
  if (s) { s.textContent = "Unsaved changes"; s.className = "save-status unsaved"; }
  scheduleDraft();
};

// While editing, unsaved changes are also kept in this browser (a "draft"), so
// a closed tab, crash or power cut doesn't lose them. Offered back on return.
const DRAFT_PREFIX = "ipo-form-filler:draft:";
let draftKey = null;        // the client page currently open ("…:new" or "…:c_xxxx")
let draftTimer = null;
let pendingDraft = null;    // a draft found when the page opened, not yet restored
const storeGet = (k) => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch { return null; } };
const storeSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage off: no drafts */ } };
const storeDel = (k) => { try { localStorage.removeItem(k); } catch { /* ignore */ } };
function scheduleDraft() {
  if (!draftKey) return;
  clearTimeout(draftTimer);
  const key = draftKey;
  draftTimer = setTimeout(() => { if (dirty && draftKey === key) storeSet(key, { at: Date.now(), state }); }, 800);
}
function clearDraft() {
  clearTimeout(draftTimer);
  if (draftKey) storeDel(draftKey);
}
window.addEventListener("beforeunload", (e) => {
  if (dirty) {
    if (draftKey) storeSet(draftKey, { at: Date.now(), state });   // keep even the last keystrokes
    e.preventDefault(); e.returnValue = "";
  }
});
window.addEventListener("pagehide", () => {
  if (dirty && draftKey) storeSet(draftKey, { at: Date.now(), state });
});

async function route() {
  if (skipNextRoute) { skipNextRoute = false; return; }
  if (dirty && location.hash !== currentHash) {
    if (!confirm("You have unsaved changes to this client. Leave without saving them?")) {
      skipNextRoute = true;
      location.hash = currentHash;   // stay put
      return;
    }
    clearDraft();   // the user chose to discard them
  }
  clearTimeout(draftTimer);
  draftKey = null;
  pendingDraft = null;
  dirty = false;
  currentHash = location.hash;
  const hash = location.hash.split("?")[0];
  query = new URLSearchParams(location.hash.split("?")[1] || "");
  returnTo = query.get("return");
  routeSeq++;
  window.scrollTo(0, 0);
  for (const [re, fn] of routes) {
    const m = hash.match(re);
    if (m) {
      app.innerHTML = '<div class="loading">Loading…</div>';
      try { await fn(...m.slice(1)); } catch (e) { app.innerHTML = `<div class="card empty">${esc(e.message)}<br><br><a class="btn" href="#/">Back to home</a></div>`; }
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);

// ------------------------------------------------------------------ page: home
async function pageHome() {
  app.oninput = app.onchange = app.onclick = null;   // drop the client page's handlers
  const seq = routeSeq;
  const [clients, forms] = await Promise.all([api("GET", "/api/clients"), getForms()]);
  if (seq !== routeSeq) return;
  document.title = "IPO Form Filler";
  const nProj = (c) => (c.projects || []).length;
  const options = clients.map((c) => `<option value="${c.id}">${esc(clientName(c))}${nProj(c) ? ` — ${nProj(c)} project${nProj(c) === 1 ? "" : "s"}` : ""}</option>`).join("");

  app.innerHTML = `
    <section class="hero">
      <h1>Welcome</h1>
      <p class="muted">Save a client's common details once — applicants, inventors, invention, agent and address for service —
      then pick any Indian Patent Office form and download it pre-filled as an editable Word document.</p>
      <div class="stats">
        <div class="stat"><b>${clients.length}</b><span class="muted">saved client${clients.length === 1 ? "" : "s"}</span></div>
        <div class="stat"><b>${forms.length}</b><span class="muted">IPO forms (Form 1 – Form 31)</span></div>
      </div>
    </section>

    <section class="choices">
      <div class="card choice">
        <div class="icon" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="8" r="4"/><path d="M2 21c0-4 3-6 7-6s7 2 7 6M19 8v6M16 11h6"/></svg></div>
        <div><h2>Add new client</h2><p>Enter a person or company's details once. They are reused across every form.</p></div>
        <div class="row"><a class="btn primary lg" href="#/client/new">+ Add new client</a></div>
      </div>
      <div class="card choice">
        <div class="icon" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="8" r="4"/><path d="M2 21c0-4 3-6 7-6s7 2 7 6M17 3a4 4 0 0 1 0 8M22 21c0-3-2-5-4-6"/></svg></div>
        <div><h2>Existing client</h2><p>Choose a saved client to select and download a form.</p></div>
        <div class="row">
          <select id="pick" aria-label="Choose a client" ${clients.length ? "" : "disabled"}>
            ${clients.length ? `<option value="">Select a client…</option>${options}` : "<option>No clients saved yet</option>"}
          </select>
          <button class="btn primary" id="open" disabled>Open</button>
        </div>
      </div>
    </section>

    <section class="card client-list">
      <div class="card-head">
        <div><h2>Your clients</h2><p class="muted small">Select a client to choose a form, or edit their details.</p></div>
        ${clients.length > 5 ? '<input type="search" id="filter" placeholder="Search clients…" style="max-width:240px">' : ""}
      </div>
      <div id="rows">
        ${clients.length ? clients.map(clientRow).join("") : '<div class="empty">No clients yet. Use <b>Add new client</b> to create the first one.</div>'}
      </div>
    </section>`;

  const pick = document.getElementById("pick");
  const open = document.getElementById("open");
  pick.addEventListener("change", () => (open.disabled = !pick.value));
  open.addEventListener("click", () => pick.value && (location.hash = `#/client/${pick.value}/forms`));
  const filter = document.getElementById("filter");
  if (filter) filter.addEventListener("input", () => {
    const q = filter.value.toLowerCase();
    document.querySelectorAll(".client-row").forEach((r) => (r.hidden = !r.textContent.toLowerCase().includes(q)));
  });
}

function clientRow(c) {
  const projects = c.projects || [];
  const meta = [
    CATEGORY_LABEL[c.applicant_category],
    projects.length ? `${projects.length} project${projects.length === 1 ? "" : "s"}: ${projects.slice(0, 3).map(projectLabel).join(", ")}${projects.length > 3 ? ", …" : ""}` : "No projects yet",
  ].filter(Boolean).map(esc).join(" · ");
  return `<div class="client-row">
    <div><div class="name">${esc(clientName(c))}</div><div class="meta">${meta}</div></div>
    <div class="actions">
      <a class="btn primary sm" href="#/client/${c.id}/forms">Select form</a>
      <a class="btn sm" href="#/client/${c.id}/edit">Edit details</a>
    </div></div>`;
}

// ------------------------------------------------------------------ page: client form
let state = null;

// `check` names a rule in CHECKS (format validation, shown under the field).
const inputField = (path, label, { type = "text", req = false, hint = "", wide = false, placeholder = "", name = false, check = "" } = {}) => {
  const value = getPath(state, path);
  const badEmail = type === "email" && value && !isEmail(value);
  const result = check && value ? runCheck(check, value, path) : {};
  const invalid = badEmail || !!result.error;
  const rule = CHECKS[check];
  const extra = (name ? ' data-name="1" autocapitalize="words"' : "")
    + (check ? ` data-check="${check}"` : "")
    + (rule?.max ? ` maxlength="${rule.max}"` : "")
    + (rule?.numeric ? ' inputmode="numeric"' : "")
    + (type === "date" ? ` max="${todayISO()}" min="1970-01-01"` : "")
    + (type === "email" ? ' autocomplete="email" spellcheck="false"' : "")
    + (invalid ? ' class="invalid" aria-invalid="true"' : "");
  if (type === "email" && !placeholder) placeholder = "name@example.com";
  if (rule?.placeholder && !placeholder) placeholder = rule.placeholder;
  const message = badEmail ? "Enter a valid e-mail, like name@example.com" : result.error || "";
  return `
  <label class="field${wide ? " wide" : ""}"><span>${esc(label)}${req ? ' <span class="req">*</span>' : ""}</span>
    ${type === "textarea"
      ? `<textarea data-path="${path}" rows="3" placeholder="${esc(placeholder)}"${extra}>${esc(value)}</textarea>`
      : `<input type="${type === "email" ? "text" : type}" ${type === "email" ? 'data-email="1" inputmode="email"' : ""} data-path="${path}" value="${esc(value)}" placeholder="${esc(placeholder)}"${extra}>`}
    ${type === "email" || check ? `<span class="field-error"${message ? "" : " hidden"}>${esc(message)}</span>` : ""}
    ${check ? `<span class="field-warn"${result.warn && !message ? "" : " hidden"}>${esc(result.warn || "")}</span>` : ""}
    ${hint ? `<span class="hint">${esc(hint)}</span>` : ""}
  </label>`;
};

// ------------------------------------------------------------------ format rules
// Each rule returns { error } (blocks Save), { warn } (advice only) and/or
// { value } (the tidied form). Blank values are always fine: nothing is mandatory.
// The server applies the same blocking rules (ipoforms/validation.py).
const pad2 = (n) => String(n).padStart(2, "0");
const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; };
const OFFICE_CODES = { 11: "delhi", 21: "mumbai", 31: "chennai", 41: "kolkata" };
const OFFICE_NAME = { delhi: "Delhi", mumbai: "Mumbai", chennai: "Chennai", kolkata: "Kolkata" };
const sibling = (path, field) => getPath(state, path.replace(/[^.]+$/, field));

function textRule({ max, digits = true, symbols = "", letters = true, label = "" }) {
  // letters (any script), spaces and the listed symbols; optionally digits
  const allowed = new RegExp(`^[\\p{L}\\p{M}\\s${digits ? "\\d" : ""}${symbols.replace(/[\]\\^-]/g, "\\$&")}]*$`, "u");
  return {
    max,
    fn(v) {
      const s = v.replace(/\s+/g, " ").trim();
      if (!digits && /\d/.test(s)) return { error: `${label} shouldn't contain numbers.` };
      if (!allowed.test(s)) {
        const bad = [...new Set([...s].filter((ch) => !allowed.test(ch)))].join(" ");
        return { error: `${label} can't contain: ${bad}` };
      }
      if (letters && !/\p{L}/u.test(s)) return { error: `${label} needs at least one letter.` };
      return { value: s };
    },
  };
}

const CHECKS = {
  personName: textRule({ max: 100, digits: false, symbols: ".'’-", label: "A person's name" }),
  orgName: textRule({ max: 200, symbols: ".,'’-&()/+:", label: "A name" }),
  place: textRule({ max: 60, digits: false, symbols: ".'’-()&", label: "A place name" }),
  // Districts / cities can contain numbers: "North 24 Parganas", "Sector 62".
  city: textRule({ max: 60, symbols: ".'’-()&,", label: "A city / district name" }),
  designation: textRule({ max: 80, digits: false, symbols: ".,'’-&()/", label: "A designation" }),
  house: { max: 100, fn: (v) => ({ value: v.replace(/\s+/g, " ").trim() }) },
  projectName: { max: 100, fn: (v) => ({ value: v.replace(/\s+/g, " ").trim() }) },
  notes: { max: 2000, fn: () => ({}) },

  // Age in whole years (asked for natural persons on Form 1; optional).
  age: { max: 3, numeric: true, placeholder: "Optional", fn: (v) => ageRule(v, false) },
  applicantAge: { max: 3, numeric: true, placeholder: "Optional", fn: (v) => ageRule(v, true) },

  title: {
    max: 500,
    fn(v) {
      const s = v.replace(/\s+/g, " ").trim();
      const words = s ? s.split(" ").length : 0;
      return { value: s, warn: words > 15 ? `The Patent Office expects a brief title — ideally 15 words or fewer (this has ${words}).` : "" };
    },
  },

  // Indian patent application number. Since 2007: 12 digits = filing year (4)
  // + office code (2: 11 Delhi, 21 Mumbai, 31 Chennai, 41 Kolkata) + serial (6),
  // e.g. 202441012345. Older applications: 1234/DEL/2006, 567/CHENP/2008.
  appno: {
    max: 20,
    placeholder: "e.g. 202441012345",
    fn(v, path) {
      let s = v.toUpperCase().replace(/[\s-]/g, "");
      if (/^IN\d+$/.test(s)) s = s.slice(2);
      if (/^\d+$/.test(s)) {
        if (s.length !== 12) return { error: `An application number has 12 digits — this has ${s.length} (e.g. 202441012345).` };
        const year = +s.slice(0, 4), office = OFFICE_CODES[s.slice(4, 6)], now = new Date().getFullYear();
        if (year < 2005 || year > now) return { error: `The first 4 digits are the filing year (2005–${now}); "${s.slice(0, 4)}" isn't.` };
        if (!office) return { error: `Digits 5–6 are the office code — 11 Delhi, 21 Mumbai, 31 Chennai or 41 Kolkata; "${s.slice(4, 6)}" isn't one.` };
        const warns = [];
        const filed = sibling(path, "filing_date");
        if (filed && +filed.slice(0, 4) !== year) warns.push(`The number says ${year} but the filing date is in ${filed.slice(0, 4)} (fine for PCT national phase).`);
        if (state.patent_office && state.patent_office !== office) warns.push(`This number is from the ${OFFICE_NAME[office]} office; the client's patent office is ${OFFICE_NAME[state.patent_office]}.`);
        return { value: s, warn: warns.join(" ") };
      }
      const old = s.match(/^(\d{1,5})\/(DEL|MUM|CHE|KOL)(NP)?\/((?:19|20)\d{2})$/);
      if (old) return { value: s };
      return { error: "Use the 12-digit number (e.g. 202441012345) or the older style 1234/DEL/2006." };
    },
  },

  patentno: {
    max: 12,
    placeholder: "e.g. 512345",
    fn(v) {
      let s = v.toUpperCase().replace(/[\s,.-]/g, "");
      if (s.startsWith("IN")) s = s.slice(2);
      if (!/^\d+$/.test(s)) return { error: "A patent number is digits only (e.g. 512345)." };
      if (s.length > 7) return { error: `A patent number has at most 7 digits — this has ${s.length}.` };
      return { value: s };
    },
  },

  inpa: {
    max: 12,
    placeholder: "IN/PA-1234",
    fn(v) {
      const s = v.toUpperCase().replace(/\s+/g, "");
      const m = s.match(/^(?:IN\/?PA[-/]?)?(\d{1,5})$/);
      return m ? { value: `IN/PA-${m[1]}` } : { error: "Use the registration number format IN/PA-1234." };
    },
  },

  filingDate: {
    fn(v) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return { error: "Enter a complete date." };
      if (v > todayISO()) return { error: "The filing date can't be in the future." };
      if (v < "1970-01-01") return { error: "The filing date can't be before 1970." };
      return {};
    },
  },
  grantDate: {
    fn(v, path) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return { error: "Enter a complete date." };
      if (v > todayISO()) return { error: "The grant date can't be in the future." };
      const filed = sibling(path, "filing_date");
      if (filed && v < filed) return { error: "The grant date can't be before the filing date." };
      return {};
    },
  },
};

function ageRule(v, applicant) {
  const s = v.trim();
  if (!/^\d+$/.test(s)) return { error: "Age is a whole number of years, e.g. 34." };
  const n = +s;
  if (n < 1 || n > 120) return { error: "Age must be between 1 and 120." };
  const warn = applicant && n < 18 ? "Under 18 — a minor normally applies through a guardian."
    : n > 100 ? "Over 100 — please double-check." : "";
  return { value: String(n), warn };
}

function runCheck(check, value, path) {
  const v = String(value ?? "");
  if (!v.trim()) return {};
  const rule = CHECKS[check];
  if (!rule) return {};
  if (rule.max && v.trim().length > rule.max) return { error: `Too long — at most ${rule.max} characters.` };
  return rule.fn(v, path) || {};
}

// Show / clear the message under a checked field; tidy when valid. Returns validity.
function checkField(el, tidy = true) {
  const path = el.dataset.path;
  // A partly typed date reads as empty; the browser flags it as badInput.
  const r = el.type === "date" && el.validity?.badInput
    ? { error: "Incomplete date — enter day, month and year, or clear it." }
    : runCheck(el.dataset.check, el.value, path);
  if (tidy && !r.error && r.value !== undefined && r.value !== el.value) { el.value = r.value; setPath(state, path, r.value); }
  el.classList.toggle("invalid", !!r.error);
  el.setAttribute("aria-invalid", r.error ? "true" : "false");
  const label = el.closest("label");
  const err = label.querySelector(".field-error"), warn = label.querySelector(".field-warn");
  err.textContent = r.error || ""; err.hidden = !r.error;
  if (warn) { warn.textContent = r.warn || ""; warn.hidden = !r.warn || !!r.error; }
  return !r.error;
}

// Fields whose advice depends on another field are re-checked when it changes.
function recheckRelated(path) {
  const base = path.replace(/[^.]+$/, "");
  if (/\.filing_date$/.test(path)) {
    for (const f of ["grant_date", "application_number"]) {
      const el = app.querySelector(`[data-path="${base}${f}"]`);
      if (el && el.value) checkField(el, false);
    }
  }
  if (path === "patent_office") app.querySelectorAll('[data-check="appno"]').forEach((el) => el.value && checkField(el, false));
}

// ------------------------------------------------------------------ e-mail & names
const EMAIL_RE = /^[^\s@]+@[^\s@.]+(\.[^\s@.]+)*\.[a-z]{2,}$/i;
const isEmail = (v) => EMAIL_RE.test(String(v || "").trim());

function checkEmail(el) {
  const v = el.value.trim();
  if (v !== el.value) { el.value = v; setPath(state, el.dataset.path, v); }
  const bad = !!v && !isEmail(v);
  el.classList.toggle("invalid", bad);
  el.setAttribute("aria-invalid", bad ? "true" : "false");
  const msg = el.parentElement.querySelector(".field-error");
  if (msg) msg.hidden = !bad;
  return !bad;
}

// "acme innovations pvt ltd" -> "Acme Innovations Pvt Ltd", "o'brien" -> "O'Brien",
// "s. mehta" -> "S. Mehta". Words typed with capitals inside them (IBM, McKinsey,
// iPhone) are left exactly as typed.
const KEEP_LOWER = new Set(["of", "and", "the", "for", "in", "on", "at", "to", "by", "de", "da", "van", "von", "bin", "binti"]);
const UPPER_WORDS = new Set(["llp", "llc", "plc", "iit", "nit", "iisc", "iiit", "isro", "drdo", "csir", "icar", "aiims", "opc", "huf", "ii", "iii", "iv"]);
function capitalizeName(text) {
  return String(text || "").replace(/\s+/g, " ").trim().split(" ").map((word, i) => {
    if (!word) return word;
    if (/[A-Z]/.test(word.slice(1)) || /^[A-Z]{2,}$/.test(word)) return word;     // deliberate capitals
    const lower = word.toLowerCase();
    const bare = lower.replace(/[^a-z]/g, "");
    if (UPPER_WORDS.has(bare)) return word.toUpperCase();
    if (i > 0 && KEEP_LOWER.has(lower)) return lower;
    return lower.replace(/(^|[-'’.(/])([a-z])/g, (m, sep, ch) => sep + ch.toUpperCase());
  }).join(" ");
}

function fixName(el) {
  const v = capitalizeName(el.value);
  if (v !== el.value) { el.value = v; setPath(state, el.dataset.path, v); }
}

const selectField = (path, label, options, { hint = "" } = {}) => {
  const cur = getPath(state, path) || "";
  return `<label class="field">${esc(label)}
    <select data-path="${path}">${options.map(([v, l]) => `<option value="${v}"${v === cur ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
    ${hint ? `<span class="hint">${esc(hint)}</span>` : ""}</label>`;
};

// ------------------------------------------------------------------ pickers
// Searchable drop-downs: type "In" and choose "India". The typed text is never
// saved as-is (except for free-text pickers such as Area / Locality); leaving
// the field picks the best match, or restores the previous value.
const COUNTRY_ALIASES = {
  "United States": "usa us america united states of america", "United Kingdom": "uk britain great britain england gb",
  "United Arab Emirates": "uae emirates dubai", "South Korea": "korea republic of korea", "North Korea": "dprk",
  "Russia": "russian federation", "Netherlands": "holland", "Czech Republic": "czechia", "Côte d'Ivoire": "ivory coast",
  "Eswatini": "swaziland", "Myanmar": "burma", "Timor-Leste": "east timor", "Congo (Democratic Republic)": "drc",
  "Turkey": "turkiye", "Vietnam": "viet nam", "Taiwan": "chinese taipei",
};
const DIAL_OPTIONS = (() => {
  const top = ["IN", "US", "GB"];
  const rows = COUNTRIES.map(([name, iso, dial]) => ({ value: dial, label: `${dial}  ${name}`, iso,
    search: `${dial} ${dial.slice(1)} ${name} ${COUNTRY_ALIASES[name] || ""} ${iso}`.toLowerCase() }));
  return [...top.map((iso) => rows.find((r) => r.iso === iso)), ...rows.filter((r) => !top.includes(r.iso))];
})();
const localities = {};   // address path -> post-office / place names from the last PIN lookup

const COUNTRY_OPTIONS = [
  ...COUNTRIES.filter((c) => c[0] === "India"), ...COUNTRIES.filter((c) => c[0] !== "India"),
].map(([n, iso]) => ({ value: n, label: n, search: `${n} ${COUNTRY_ALIASES[n] || ""} ${iso}`.toLowerCase() }));

function comboOptions(source, path) {
  if (source === "country") return COUNTRY_OPTIONS;
  if (source === "dial") return DIAL_OPTIONS;
  if (source === "locality") return (localities[path] || []).map((n) => ({ value: n, label: n, search: n.toLowerCase() }));
  return [];
}

function filterOptions(opts, text) {
  const q = text.trim().toLowerCase();
  if (!q) return opts;
  const exact = [], starts = [], words = [], contains = [];
  for (const o of opts) {
    const tokens = o.search.split(/[\s(),]+/);
    if (o.label.toLowerCase() === q || (q.length <= 3 && tokens.includes(q))) exact.push(o);   // "uk", "usa", "in"
    else if (o.search.startsWith(q) || o.label.toLowerCase().startsWith(q)) starts.push(o);
    else if (tokens.some((w) => w.startsWith(q))) words.push(o);
    else if (q.length >= 4 && o.search.includes(q)) contains.push(o);
  }
  return [...exact, ...starts, ...words, ...contains];
}

const comboField = (path, label, source, { free = false, wide = false, max = 0, placeholder = "Type to search, e.g. In" } = {}) => `
  <label class="field${wide ? " wide" : ""}"><span>${esc(label)}</span>
    <div class="combo">
      <input type="text" data-combo-path="${path}" data-source="${source}" data-free="${free ? 1 : 0}"${max ? ` maxlength="${max}"` : ""}
        value="${esc(getPath(state, path))}" placeholder="${esc(placeholder)}" autocomplete="off"
        role="combobox" aria-autocomplete="list" aria-expanded="false">
      <ul class="combo-list" role="listbox" hidden></ul>
    </div>
  </label>`;

function splitPhone(v) {
  const m = String(v || "").match(/^(\+\d{1,4})\s*(.*)$/);
  return m ? { code: m[1], number: m[2] } : { code: "+91", number: String(v || "") };
}

// ------------------------------------------------------------------ phone numbers
// India (+91): 10 digits; mobiles start with 6-9. A landline is its STD code +
// number without the leading 0 (080 2345 6789 -> 80 2345 6789), also 10 digits.
// +1 (US/Canada): 10 digits. Elsewhere: 4-14 digits.
const phoneKind = (path) => (/\.mobile$/.test(path) ? "mobile" : "landline");

function phoneDigits(code, number) {
  let d = String(number || "").replace(/\D/g, "");
  const cc = code.replace("+", "");
  if (d.length > 10 && d.startsWith(cc) && (code === "+91" || code === "+1")) d = d.slice(cc.length);   // pasted with country code
  if (code === "+91" && d.length === 11 && d.startsWith("0")) d = d.slice(1);                          // trunk 0
  return d;
}

function phoneProblem(code, number, kind) {
  const d = phoneDigits(code, number);
  if (!d) return "";
  if (code === "+91") {
    if (d.length !== 10) return `Indian numbers have 10 digits — this has ${d.length}.`;
    if (kind === "mobile" && !/^[6-9]/.test(d)) return "Indian mobile numbers start with 6, 7, 8 or 9.";
    return "";
  }
  if (code === "+1") return d.length === 10 ? "" : `US / Canada numbers have 10 digits — this has ${d.length}.`;
  return d.length >= 4 && d.length <= 14 ? "" : `Enter a valid number for ${code}.`;
}

// Tidy layout once the number is valid: +91 mobile "98765 43210", +1 "416 555 0100".
// Landlines and other countries keep the spacing you typed (e.g. "080 2345 6789").
function formatPhone(code, number, kind) {
  const d = phoneDigits(code, number);
  if (code === "+91" && d.length === 10 && kind === "mobile") return `${d.slice(0, 5)} ${d.slice(5)}`;
  if (code === "+1" && d.length === 10) return `${d.slice(0, 3)} ${d.slice(3, 6)} ${d.slice(6)}`;
  return String(number || "").replace(/\s+/g, " ").trim();
}

function phoneField(path, label) {
  const { code, number } = splitPhone(getPath(state, path));
  const kind = phoneKind(path);
  const problem = phoneProblem(code, number, kind);
  return `<label class="field"><span>${esc(label)}</span>
    <div class="phone" data-phone-path="${path}" data-kind="${kind}">
      <div class="combo dial">
        <input type="text" data-dial-for="${path}" data-source="dial" value="${esc(code)}" data-code="${esc(code)}"
          autocomplete="off" role="combobox" aria-label="${esc(label)} country code" aria-expanded="false">
        <ul class="combo-list" role="listbox" hidden></ul>
      </div>
      <input type="tel" data-phone-number="${path}" value="${esc(number)}" inputmode="tel"
        placeholder="${code === "+91" ? (kind === "mobile" ? "10-digit mobile" : "STD code + number") : "Number"}"${problem ? ' class="invalid" aria-invalid="true"' : ""}>
    </div>
    <span class="field-error"${problem ? "" : " hidden"}>${esc(problem)}</span></label>`;
}

function updatePhone(path) {
  const box = app.querySelector(`.phone[data-phone-path="${path}"]`);
  if (!box) return;
  const code = box.querySelector("[data-dial-for]").dataset.code;
  const number = box.querySelector("[data-phone-number]").value.trim();
  setPath(state, path, number ? `${code} ${number}` : "");
}

// Show / clear the message under a phone field; tidy a valid number. Returns validity.
function checkPhone(box, tidy = true) {
  const path = box.dataset.phonePath;
  const dial = box.querySelector("[data-dial-for]");
  const input = box.querySelector("[data-phone-number]");
  // A number pasted with its country code ("+91 80 2345 6789", "+44 7700 900123"):
  // move the code into the picker instead of saving it twice.
  const pasted = tidy && input.value.match(/^\s*(\+\d{1,4})[\s-]+/);
  if (pasted && DIAL_OPTIONS.some((o) => o.value === pasted[1])) {
    dial.value = dial.dataset.code = pasted[1];
    input.value = input.value.slice(pasted[0].length);
  }
  const code = dial.dataset.code;
  const problem = phoneProblem(code, input.value, box.dataset.kind);
  if (!problem && tidy && input.value.trim()) input.value = formatPhone(code, input.value, box.dataset.kind);
  input.placeholder = code === "+91" ? (box.dataset.kind === "mobile" ? "10-digit mobile" : "STD code + number") : "Number";
  updatePhone(path);
  input.classList.toggle("invalid", !!problem);
  input.setAttribute("aria-invalid", problem ? "true" : "false");
  const msg = box.parentElement.querySelector(".field-error");
  msg.textContent = problem; msg.hidden = !problem;
  return !problem;
}

// ------------------------------------------------------------------ PIN / postal code format
// [pattern, what it should look like, example]. Countries not listed accept
// 2-10 letters/digits. Checked case-insensitively after tidying.
const POSTCODE_RULES = {
  IN: [/^[1-9]\d{5}$/, "6 digits, not starting with 0", "560001"],
  US: [/^\d{5}(-\d{4})?$/, "5 digits, or ZIP+4", "90210"],
  GB: [/^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$/, "a UK postcode", "SW1A 1AA"],
  CA: [/^[A-Z]\d[A-Z] \d[A-Z]\d$/, "letter-digit-letter digit-letter-digit", "K1A 0B1"],
  IE: [/^[A-Z]\d[\dW] [A-Z\d]{4}$/, "an Eircode", "D02 X285"],
  NL: [/^[1-9]\d{3} [A-Z]{2}$/, "4 digits and 2 letters", "1012 AB"],
  JP: [/^\d{3}-\d{4}$/, "7 digits", "100-0001"],
  BR: [/^\d{5}-\d{3}$/, "8 digits", "01310-100"],
  SE: [/^\d{3} \d{2}$/, "5 digits", "114 55"],
  PT: [/^\d{4}-\d{3}$/, "7 digits", "1000-001"],
  PL: [/^\d{2}-\d{3}$/, "5 digits", "00-950"],
  AU: [/^\d{4}$/, "4 digits", "2000"], NZ: [/^\d{4}$/, "4 digits", "1010"], ZA: [/^\d{4}$/, "4 digits", "2001"],
  CH: [/^\d{4}$/, "4 digits", "8001"], AT: [/^\d{4}$/, "4 digits", "1010"], BE: [/^\d{4}$/, "4 digits", "1000"],
  DK: [/^\d{4}$/, "4 digits", "1050"], NO: [/^\d{4}$/, "4 digits", "0150"], BD: [/^\d{4}$/, "4 digits", "1000"],
  PH: [/^\d{4}$/, "4 digits", "1000"],
  DE: [/^\d{5}$/, "5 digits", "10115"], FR: [/^\d{5}$/, "5 digits", "75001"], IT: [/^\d{5}$/, "5 digits", "00118"],
  ES: [/^\d{5}$/, "5 digits", "28001"], FI: [/^\d{5}$/, "5 digits", "00100"], MX: [/^\d{5}$/, "5 digits", "06000"],
  MY: [/^\d{5}$/, "5 digits", "50000"], TH: [/^\d{5}$/, "5 digits", "10200"], LK: [/^\d{5}$/, "5 digits", "00100"],
  NP: [/^\d{5}$/, "5 digits", "44600"], PK: [/^\d{5}$/, "5 digits", "44000"], KR: [/^\d{5}$/, "5 digits", "03154"],
  TR: [/^\d{5}$/, "5 digits", "34000"], SA: [/^\d{5}$/, "5 digits", "11564"], ID: [/^\d{5}$/, "5 digits", "10110"],
  SG: [/^\d{6}$/, "6 digits", "018956"], CN: [/^\d{6}$/, "6 digits", "100000"], RU: [/^\d{6}$/, "6 digits", "101000"],
  VN: [/^\d{6}$/, "6 digits", "100000"], IL: [/^\d{7}$/, "7 digits", "6100000"],
};
const GENERIC_POSTCODE = [/^[A-Z0-9][A-Z0-9 -]{1,9}$/, "2–10 letters or digits", ""];
// Countries whose code is a plain run of digits (no letters, spaces or hyphens).
const DIGITS_ONLY = new Set(Object.entries(POSTCODE_RULES)
  .filter(([, [re]]) => /^\^\\d\{\d\}\$$/.test(re.source) || re.source === "^[1-9]\\d{5}$").map(([iso]) => iso));

// No country chosen -> no country-specific PIN format (the server does the same).
const isoOfAddress = (base) => isoFor(getPath(state, `${base}.country`) || "") || "";

// Uppercase, single spaces, and the separator each country expects.
function tidyPostcode(iso, v) {
  let s = String(v || "").toUpperCase().replace(/\s+/g, " ").trim();
  const compact = s.replace(/[\s-]/g, "");
  if (iso === "GB" && /^[A-Z0-9]{5,7}$/.test(compact)) s = `${compact.slice(0, -3)} ${compact.slice(-3)}`;
  if ((iso === "CA" || iso === "IE") && compact.length === 6 + (iso === "IE" ? 1 : 0)) s = `${compact.slice(0, 3)} ${compact.slice(3)}`;
  if (iso === "NL" && /^\d{4}[A-Z]{2}$/.test(compact)) s = `${compact.slice(0, 4)} ${compact.slice(4)}`;
  if (iso === "JP" && /^\d{7}$/.test(compact)) s = `${compact.slice(0, 3)}-${compact.slice(3)}`;
  if (iso === "US" && /^\d{9}$/.test(compact)) s = `${compact.slice(0, 5)}-${compact.slice(5)}`;
  if (iso === "BR" && /^\d{8}$/.test(compact)) s = `${compact.slice(0, 5)}-${compact.slice(5)}`;
  if (iso === "SE" && /^\d{5}$/.test(compact)) s = `${compact.slice(0, 3)} ${compact.slice(3)}`;
  if (iso === "PT" && /^\d{7}$/.test(compact)) s = `${compact.slice(0, 4)}-${compact.slice(4)}`;
  if (iso === "PL" && /^\d{5}$/.test(compact)) s = `${compact.slice(0, 2)}-${compact.slice(2)}`;
  if (DIGITS_ONLY.has(iso) && /^[\d\s-]+$/.test(s)) s = compact;
  return s;
}

function pinProblem(iso, v) {
  const s = tidyPostcode(iso, v);
  if (!s) return "";
  const [re, what, example] = POSTCODE_RULES[iso] || GENERIC_POSTCODE;
  if (re.test(s)) return "";
  if (iso === "IN") {
    const d = s.replace(/\D/g, "");
    if (/\D/.test(s)) return "A PIN code has digits only.";
    if (d.length !== 6) return `A PIN code has 6 digits — this has ${d.length}.`;
    return "A PIN code can't start with 0.";
  }
  return `Should be ${what}${example ? ` (e.g. ${example})` : ""}.`;
}

function pinInput(base) {
  const iso = isoOfAddress(base);
  const value = getPath(state, `${base}.pin_code`) || "";
  const problem = pinProblem(iso, value);
  const ex = (POSTCODE_RULES[iso] || GENERIC_POSTCODE)[2];
  return `<input type="text" data-path="${base}.pin_code" data-pin-for="${base}" value="${esc(value)}"
      placeholder="${ex ? `e.g. ${ex}` : "Postal code"}" autocomplete="postal-code" spellcheck="false"
      ${iso === "IN" ? 'inputmode="numeric" maxlength="6"' : 'maxlength="10"'}${problem ? ' class="invalid" aria-invalid="true"' : ""}>
    <span class="field-error"${problem ? "" : " hidden"}>${esc(problem)}</span>`;
}

// Show / clear the format message; tidy a valid code. Returns validity.
function checkPin(input, tidy = true) {
  const base = input.dataset.pinFor;
  const iso = isoOfAddress(base);
  const problem = pinProblem(iso, input.value);
  if (tidy && !problem) {
    const t = tidyPostcode(iso, input.value);
    if (t !== input.value) { input.value = t; setPath(state, `${base}.pin_code`, t); }
  }
  input.classList.toggle("invalid", !!problem);
  input.setAttribute("aria-invalid", problem ? "true" : "false");
  const msg = input.parentElement.querySelector(".field-error");
  msg.textContent = problem; msg.hidden = !problem;
  const ex = (POSTCODE_RULES[iso] || GENERIC_POSTCODE)[2];
  input.placeholder = ex ? `e.g. ${ex}` : "Postal code";
  if (iso === "IN") { input.inputMode = "numeric"; input.maxLength = 6; } else { input.inputMode = "text"; input.maxLength = 10; }
  return !problem;
}

function addressBlock(base) {
  return `<div class="subtle-title">Address <span class="hint" style="text-transform:none;letter-spacing:0;font-weight:400">— choose the country and enter the PIN / postal code; city, state and area fill in automatically</span></div>
    <div class="grid">
      ${comboField(`${base}.country`, "Country", "country")}
      <label class="field"><span>PIN / Postal code</span>
        ${pinInput(base)}
        <span class="hint pin-status" data-pin-status="${base}"></span></label>
      ${inputField(`${base}.city`, "City / District", { check: "city" })}
      ${inputField(`${base}.state`, "State", { check: "place" })}
      ${comboField(`${base}.street`, "Area / Locality / Street", "locality", { free: true, max: 150, placeholder: "Choose after PIN lookup, or type" })}
      ${inputField(`${base}.house_no`, "House / Flat / Building no.", { check: "house" })}
    </div>`;
}

let comboActive = -1;
function comboOpen(input) {
  const list = input.parentElement.querySelector(".combo-list");
  const isDial = !!input.dataset.dialFor;
  const path = input.dataset.comboPath || "";
  const all = comboOptions(input.dataset.source, path.replace(/\.street$/, ""));
  const text = input.dataset.typed === "1" ? input.value : "";
  const opts = filterOptions(all, text).slice(0, 80);
  input._opts = opts;
  if (!opts.length) {
    list.innerHTML = input.dataset.source === "locality"
      ? '<li class="combo-empty">Enter a PIN code above to see areas — or just type</li>'
      : '<li class="combo-empty">No match</li>';
  } else {
    const current = isDial ? input.dataset.code : getPath(state, path);
    comboActive = Math.max(0, input.dataset.typed === "1" ? 0 : opts.findIndex((o) => o.value === current));
    list.innerHTML = opts.map((o, i) => `<li role="option" data-i="${i}" class="${i === comboActive ? "active" : ""}">${esc(o.label)}</li>`).join("");
  }
  list.hidden = false;
  input.setAttribute("aria-expanded", "true");
  list.querySelector(".active")?.scrollIntoView({ block: "nearest" });
}
function comboClose(input) {
  const list = input.parentElement.querySelector(".combo-list");
  list.hidden = true;
  input.setAttribute("aria-expanded", "false");
  input.dataset.typed = "0";
}
function comboChoose(input, opt) {
  if (input.dataset.dialFor) {
    if (input.dataset.code !== opt.value) markDirty();
    input.value = opt.value; input.dataset.code = opt.value;
    updatePhone(input.dataset.dialFor);
    const box = input.closest(".phone");
    if (box.querySelector("[data-phone-number]").value.trim()) checkPhone(box);   // rules depend on the code
  } else {
    if ((getPath(state, input.dataset.comboPath) || "") !== opt.value) markDirty();
    input.value = opt.value;
    setPath(state, input.dataset.comboPath, opt.value);
    if (input.dataset.comboPath.endsWith(".address.country")) {
      const base = input.dataset.comboPath.replace(/\.country$/, "");
      const pinEl = app.querySelector(`[data-pin-for="${base}"]`);
      if (pinEl) checkPin(pinEl);   // the format depends on the country
      pinLookup(base, true);
    }
  }
  comboClose(input);
}
function comboCommit(input) {
  const typed = input.dataset.typed === "1";
  const free = input.dataset.free === "1";
  const text = input.value.trim();
  if (input.dataset.dialFor) {
    if (typed) {
      const hit = filterOptions(DIAL_OPTIONS, text)[0];
      if (hit) return comboChoose(input, hit);
    }
    input.value = input.dataset.code;
    return comboClose(input);
  }
  const path = input.dataset.comboPath;
  if (free) { setPath(state, path, text); return comboClose(input); }
  if (!typed) { input.value = getPath(state, path) || ""; return comboClose(input); }
  if (!text) { setPath(state, path, ""); return comboClose(input); }
  const opts = comboOptions(input.dataset.source, path);
  const exact = opts.find((o) => o.value.toLowerCase() === text.toLowerCase());
  const best = exact || filterOptions(opts, text)[0];
  if (best) return comboChoose(input, best);
  input.value = getPath(state, path) || "";
  comboClose(input);
  toast(`"${text}" is not in the list — please choose from the drop-down`, true);
}

document.addEventListener("focusin", (e) => {
  const t = e.target;
  if (t.matches?.(".combo input")) { t.dataset.typed = "0"; t.select(); comboOpen(t); }
});
document.addEventListener("focusout", (e) => {
  const t = e.target;
  if (t.matches?.(".combo input")) comboCommit(t);
  else if (t.dataset?.email) checkEmail(t);
  else if (t.dataset?.check || t.dataset?.name) {
    if (t.dataset.name) fixName(t);
    if (t.dataset.check) { checkField(t); recheckRelated(t.dataset.path); }   // dates too: catches a half-typed date
  }
  else if (t.dataset?.phoneNumber) checkPhone(t.closest(".phone"));
  else if (t.dataset?.pinFor) checkPin(t);
});
document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.matches?.(".combo input")) { t.dataset.typed = "1"; comboOpen(t); }
  else if (t.dataset?.email && !t.parentElement.querySelector(".field-error").hidden) checkEmail(t);   // clear the error as soon as it's fixed
  else if (t.dataset?.check && /^(age|applicantAge)$/.test(t.dataset.check) && /\D/.test(t.value)) {
    t.value = t.value.replace(/\D/g, ""); setPath(state, t.dataset.path, t.value);   // whole numbers only
    if (!t.closest("label").querySelector(".field-error").hidden) checkField(t, false);
  }
  else if (t.dataset?.check && t.type !== "date" && !t.closest("label").querySelector(".field-error").hidden) checkField(t, false);
  else if (t.dataset?.phoneNumber) {
    const clean = t.value.replace(/[^\d\s\-()+]/g, "");   // numbers only — letters are dropped as you type
    if (clean !== t.value) t.value = clean;
    const box = t.closest(".phone");
    if (!box.parentElement.querySelector(".field-error").hidden) checkPhone(box, false);   // clear once fixed
    else updatePhone(t.dataset.phoneNumber);
  }
  else if (t.dataset?.pinFor) {
    if (isoOfAddress(t.dataset.pinFor) === "IN" && (/\D/.test(t.value) || t.value.length > 6)) {   // Indian PIN: 6 digits only
      t.value = t.value.replace(/\D/g, "").slice(0, 6);
      setPath(state, t.dataset.path, t.value);
    }
    if (!t.parentElement.querySelector(".field-error").hidden) checkPin(t, false);   // clear once fixed
    pinLookup(t.dataset.pinFor, false);
  }
});
document.addEventListener("change", (e) => {
  const t = e.target;
  if (t.dataset?.check && t.type === "date") { checkField(t); recheckRelated(t.dataset.path); }
  else if (t.dataset?.path === "patent_office") recheckRelated("patent_office");
});
// Ctrl+S / Cmd+S on the client page: Save and keep editing.
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "s") {
    const btn = app.querySelector('[data-action="save-stay"]');
    if (btn) { e.preventDefault(); if (!btn.disabled) btn.click(); }
  }
});
document.addEventListener("keydown", (e) => {
  const t = e.target;
  if (!t.matches?.(".combo input")) return;
  const list = t.parentElement.querySelector(".combo-list");
  const opts = t._opts || [];
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (list.hidden) return comboOpen(t);
    comboActive = Math.min(opts.length - 1, Math.max(0, comboActive + (e.key === "ArrowDown" ? 1 : -1)));
    list.querySelectorAll("li").forEach((li, i) => li.classList.toggle("active", i === comboActive));
    list.querySelector(".active")?.scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (!list.hidden && opts[comboActive]) comboChoose(t, opts[comboActive]);
    else comboCommit(t);
  } else if (e.key === "Escape") {
    t.dataset.typed = "0";
    t.value = t.dataset.dialFor ? t.dataset.code : (getPath(state, t.dataset.comboPath) || "");
    comboClose(t);
  }
});
document.addEventListener("mousedown", (e) => {
  const li = e.target.closest?.(".combo-list li[data-i]");
  if (!li) return;
  e.preventDefault();   // keep focus in the input
  const input = li.closest(".combo").querySelector("input");
  comboChoose(input, input._opts[+li.dataset.i]);
});

// ------------------------------------------------------------------ PIN lookup
const pinTimers = {};
const isoFor = (country) => (COUNTRIES.find((c) => c[0].toLowerCase() === String(country || "").trim().toLowerCase()) || [])[1];

function setField(path, value) {
  setPath(state, path, value);
  const el = app.querySelector(`[data-path="${path}"], [data-combo-path="${path}"]`);
  if (el) el.value = value;
}

// quiet = reopening a saved client: only load the area list, change nothing.
function pinLookup(base, immediate, quiet = false) {
  clearTimeout(pinTimers[base]);
  const status = app.querySelector(`[data-pin-status="${base}"]`);
  const pin = String(getPath(state, `${base}.pin_code`) || "").trim();
  const country = getPath(state, `${base}.country`) || "";
  const iso = isoFor(country) || "";
  const say = (msg, cls = "") => { if (status && !quiet) { status.textContent = msg; status.className = `hint pin-status ${cls}`; } };
  if (!pin) return say("");
  if (!iso) return say("Choose the country to look this code up automatically.");
  if (pinProblem(iso, pin)) return say("");   // the format message under the field says what's wrong
  if (iso !== "IN" && (!POSTCODE_COUNTRIES.has(iso) || pin.length < 3)) {
    return say(POSTCODE_COUNTRIES.has(iso) ? "" : `Automatic lookup isn't available for ${country} — enter the details below.`);
  }
  pinTimers[base] = setTimeout(async () => {
    say("Looking up…");
    try {
      const r = await api("GET", `/api/postcode/${iso}/${encodeURIComponent(pin)}`);
      if (tidyPostcode(iso, getPath(state, `${base}.pin_code`)) !== tidyPostcode(iso, pin)) return say("");   // typed on since
      if (!r.found) return say("PIN / postal code not found — please check it, or enter the details below.", "warn");
      if (quiet) { localities[base] = r.localities || []; return; }
      if (r.city) setField(`${base}.city`, r.city);
      if (r.state) setField(`${base}.state`, r.state);
      localities[base] = r.localities || [];
      if (localities[base].length === 1 && !getPath(state, `${base}.street`)) setField(`${base}.street`, localities[base][0]);
      if (base === "applicants.0.address" && !state.patent_office) {
        const office = suggestOffice(r.state);
        if (office) {
          setField("patent_office", office);
          const box = document.getElementById("office-suggest");
          if (box) box.innerHTML = "";
          recheckRelated("patent_office");
        }
      }
      const where = [r.city, r.state].filter(Boolean).join(", ");
      say(r.offline
        ? `Offline — filled the state only (${r.state}).`
        : `✓ ${where}${localities[base].length > 1 ? ` · ${localities[base].length} areas — choose yours under Area / Locality` : ""}`, "ok");
    } catch (err) {
      say(err.message || "Lookup failed — enter the details below.", "warn");
    }
  }, immediate || iso === "IN" ? 0 : 600);
}

function personBlock(listPath, i) {
  const base = `${listPath}.${i}`;
  const isApplicant = listPath === "applicants";
  const title = isApplicant ? "Applicant" : "Inventor";
  const canRemove = !isApplicant || state.applicants.length > 1;
  // Inventors are always natural persons; an applicant may be a company.
  const individual = !isApplicant || getPath(state, `${base}.kind`) !== "organisation";
  return `<div class="person">
    <div class="person-head"><h3>${title} ${i + 1}</h3>
      ${canRemove ? `<button type="button" class="btn link sm" data-action="remove" data-list="${listPath}" data-index="${i}">Remove</button>` : ""}</div>
    <div class="grid">
      ${isApplicant ? selectField(`${base}.kind`, "Applicant is", [["individual", "An individual"], ["organisation", "A company / organisation"]]) : ""}
      ${inputField(`${base}.name`, individual ? "Full name" : "Registered name", { wide: true, name: true,
        check: individual ? "personName" : "orgName",
        hint: individual ? "Family name first is preferred." : "As registered, e.g. Acme Innovations Pvt. Ltd." })}
      ${individual ? selectField(`${base}.gender`, "Gender", GENDERS) : ""}
      ${individual ? inputField(`${base}.age`, "Age (years)", { check: isApplicant ? "applicantAge" : "age", placeholder: "Optional" }) : ""}
      ${comboField(`${base}.nationality`, "Nationality", "country")}
      ${comboField(`${base}.country_of_residence`, "Country of residence", "country")}
    </div>
    ${addressBlock(`${base}.address`)}
    <div class="subtle-title">Contact</div>
    <div class="grid">
      ${inputField(`${base}.email`, "E-mail", { type: "email" })}
      ${phoneField(`${base}.mobile`, "Mobile")}
      ${isApplicant ? phoneField(`${base}.telephone`, "Telephone") : ""}
    </div>
  </div>`;
}

function projectBlock(p, pi) {
  const base = `projects.${pi}`;
  return `<div class="project">
    <div class="project-head">
      <h3>Project ${pi + 1}${p.name || p.invention_title ? ": " + esc(projectLabel(p)) : ""}</h3>
      <button type="button" class="btn link sm" data-action="remove" data-list="projects" data-index="${pi}">Remove project</button>
    </div>
    <div class="grid">
      ${inputField(`${base}.name`, "Project name / internal reference", { placeholder: "e.g. Smart irrigation – 2024", check: "projectName" })}
      ${inputField(`${base}.invention_title`, "Title of the invention", { type: "textarea", wide: true, check: "title" })}
      <div class="field wide"><span style="margin-bottom:6px">Type of application</span>
        <div class="checks">${APP_TYPES.map(([v, l]) => `<label><input type="checkbox" data-multi="${base}.application_type" value="${v}"${p.application_type.includes(v) ? " checked" : ""}> ${l}</label>`).join("")}</div></div>
      ${inputField(`${base}.application_number`, "Patent application no.", { check: "appno", hint: "12 digits: year + office code + serial" })}
      ${inputField(`${base}.filing_date`, "Date of filing", { type: "date", check: "filingDate" })}
      ${inputField(`${base}.patent_number`, "Patent no. (after grant)", { check: "patentno" })}
      ${inputField(`${base}.grant_date`, "Date of grant", { type: "date", check: "grantDate" })}
    </div>
    <div class="inventors-head">
      <div><span class="subtle-title" style="margin:0">Inventors of this invention</span>
        <span class="hint">Used in Form 1, Form 5, Form 8 and Form 8A.</span></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button type="button" class="btn sm" data-action="copy-inventors" data-project="${pi}">Same as applicants</button>
        <button type="button" class="btn sm" data-action="add" data-list="${base}.inventors">+ Add inventor</button></div>
    </div>
    ${p.inventors.length ? p.inventors.map((_, i) => personBlock(`${base}.inventors`, i)).join("") : '<div class="empty small" style="padding:10px">No inventors added.</div>'}
  </div>`;
}

// "Suggested: Chennai (from Karnataka)" under the patent-office picker.
function officeSuggestion() {
  const st = state.applicants[0]?.address?.state;
  const sugg = !state.patent_office && suggestOffice(st);
  return sugg ? `<div class="suggest">Suggested: <button type="button" class="btn link sm" data-action="use-office" data-office="${sugg}">${esc(OFFICES.find((o) => o[0] === sugg)[1])}</button> <span class="muted">(from ${esc(st)})</span></div>` : "";
}

function renderClientForm(isNew) {
  const s = state;
  app.innerHTML = `
    <div class="form-title">
      <div><h1>${isNew ? "Add new client" : "Edit client details"}</h1>
      <p class="muted" style="margin:0">Only the details that repeat across IPO forms. Anything specific to one form stays blank in the downloaded document for you to complete.</p></div>
    </div>
    ${pendingDraft ? `<div class="draft-banner" role="alert">
      <div><b>You have unsaved changes from ${esc(new Date(pendingDraft.at).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }))}.</b>
        <span class="muted">They were kept in this browser when the page closed before saving.</span></div>
      <div class="draft-actions">
        <button type="button" class="btn primary sm" data-action="restore-draft">Restore them</button>
        <button type="button" class="btn sm" data-action="discard-draft">Discard</button>
      </div></div>` : ""}
    <form id="client-form" novalidate>
    <section class="card">
      <div class="card-head"><div><h2><span class="step">1</span>Client type</h2></div></div>
      <div class="grid">
        ${selectField("client_type", "Client is", [["individual", "Individual"], ["organisation", "Company / Organisation"]])}
        ${selectField("applicant_category", "Category of applicant", [["", "— Select —"], ...CATEGORIES], { hint: "Used in Form 1, Form 28 and Form 18A." })}
      </div>
    </section>

    <section class="card">
      <div class="card-head"><div><h2><span class="step">2</span>Applicant(s)</h2>
        <p class="muted small">The person(s) or company applying for / owning the patent.</p></div>
        <button type="button" class="btn sm" data-action="add" data-list="applicants">+ Add applicant</button></div>
      ${s.applicants.map((_, i) => personBlock("applicants", i)).join("")}
    </section>

    <section class="card">
      <div class="card-head"><div><h2><span class="step">3</span>Projects / inventions</h2>
        <p class="muted small">One entry per invention. Each has its own title, application/patent numbers and inventors. You choose the project when you pick a form.</p></div>
        <button type="button" class="btn sm" data-action="add-project">+ Add project</button></div>
      ${s.projects.length ? s.projects.map(projectBlock).join("") : '<div class="empty small">No projects yet. Use <b>+ Add project</b>.</div>'}
    </section>

    <section class="card">
      <div class="card-head"><div><h2><span class="step">4</span>Patent agent</h2>
        <p class="muted small">Optional. Leave blank if the applicant files directly.</p></div></div>
      <div class="grid">
        ${inputField("agent.name", "Agent name", { name: true, check: "personName" })}
        ${inputField("agent.inpa_number", "IN/PA registration no.", { check: "inpa" })}
        ${phoneField("agent.mobile", "Mobile")}
        ${inputField("agent.email", "E-mail", { type: "email" })}
      </div>
      ${addressBlock("agent.address")}
    </section>

    <section class="card">
      <div class="card-head"><div><h2><span class="step">5</span>Address for service in India</h2>
        <p class="muted small">Where the Patent Office sends correspondence. Asked on most forms.</p></div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
          <button type="button" class="btn sm" data-action="service-from-applicant">Use applicant 1</button>
          <button type="button" class="btn sm" data-action="service-from-agent">Use agent</button></div></div>
      <div class="grid">
        ${inputField("service.name", "Name", { wide: true, name: true, check: "orgName" })}
      </div>
      ${addressBlock("service.address")}
      <div class="subtle-title">Contact</div>
      <div class="grid">
        ${phoneField("service.telephone", "Telephone")}
        ${phoneField("service.mobile", "Mobile")}
        ${phoneField("service.fax", "Fax")}
        ${inputField("service.email", "E-mail", { type: "email" })}
      </div>
    </section>

    <section class="card">
      <div class="card-head"><div><h2><span class="step">6</span>Signing &amp; filing</h2></div></div>
      <div class="grid">
        ${inputField("signatory.name", "Name of person signing", { name: true, check: "personName", hint: "Defaults to the agent if left blank." })}
        ${inputField("signatory.designation", "Designation", { placeholder: "e.g. Director / Patent Agent", check: "designation" })}
        <div>${selectField("patent_office", "Appropriate patent office", OFFICES, { hint: "Based on the applicant's address." })}
          <div id="office-suggest">${officeSuggestion()}</div></div>
        ${inputField("notes", "Notes (not printed on forms)", { type: "textarea", wide: true, check: "notes" })}
      </div>
    </section>
    </form>

    <div class="savebar"><div class="savebar-inner">
      ${isNew ? "" : '<button type="button" class="btn danger" data-action="delete">Delete client</button>'}
      <span id="save-status" class="save-status${dirty ? " unsaved" : ""}" aria-live="polite">${dirty ? "Unsaved changes" : ""}</span>
      <span class="spacer"></span>
      <button type="button" class="btn" data-action="cancel">Cancel</button>
      <button type="button" class="btn" data-action="save-stay" title="Save and keep editing (Ctrl+S)">Save</button>
      <button type="button" class="btn primary" data-action="save">Save &amp; close</button>
    </div></div>`;
}

async function pageClientForm(id) {
  let isNew = !id;   // becomes false after the first "Save" of a new client
  const seq = routeSeq;
  const loaded = isNew ? blankClient() : normalise(await api("GET", `/api/clients/${id}`));
  if (seq !== routeSeq) return;
  state = loaded;
  document.title = (isNew ? "Add client" : "Edit client") + " – IPO Form Filler";

  // An unsaved draft from an earlier visit (tab closed, crash...)? Offer it back,
  // unless the client has been saved since the draft was made.
  draftKey = DRAFT_PREFIX + (id || "new");
  const draft = storeGet(draftKey);
  const savedAt = Date.parse(loaded.updated_at || "") || 0;
  pendingDraft = draft && draft.state && draft.at > savedAt ? draft : null;
  if (draft && !pendingDraft) storeDel(draftKey);

  const reloadAreas = () => {
    // Area lists belong to the client being edited; reload them from saved PINs.
    for (const k of Object.keys(localities)) delete localities[k];
    app.querySelectorAll("[data-pin-for]").forEach((el) => {
      if (el.value.trim()) pinLookup(el.dataset.pinFor, true, true);
    });
  };
  renderClientForm(isNew);
  reloadAreas();

  const rerender = () => { const y = window.scrollY; renderClientForm(isNew); window.scrollTo(0, y); };

  app.oninput = app.onchange = (e) => {
    const t = e.target;
    if (t.closest("#client-form")) markDirty();
    if (t.dataset.path) {
      setPath(state, t.dataset.path, t.value);
      t.classList.remove("invalid");
      // Refresh just the suggestion - redrawing the page here would lose the
      // field the user is tabbing into.
      if (t.dataset.path === "applicants.0.address.state" || t.dataset.path === "patent_office") {
        const box = document.getElementById("office-suggest");
        if (box) box.innerHTML = officeSuggestion();
      }
      if (e.type === "change" && /^applicants\.\d+\.kind$/.test(t.dataset.path)) {
        // Companies have no gender or age; the name rule changes too.
        const p = getPath(state, t.dataset.path.replace(/\.kind$/, ""));
        if (t.value === "organisation") { p.gender = ""; p.age = ""; }
        rerender();
      }
      if (e.type === "change" && t.dataset.path === "client_type") {
        // A single applicant follows the client type; mixed lists are left alone.
        if (state.applicants.length === 1) {
          const p = state.applicants[0];
          p.kind = t.value;
          if (t.value === "organisation") { p.gender = ""; p.age = ""; }
        }
        rerender();
      }
    } else if (t.dataset.multi) {
      const set = new Set(getPath(state, t.dataset.multi) || []);
      t.checked ? set.add(t.value) : set.delete(t.value);
      setPath(state, t.dataset.multi, [...set]);
    }
  };

  app.onclick = async (e) => {
    const b = e.target.closest("[data-action]");
    if (!b) return;
    const act = b.dataset.action;
    if (!["cancel", "delete", "save", "save-stay", "restore-draft", "discard-draft"].includes(act)) markDirty();
    if (act === "add") {
      const kind = b.dataset.list === "applicants" && state.client_type === "organisation" ? "organisation" : "individual";
      getPath(state, b.dataset.list).push(blankPerson(kind)); rerender();
    }
    else if (act === "add-project") {
      state.projects.push(blankProject()); rerender();
      const cards = app.querySelectorAll(".project");
      cards[cards.length - 1]?.scrollIntoView({ block: "start", behavior: "smooth" });
    } else if (act === "remove") {
      const list = getPath(state, b.dataset.list);
      const item = list[+b.dataset.index];
      if (b.dataset.list === "projects" && (item.name || item.invention_title || item.application_number)
          && !confirm(`Remove project "${projectLabel(item)}"? It is deleted when you save.`)) return;
      list.splice(+b.dataset.index, 1); rerender();
    } else if (act === "copy-inventors") {
      const proj = state.projects[+b.dataset.project];
      // Adds individual applicants who aren't inventors yet; inventors already
      // entered (with their own details) are kept as they are.
      const have = new Set(proj.inventors.map((p) => p.name.trim().toLowerCase()).filter(Boolean));
      const individuals = state.applicants.filter((a) => a.name && a.kind !== "organisation");
      const toAdd = individuals.filter((a) => !have.has(a.name.trim().toLowerCase()))
        .map((a) => ({ ...JSON.parse(JSON.stringify(a)), kind: "individual" }));
      // Drop empty inventor rows the user hadn't filled in yet.
      proj.inventors = [...proj.inventors.filter((p) => p.name.trim()), ...toAdd];
      rerender();
      toast(toAdd.length ? `Added ${toAdd.length} applicant${toAdd.length > 1 ? "s" : ""} as inventor${toAdd.length > 1 ? "s" : ""}`
        : individuals.length ? "Those applicants are already inventors"
        : state.applicants.some((a) => a.name) ? "Only individual applicants can be inventors — none to add" : "Add an applicant name first",
        !toAdd.length && !individuals.length);
    } else if (act === "service-from-applicant") {
      const a = state.applicants[0];
      state.service = { ...state.service, name: a.name, address: { ...a.address },
        telephone: a.telephone, mobile: a.mobile, email: a.email };
      localities["service.address"] = localities["applicants.0.address"];
      rerender();
    } else if (act === "service-from-agent") {
      const ag = state.agent;
      state.service = { ...state.service, name: ag.name, address: { ...ag.address }, mobile: ag.mobile, email: ag.email };
      localities["service.address"] = localities["agent.address"];
      rerender();
      if (!ag.address.pin_code && !ag.address.street) toast("Agent copied — the agent has no address yet");
    } else if (act === "use-office") {
      setField("patent_office", b.dataset.office);
      document.getElementById("office-suggest").innerHTML = "";
      recheckRelated("patent_office"); markDirty();
    }
    else if (act === "cancel") { location.hash = returnTo || "#/"; }   // asks first if there are unsaved changes
    else if (act === "delete") {
      if (!confirm(`Delete ${clientName(state)}? This cannot be undone.`)) return;
      b.disabled = true;
      try {
        await api("DELETE", `/api/clients/${id}`);
      } catch (err) {
        b.disabled = false;
        toast(`Couldn't delete: ${err.message}`, true);
        return;
      }
      dirty = false;
      clearDraft();
      toast("Client deleted"); location.hash = "#/";
    } else if (act === "restore-draft" && pendingDraft) {
      state = normalise(pendingDraft.state);
      pendingDraft = null;
      rerender(); reloadAreas(); markDirty();
      toast("Unsaved changes restored — remember to save");
    } else if (act === "discard-draft") {
      pendingDraft = null; clearDraft(); rerender();
    } else if (act === "save" || act === "save-stay") {
      const stay = act === "save-stay";
      // Commit whatever field still has focus (name tidy-up, picker choice...).
      if (document.activeElement && app.contains(document.activeElement)) document.activeElement.blur();
      // Names are tidied and e-mails checked even if the field still has focus.
      app.querySelectorAll("[data-name]").forEach(fixName);
      const badEmails = [...app.querySelectorAll("[data-email]")].filter((el) => !checkEmail(el));
      const badPhones = [...app.querySelectorAll(".phone")].filter((box) => !checkPhone(box))
        .map((box) => box.querySelector("[data-phone-number]"));
      const badPins = [...app.querySelectorAll("[data-pin-for]")].filter((el) => !checkPin(el));
      const badOther = [...app.querySelectorAll("[data-check]")].filter((el) => !checkField(el));
      const bad = [...badEmails, ...badPhones, ...badPins, ...badOther]
        .sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
      if (bad.length) {
        bad[0].scrollIntoView({ block: "center" }); bad[0].focus();
        const parts = [badEmails.length && `${badEmails.length} e-mail${badEmails.length > 1 ? "s" : ""}`,
          badPhones.length && `${badPhones.length} phone number${badPhones.length > 1 ? "s" : ""}`,
          badPins.length && `${badPins.length} PIN / postal code${badPins.length > 1 ? "s" : ""}`,
          badOther.length && `${badOther.length} ${badOther.length < bad.length ? "other " : ""}field${badOther.length > 1 ? "s" : ""}`].filter(Boolean);
        const what = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0];
        toast(`Fix the ${what} marked in red (or clear ${bad.length > 1 ? "them" : "it"}) before saving`, true);
        return;
      }
      app.querySelectorAll('[data-action^="save"]').forEach((x) => (x.disabled = true));
      try {
        const saved = isNew ? await api("POST", "/api/clients", state) : await api("PUT", `/api/clients/${id}`, state);
        dirty = false;
        clearDraft();
        if (!stay) {
          toast(`Saved ${clientName(saved)}`);
          location.hash = returnTo || "#/";
          return;
        }
        // Save and stay: carry on editing the saved copy (with its new
        // version stamp, so the next save isn't mistaken for a conflict).
        state = normalise(saved);
        if (isNew) {
          isNew = false;
          id = saved.id;
          draftKey = DRAFT_PREFIX + id;
          history.replaceState(null, "", `#/client/${id}/edit${returnTo ? `?return=${encodeURIComponent(returnTo)}` : ""}`);
          currentHash = location.hash;
          document.title = "Edit client – IPO Form Filler";
        }
        rerender();
        const s = document.getElementById("save-status");
        if (s) { s.textContent = `Saved at ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`; s.className = "save-status saved"; }
        toast(`Saved ${clientName(saved)} — you can keep editing`);
      } catch (err) {
        toast(err.message, true);
        app.querySelectorAll('[data-action^="save"]').forEach((x) => (x.disabled = false));
      }
    }
  };
}

// ------------------------------------------------------------------ page: pick a form
async function pageFormPicker(id) {
  app.oninput = app.onchange = app.onclick = null;
  const seq = routeSeq;
  const [c, forms] = await Promise.all([api("GET", `/api/clients/${id}`), getForms()]);
  if (seq !== routeSeq) return;
  document.title = `${clientName(c)} – Select form`;
  const proj = pickProject(c, query.get("p"));
  noteMissingProject(c, proj);
  const pq = projectQuery(proj);

  app.innerHTML = `
    <section class="card client-banner">
      <div>
        <div class="muted small">Client</div>
        <div class="who">${esc(clientName(c))}</div>
        ${projectFacts(c, proj)}
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end">
        ${projectSelect(c, proj)}
        <a class="btn" href="#/client/${id}/edit?return=${encodeURIComponent(`#/client/${id}/forms${pq}`)}">Edit details</a>
        <a class="btn" href="#/">Change client</a>
      </div>
    </section>
    <div class="toolbar">
      <h2 style="margin:0">Select a form</h2>
      <input type="search" id="q" placeholder="Search by number or name, e.g. 18 or opposition" aria-label="Search forms">
      <span class="muted small" id="count">${forms.length} forms</span>
    </div>
    <div class="form-grid" id="forms">
      ${forms.map((f) => `
        <a class="form-card" href="#/client/${id}/form/${f.id}${pq}" data-no="${esc(f.number.toLowerCase())}" data-text="${esc((f.name + " " + f.purpose).toLowerCase())}">
          <span class="form-no"><small>FORM</small>${esc(f.number)}</span>
          <span><span class="fname">${esc(f.name)}</span><span class="fpurpose">${esc(f.purpose)}</span></span>
        </a>`).join("")}
    </div>`;

  const q = document.getElementById("q");
  q.addEventListener("input", () => {
    const term = q.value.toLowerCase().replace(/^form\s*/, "").trim();
    // "7" finds Form 7 and 7A; words search the name and purpose.
    const numeric = /^\d+[a-z]?$/.test(term);
    let n = 0;
    document.querySelectorAll(".form-card").forEach((el) => {
      const show = !term || (numeric
        ? el.dataset.no === term || (/^\d+$/.test(term) && /^\d+[a-z]$/.test(el.dataset.no) && el.dataset.no.slice(0, -1) === term)
        : el.dataset.text.includes(term));
      el.hidden = !show; n += show;
    });
    document.getElementById("count").textContent = `${n} form${n === 1 ? "" : "s"}`;
  });
  bindProjectSelect(`#/client/${id}/forms`);
  q.focus();
}

function projectFacts(c, proj) {
  const facts = [["Category", CATEGORY_LABEL[c.applicant_category]]];
  if (proj) {
    facts.push(["Invention", proj.invention_title], ["Application no.", proj.application_number],
      ["Filed", fmtDate(proj.filing_date)], ["Patent no.", proj.patent_number],
      ["Inventors", proj.inventors.length || ""]);
  }
  const shown = facts.filter(([, v]) => v);
  return shown.length ? `<dl>${shown.map(([k, v]) => `<div><dt>${k}:</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : "";
}

function bindProjectSelect(baseHash) {
  const sel = document.getElementById("project");
  if (sel) sel.addEventListener("change", () => (location.hash = `${baseHash}?p=${sel.value}`));
}

// ------------------------------------------------------------------ page: preview + download
function rowValue(r) {
  if (r.options) {
    const anySel = r.options.some((o) => o.selected);
    if (r.kind === "strikeoutChoice") {
      return r.options.map((o) => `<span class="${anySel && !o.selected ? "strike" : ""}${o.selected ? " opt-on" : ""}">${esc(o.label)}</span>`).join(" / ");
    }
    if (r.kind === "dropdown" && anySel) return esc(r.value);
    return r.options.map((o) => `<span class="opt${o.selected ? " on" : ""}">${o.selected ? "☒" : "☐"} ${esc(o.label)}</span>`).join("");
  }
  return esc(r.value);
}

function renderBlock(b) {
  if (b.type === "text") return `<p class="bp">${esc(b.text)}</p>`;
  if (b.type === "subheading") return `<div class="subh">${esc(b.text)}</div>`;
  if (b.type === "table") {
    return `<p class="bp"><i>${esc(b.label)}</i></p><table class="grid-table"><tr>${b.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>
      ${b.rows.map((r) => `<tr>${r.map((v) => `<td class="val blank" style="height:30px">${esc(v)}</td>`).join("")}</tr>`).join("")}</table>`;
  }
  if (b.type === "fields") {
    return `<table>${b.rows.map((r) => {
      const filled = r.prefilled || (r.options && r.options.some((o) => o.selected));
      const tall = !filled && (r.kind === "signature" || r.multiline);
      const cls = r.office ? "val" : `val ${filled ? "filled" : "blank"}${tall ? " tall" : ""}`;
      return `<tr${r._n !== undefined ? ` id="row-${r._n}"` : ""}><td class="lbl">${esc(r.label)}</td><td class="${cls}">${rowValue(r)}</td></tr>`;
    }).join("")}</table>`;
  }
  return "";
}

// The fields that count towards "pre-filled" / "left blank" - the same rule
// the server uses for its totals (inputs only; not office-use or signatures).
const COUNTED_KINDS = new Set(["text", "textarea", "date", "number", "dropdown", "radio",
  "checkbox", "checkboxGroup", "strikeoutChoice"]);

// Numbers each counted row (so the lists can jump to it) and splits them
// into filled / blank, labelled with their section and person.
function fieldInventory(m) {
  const filled = [], blank = [];
  let n = 0;
  for (const s of m.sections) {
    if (s.office) continue;
    const section = (s.title || "").replace(/\s*\[.*$/, "").replace(/^[\dA-Z]{1,3}[.)]\s*/, "");
    let person = "";
    for (const b of s.blocks) {
      if (b.type === "subheading") person = b.text;
      if (b.type !== "fields") continue;
      for (const r of b.rows) {
        if (r.office || !COUNTED_KINDS.has(r.kind)) continue;
        r._n = n++;
        const entry = { n: r._n, section, label: (person ? person + " · " : "") + r.label, value: r.value };
        (r.prefilled ? filled : blank).push(entry);
      }
    }
  }
  return { filled, blank };
}

function fieldPopup(title, entries, showValues) {
  if (!entries.length) return `<div class="pop" role="tooltip"><div class="pop-inner"><div class="pop-title">${esc(title)}</div><p class="pop-empty">None.</p></div></div>`;
  let lastSection = null;
  const items = entries.map((e) => {
    const head = e.section !== lastSection ? `<li class="pop-section">${esc(e.section || "General")}</li>` : "";
    lastSection = e.section;
    return `${head}<li><button type="button" data-jump="${e.n}"><span class="pl">${esc(e.label)}</span>${showValues ? `<span class="pv">${esc(e.value.replace(/\n/g, " · "))}</span>` : ""}</button></li>`;
  }).join("");
  return `<div class="pop" role="tooltip"><div class="pop-inner"><div class="pop-title">${esc(title)}</div><ul>${items}</ul></div></div>`;
}

async function pagePreview(id, formId) {
  app.oninput = app.onchange = app.onclick = null;
  const seq = routeSeq;
  const c = await api("GET", `/api/clients/${id}`);
  const proj = pickProject(c, query.get("p"));
  const pq = projectQuery(proj);
  const apiQ = proj ? `?project=${proj.id}` : "";
  const m = await api("GET", `/api/clients/${id}/forms/${formId}${apiQ}`);
  if (seq !== routeSeq) return;
  const f = m.form;
  noteMissingProject(c, proj);
  document.title = `Form ${f.number} – ${clientName(c)}`;
  const here = `#/client/${id}/form/${formId}${pq}`;
  const inv = fieldInventory(m);
  app.innerHTML = `
    <div class="preview-head">
      <div>
        <a href="#/client/${id}/forms${pq}" class="btn link sm" style="padding-left:0">← All forms for ${esc(clientName(c))}</a>
        <h1 style="margin-top:4px">Form ${esc(f.number)} — ${esc(f.name)}</h1>
        <div style="margin-top:8px">${projectSelect(c, proj)}</div>
        <div class="chips">
          <div class="chip-pop" tabindex="0" aria-label="Show the pre-filled fields">
            <span class="chip ok">${inv.filled.length} fields pre-filled</span>
            ${fieldPopup("Pre-filled from the client's details", inv.filled, true)}
          </div>
          <div class="chip-pop" tabindex="0" aria-label="Show the fields left blank">
            <span class="chip">${inv.blank.length} left blank to complete in Word</span>
            ${fieldPopup("Left blank — complete these in Word", inv.blank, false)}
          </div>
          <span class="chip legend"><i class="f"></i>pre-filled <i class="b" style="margin-left:8px"></i>blank</span>
        </div>
      </div>
      <div class="preview-actions">
        <a class="btn" href="#/client/${id}/edit?return=${encodeURIComponent(here)}">Edit client details</a>
      </div>
    </div>
    ${m.official_pdf ? `<div class="paper-top"><a class="btn sm" href="/official/${encodeURIComponent(m.official_pdf)}" target="_blank" rel="noopener">View official PDF ↗</a></div>` : ""}
    <article class="paper">
      <div class="doc-head">
        <div class="act">${esc(f.act)}<br>&amp;<br>${esc(f.rules)}</div>
        <div class="formno">FORM ${esc(f.number)}</div>
        <div class="fname">${esc(f.name)}</div>
        ${f.see ? `<div class="see">[See ${esc(f.see)}]</div>` : ""}
      </div>
      ${m.sections.map((s) => `<section class="${s.office ? "office" : ""}">
        ${s.title ? `<h4>${esc(s.title)}</h4>` : ""}${s.blocks.map(renderBlock).join("")}</section>`).join("")}
    </article>
    <div class="download-bar">
      <div>
        <div class="download-title">Download</div>
        <p class="muted small" style="margin:0">Pre-filled with ${esc(clientName(c))}'s details${proj ? ` for "${esc(projectLabel(proj))}"` : ""}, or an empty copy.</p>
      </div>
      <div class="download-actions">
        <a class="btn primary lg" href="/api/clients/${id}/forms/${formId}.docx${apiQ}" download>Download filled form (.docx)</a>
        <a class="btn" href="/api/forms/${formId}/blank.docx" download>Download blank form (.docx)</a>
        ${m.official_pdf ? `<a class="btn" href="/official/${encodeURIComponent(m.official_pdf)}?download=1" download>Download official PDF</a>` : ""}
      </div>
    </div>`;
  bindProjectSelect(`#/client/${id}/form/${formId}`);
  // Clicking a field in a pop-up scrolls to it on the form and flashes it.
  app.onclick = (e) => {
    const b = e.target.closest("[data-jump]");
    if (!b) return;
    const row = document.getElementById(`row-${b.dataset.jump}`);
    if (!row) return;
    document.activeElement?.blur();   // closes the pop-up
    row.scrollIntoView({ block: "center", behavior: "smooth" });
    row.classList.remove("flash"); void row.offsetWidth; row.classList.add("flash");
  };
}
