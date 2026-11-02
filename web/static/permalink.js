// A permalink is #/<year>/<view>[/<cell>][/<document kind>/<PDF page>], where the cell is
// <plan>/<column> on a sheet, <sheet>/<plan>/<column> on Ambiguities, and <sheet>/<column> on a plan's page.
// Links from before the year was added start at the view.
const SHEETS = ["main", "dvha"];
const VIEWS = [...SHEETS, "plan", "ambiguities"];

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
  const view = VIEWS.includes(parts[0]) ? parts.shift() : "main";
  const state = { year, view };
  if (view === "plan" && parts.length) state.plan = parts.shift();
  const sheet = SHEETS.includes(view) ? view : view === "ambiguities" || SHEETS.includes(parts[0]) ? parts.shift() : null;
  if (sheet) {
    if (view !== "plan") state.plan = parts.shift();
    Object.assign(state, { sheet, column: parts.shift() });
  }
  if (parts.length) Object.assign(state, { kind: parts.shift().toUpperCase(), page: Number(parts.shift()) || 1 });
  for (const k of Object.keys(state)) if (state[k] === undefined) delete state[k];
  if (SHEETS.includes(view) && !state.column) return { year, view };
  return state;
}

export function format({ year, view, plan, sheet, column, kind, page }) {
  const parts = [year, view];
  if (view === "plan") parts.push(plan);
  if (column) parts.push(...(view === "plan" ? [sheet, column] : view === "ambiguities" ? [sheet, plan, column] : [plan, column]));
  if (kind && (column || view === "plan")) parts.push(kind, page);
  return `#/${parts.map((p) => encodeURIComponent(p)).join("/")}`;
}
