// A permalink is #/<year>/<view>[/<cell>][/<document kind>/<PDF page>], where the cell is
// <plan>/<column> on a sheet, <sheet>/<plan>/<column> on Notes, and <sheet>/<column> on a plan's page.
// The pipeline view is #/<year>/how[/<sheet>/<plan>/<column>[/<step>]].
// Links from before the year was added start at the view.
const SHEETS = ["main", "dvha"];
const VIEWS = [...SHEETS, "plan", "notes", "how"];

const decode = (s) => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

export function parse(hash, liveYear) {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decode);
  const year = /^\d{4}$/.test(parts[0]) ? Number(parts.shift()) : liveYear;
  if (parts[0] === "ambiguities") parts[0] = "notes";
  const view = VIEWS.includes(parts[0]) ? parts.shift() : "main";
  const state = { year, view };
  if (view === "plan" && parts.length) state.plan = parts.shift();
  const cellFirst = view === "notes" || view === "how";
  const sheet = SHEETS.includes(view) ? view : cellFirst || SHEETS.includes(parts[0]) ? parts.shift() : null;
  if (sheet) {
    if (view !== "plan") state.plan = parts.shift();
    Object.assign(state, { sheet, column: parts.shift() });
  }
  if (view === "how" && parts.length) state.step = parts.shift();
  else if (parts.length) Object.assign(state, { kind: parts.shift().toUpperCase(), page: Number(parts.shift()) || 1 });
  for (const k of Object.keys(state)) if (state[k] === undefined) delete state[k];
  if (SHEETS.includes(view) && !state.column) return { year, view };
  return state;
}

export function format({ year, view, plan, sheet, column, kind, page, step }) {
  const parts = [year, view];
  if (view === "plan") parts.push(plan);
  if (column) parts.push(...(view === "plan" ? [sheet, column] : view === "notes" || view === "how" ? [sheet, plan, column] : [plan, column]));
  if (view === "how" && column && step) parts.push(step);
  if (kind && (column || view === "plan")) parts.push(kind, page);
  return `#/${parts.map((p) => encodeURIComponent(p)).join("/")}`;
}
