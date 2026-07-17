/**
 * Reads the `--l2-*` custom properties defined in `graph-theme.css` (light
 * values from `:root`, `.dark` overrides if a `.dark` ancestor class is ever
 * wired up — see that file's docstring) via `getComputedStyle`. Cytoscape's
 * canvas-rendered stylesheet can't resolve `var(...)` itself, so this is the
 * one place those tokens get turned into literal color strings usable as a
 * cytoscape `background-color`/`line-color`/etc. value.
 *
 * `FALLBACK` mirrors `:root`'s exact light-mode values — used verbatim
 * during SSR (no `document` there) and in a client render before paint,
 * so there's no flash-of-different-color between the fallback and the
 * real computed value (they're identical by construction).
 */
export interface GraphTheme {
  roleSource: string;
  roleMule: string;
  roleSink: string;
  roleNormal: string;
  roleUnknown: string;
  centerFill: string;
  centerStroke: string;
  edge: string;
  statusFlag: string;
  selection: string;
  label: string;
  // ROADMAP Phase 18 — Relationship Explorer's own tokens, see
  // `graph-theme.css`'s docstring for why these are additive, not a reuse
  // of `role*`/`center*` above.
  relInScope: string;
  relOutOfScope: string;
  relEdge: string;
}

const FALLBACK: GraphTheme = {
  roleSource: "#2a78d6",
  roleMule: "#e87ba4",
  roleSink: "#eda100",
  roleNormal: "#9ca3af",
  roleUnknown: "#9ca3af",
  centerFill: "oklch(0.205 0 0 / 10%)",
  centerStroke: "oklch(0.205 0 0)",
  edge: "#b8b8b8",
  statusFlag: "#dc2626",
  selection: "#7c3aed",
  label: "oklch(0.145 0 0)",
  relInScope: "#2a78d6",
  relOutOfScope: "#ea580c",
  relEdge: "#9ca3af",
};

export function readGraphTheme(): GraphTheme {
  if (typeof window === "undefined") return FALLBACK;
  const style = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    roleSource: read("--l2-role-source", FALLBACK.roleSource),
    roleMule: read("--l2-role-mule", FALLBACK.roleMule),
    roleSink: read("--l2-role-sink", FALLBACK.roleSink),
    roleNormal: read("--l2-role-normal", FALLBACK.roleNormal),
    roleUnknown: read("--l2-role-unknown", FALLBACK.roleUnknown),
    centerFill: read("--l2-center-fill", FALLBACK.centerFill),
    centerStroke: read("--l2-center-stroke", FALLBACK.centerStroke),
    edge: read("--l2-edge", FALLBACK.edge),
    statusFlag: read("--l2-status-flag", FALLBACK.statusFlag),
    selection: read("--l2-selection", FALLBACK.selection),
    label: read("--l2-label", FALLBACK.label),
    relInScope: read("--l2-rel-in-scope", FALLBACK.relInScope),
    relOutOfScope: read("--l2-rel-out-of-scope", FALLBACK.relOutOfScope),
    relEdge: read("--l2-rel-edge", FALLBACK.relEdge),
  };
}

/** `GraphNode.role` -> its fill color, per `graph-theme.css`'s docstring. */
export function roleColor(theme: GraphTheme, role: string): string {
  switch (role) {
    case "SOURCE":
      return theme.roleSource;
    case "MULE":
      return theme.roleMule;
    case "SINK":
      return theme.roleSink;
    case "NORMAL":
      return theme.roleNormal;
    default:
      return theme.roleUnknown;
  }
}

/** Plain-language label for a role, used in the legend and node-detail
 * panel — never rely on color alone to convey role (dataviz guidance,
 * ROADMAP Phase 17). */
export function roleLabel(role: string): string {
  switch (role) {
    case "SOURCE":
      return "Source";
    case "MULE":
      return "Mule";
    case "SINK":
      return "Sink";
    case "NORMAL":
      return "Normal";
    default:
      return "Unknown";
  }
}
