"use client";

/** Repository map — the product's centerpiece surface (docs/design/
 * repository-map.dc.html, ported 1:1 where it made sense).
 *
 * The map answers "what are this company's repositories and how do they relate":
 * typed nodes (frontend … infra) laid out by architectural layer, with directed
 * API-call and data-flow relations drawn between them. Synced git connections
 * (Admin → Settings) appear automatically as live nodes carrying their code-graph
 * stats; planned repositories and every relation are drawn by hand.
 *
 * UI-FIRST scope (deliberate): projects, hand-drawn repos, relations, positions
 * and type assignments persist in localStorage only. Server-side persistence —
 * and feeding the relation graph to the impact worker — is the next backend
 * decision (docs/ROADMAP.md S14). Nothing here invents estimation numbers.
 */

import type { CSSProperties, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api, type ConnectionEntry } from "@/lib/api";
import { CONNECTOR_LABELS, ConnectorMark, IconMap } from "@/components/icons";

/* ---------------- Domain tables (from the design file) ---------------- */

const TYPES = {
  fe: { label: "Frontend", layer: "client", hue: 300 },
  mobile: { label: "Mobile", layer: "client", hue: 330 },
  middleware: { label: "Middleware", layer: "middleware", hue: 270 },
  be: { label: "Backend", layer: "service", hue: 230 },
  db: { label: "Database schema", layer: "data", hue: 200 },
  lib: { label: "Shared library", layer: "platform", hue: 160 },
  infra: { label: "Infra / IaC", layer: "platform", hue: 130 },
} as const;
type RepoType = keyof typeof TYPES;

const LAYERS: [string, string][] = [
  ["client", "CLIENTS"],
  ["middleware", "MIDDLEWARE"],
  ["service", "SERVICES"],
  ["data", "DATA"],
];

const KIND = {
  api: { label: "API call / service consumption", color: "var(--acc)", dash: "0" },
  data: { label: "Data flow", color: "var(--flow)", dash: "7 6" },
} as const;
type EdgeKind = keyof typeof KIND;

const GIT_KINDS = new Set(["git", "github", "gitlab", "bitbucket"]);
const PROVIDERS = ["github", "gitlab", "bitbucket", "git"];

const W = 214;
const H = 76;

/* ---------------- Persisted state ---------------- */

interface MapProject {
  id: string;
  name: string;
  key: string;
}
interface ManualRepo {
  id: string;
  project: string;
  name: string;
  provider: string;
  type: RepoType;
}
interface MapEdge {
  id: string;
  from: string;
  to: string;
  kind: EdgeKind;
}
interface ConnMeta {
  project: string | null; // null = visible in every project
  type: RepoType;
}
interface MapState {
  projects: MapProject[];
  repos: ManualRepo[];
  edges: MapEdge[];
  custom: Record<string, { x: number; y: number }>;
  connMeta: Record<string, ConnMeta>;
  projectId: string;
  seq: number;
}

const STORAGE_KEY = "estimo-map-v1";

const INITIAL: MapState = {
  projects: [{ id: "p-core", name: "Core Platform", key: "CORE" }],
  repos: [],
  edges: [],
  custom: {},
  connMeta: {},
  projectId: "p-core",
  seq: 1,
};

function loadState(): MapState {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return INITIAL;
    const parsed = JSON.parse(raw) as MapState;
    if (!parsed.projects?.length) return INITIAL;
    return { ...INITIAL, ...parsed };
  } catch {
    return INITIAL;
  }
}

/** A synthetic starter set (from the design file) so an empty deployment can see
 * what the map is FOR. Names are generic — sample data, clearly user-deletable. */
const SAMPLE: { name: string; provider: string; type: RepoType }[] = [
  { name: "web-portal-ui", provider: "github", type: "fe" },
  { name: "mobile-customer-app", provider: "github", type: "mobile" },
  { name: "integration-gateway", provider: "bitbucket", type: "middleware" },
  { name: "payments-service", provider: "github", type: "be" },
  { name: "identity-service", provider: "gitlab", type: "be" },
  { name: "core-db-schema", provider: "bitbucket", type: "db" },
  { name: "shared-dto-lib", provider: "github", type: "lib" },
  { name: "platform-iac", provider: "gitlab", type: "infra" },
];
const SAMPLE_EDGES: [number, number, EdgeKind][] = [
  [0, 2, "api"],
  [1, 2, "api"],
  [2, 3, "api"],
  [2, 4, "api"],
  [3, 5, "data"],
  [4, 5, "data"],
  [6, 3, "api"],
  [7, 2, "data"],
];

/* ---------------- Small style helpers ---------------- */

const mono = (size: number, tracking = 0): CSSProperties => ({
  fontFamily: "var(--font-mono)",
  fontSize: size,
  letterSpacing: tracking ? `${tracking}em` : undefined,
});

function typeDot(type: RepoType): CSSProperties {
  const color = `oklch(0.74 0.13 ${TYPES[type].hue})`;
  return {
    width: 7,
    height: 7,
    borderRadius: "50%",
    display: "block",
    flex: "0 0 7px",
    background: color,
    boxShadow: `0 0 9px ${color}`,
  };
}

function typeChip(type: RepoType): CSSProperties {
  const hue = TYPES[type].hue;
  return {
    padding: "4px 10px",
    borderRadius: 20,
    fontSize: 10.5,
    letterSpacing: "0.04em",
    color: `oklch(0.84 0.10 ${hue})`,
    border: `1px solid oklch(0.42 0.08 ${hue})`,
    background: `oklch(0.26 0.05 ${hue})`,
  };
}

const sectionLabel: CSSProperties = {
  ...mono(10, 0.14),
  color: "var(--mut)",
  textTransform: "uppercase" as const,
};

interface RepoView {
  id: string;
  name: string;
  provider: string;
  type: RepoType;
  connection?: ConnectionEntry;
}

/* ---------------- Page ---------------- */

export default function MapPage() {
  const [state, setState] = useState<MapState>(INITIAL);
  const [hydrated, setHydrated] = useState(false);
  const [connections, setConnections] = useState<ConnectionEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [linkKind, setLinkKind] = useState<EdgeKind | null>(null);
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [showAddProject, setShowAddProject] = useState(false);
  const [projectDraft, setProjectDraft] = useState("");
  const [draft, setDraft] = useState({ name: "", provider: "github", type: "be" as RepoType });

  useEffect(() => {
    setState(loadState());
    setHydrated(true);
    api.listConnections().then(setConnections).catch(() => setConnections([]));
  }, []);

  useEffect(() => {
    if (hydrated) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state, hydrated]);

  const project = state.projects.find((p) => p.id === state.projectId) ?? state.projects[0];

  /* ---- The visible node set: manual repos of this project + git connections. ---- */
  const repos: RepoView[] = useMemo(() => {
    const manual = state.repos
      .filter((r) => r.project === project?.id)
      .map((r) => ({ id: r.id, name: r.name, provider: r.provider, type: r.type }));
    const synced = connections
      .filter((c) => GIT_KINDS.has(c.kind))
      .filter((c) => {
        const assigned = state.connMeta[c.id]?.project ?? null;
        return assigned === null || assigned === project?.id;
      })
      .map((c) => ({
        id: `conn-${c.id}`,
        name: c.name,
        provider: c.kind,
        type: state.connMeta[c.id]?.type ?? "be",
        connection: c,
      }));
    return [...synced, ...manual];
  }, [state.repos, state.connMeta, connections, project?.id]);

  const byId = useMemo(() => {
    const map: Record<string, RepoView> = {};
    for (const repo of repos) map[repo.id] = repo;
    return map;
  }, [repos]);

  const edges = useMemo(
    () => state.edges.filter((e) => byId[e.from] && byId[e.to]),
    [state.edges, byId],
  );

  /* ---- Layout: layer columns, platform row, custom drags on top. ---- */
  const layout = useMemo(() => {
    const pos: Record<string, { x: number; y: number }> = {};
    const columns: { label: string; x: number; y: number; wide?: boolean }[] = [];
    const colX: Record<string, number> = { client: 60, middleware: 402, service: 744, data: 1086 };
    const groups: Record<string, RepoView[]> = {};
    for (const repo of repos) (groups[TYPES[repo.type].layer] ??= []).push(repo);
    let maxY = 0;
    for (const [key, label] of LAYERS) {
      const items = groups[key] ?? [];
      const step = 108;
      const startY = Math.max(110, 340 - ((items.length - 1) * step) / 2);
      items.forEach((repo, index) => {
        pos[repo.id] = { x: colX[key], y: startY + index * step };
        maxY = Math.max(maxY, startY + index * step);
      });
      columns.push({ label, x: colX[key], y: 44 });
    }
    const platform = groups.platform ?? [];
    const platY = maxY + 168;
    platform.forEach((repo, index) => {
      pos[repo.id] = { x: 60 + index * (W + 52), y: platY };
    });
    if (platform.length) columns.push({ label: "PLATFORM", x: 60, y: platY - 42, wide: true });
    let width = Math.max(colX.data + W + 70, 60 + platform.length * (W + 52));
    let height = platY + H + 90;
    for (const repo of repos) {
      const custom = state.custom[repo.id];
      if (custom) pos[repo.id] = custom;
      const p = pos[repo.id];
      if (p) {
        width = Math.max(width, p.x + W + 70);
        height = Math.max(height, p.y + H + 70);
      }
    }
    return { pos, columns, width, height };
  }, [repos, state.custom]);

  const posRef = useRef(layout.pos);
  posRef.current = layout.pos;

  /* ---- Dragging ---- */
  const dragRef = useRef<{
    id: string;
    sx: number;
    sy: number;
    ox: number;
    oy: number;
    moved: number;
  } | null>(null);

  const select = useCallback(
    (id: string) => {
      if (linkKind) {
        if (!linkFrom) {
          setLinkFrom(id);
          return;
        }
        if (linkFrom === id) {
          setLinkFrom(null);
          return;
        }
        const kind = linkKind;
        const from = linkFrom;
        setState((s) => {
          const exists = s.edges.some((e) => e.from === from && e.to === id && e.kind === kind);
          return exists
            ? s
            : {
                ...s,
                edges: [...s.edges, { id: `e${s.seq}`, from, to: id, kind }],
                seq: s.seq + 1,
              };
        });
        setLinkKind(null);
        setLinkFrom(null);
        setSelectedEdgeId(null);
        setSelectedId(id);
        return;
      }
      setSelectedEdgeId(null);
      setSelectedId((current) => (current === id ? null : id));
    },
    [linkKind, linkFrom],
  );

  const onDragMove = useCallback((event: MouseEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    const dx = event.clientX - drag.sx;
    const dy = event.clientY - drag.sy;
    drag.moved = Math.max(drag.moved, Math.abs(dx) + Math.abs(dy));
    if (drag.moved < 4) return;
    const next = { x: Math.max(8, drag.ox + dx), y: Math.max(8, drag.oy + dy) };
    setState((s) => ({ ...s, custom: { ...s.custom, [drag.id]: next } }));
  }, []);

  const onDragEnd = useCallback(() => {
    const drag = dragRef.current;
    window.removeEventListener("mousemove", onDragMove);
    window.removeEventListener("mouseup", onDragEnd);
    dragRef.current = null;
    setDragging(null);
    if (drag && drag.moved < 4) select(drag.id);
  }, [onDragMove, select]);

  const onNodeDown = (id: string) => (event: React.MouseEvent) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const start = posRef.current[id] ?? { x: 0, y: 0 };
    dragRef.current = {
      id,
      sx: event.clientX,
      sy: event.clientY,
      ox: start.x,
      oy: start.y,
      moved: 0,
    };
    window.addEventListener("mousemove", onDragMove);
    window.addEventListener("mouseup", onDragEnd);
    setDragging(id);
  };

  useEffect(
    () => () => {
      window.removeEventListener("mousemove", onDragMove);
      window.removeEventListener("mouseup", onDragEnd);
    },
    [onDragMove, onDragEnd],
  );

  /* ---- Derived selection ---- */
  const selected = selectedId ? byId[selectedId] : null;
  const selectedEdge = edges.find((e) => e.id === selectedEdgeId) ?? null;
  const related = useMemo(() => {
    const set = new Set<string>();
    if (selectedId) {
      set.add(selectedId);
      for (const e of edges) {
        if (e.from === selectedId) set.add(e.to);
        if (e.to === selectedId) set.add(e.from);
      }
    }
    return set;
  }, [selectedId, edges]);

  const outgoing = selected ? edges.filter((e) => e.from === selected.id) : [];
  const incoming = selected ? edges.filter((e) => e.to === selected.id) : [];

  function pathFor(s: { x: number; y: number }, t: { x: number; y: number }): string {
    let sx = s.x + W;
    const sy = s.y + H / 2;
    let tx = t.x;
    const ty = t.y + H / 2;
    if (t.x + W / 2 < s.x + W / 2) {
      sx = s.x;
      tx = t.x + W;
    }
    const dir = tx >= sx ? 1 : -1;
    const c = Math.max(56, Math.abs(tx - sx) * 0.45);
    return `M${sx},${sy} C${sx + c * dir},${sy} ${tx - c * dir},${ty} ${tx},${ty}`;
  }

  /* ---- Mutations ---- */
  const openProject = (id: string) => {
    setState((s) => ({ ...s, projectId: id }));
    setSelectedId(null);
    setSelectedEdgeId(null);
    setLinkKind(null);
    setLinkFrom(null);
    setShowAdd(false);
  };

  const addProject = () => {
    const name = projectDraft.trim();
    if (!name) return;
    setState((s) => {
      const id = `p${s.seq}`;
      const key =
        name
          .replace(/[^a-zA-Z ]/g, "")
          .split(" ")
          .filter(Boolean)
          .map((word) => word[0])
          .join("")
          .slice(0, 4)
          .toUpperCase() || "PRJ";
      return {
        ...s,
        projects: [...s.projects, { id, name, key }],
        projectId: id,
        seq: s.seq + 1,
      };
    });
    setShowAddProject(false);
    setProjectDraft("");
    setSelectedId(null);
    setSelectedEdgeId(null);
  };

  const addRepo = () => {
    const name = draft.name.trim();
    if (!name || !project) return;
    setState((s) => {
      const id = `r${s.seq}`;
      return {
        ...s,
        repos: [
          ...s.repos,
          { id, project: project.id, name, provider: draft.provider, type: draft.type },
        ],
        seq: s.seq + 1,
      };
    });
    setDraft({ ...draft, name: "" });
    setShowAdd(false);
  };

  const loadSample = () => {
    if (!project) return;
    setState((s) => {
      const repoIds = SAMPLE.map((_, index) => `r${s.seq + index}`);
      const sampleRepos = SAMPLE.map((sample, index) => ({
        id: repoIds[index],
        project: project.id,
        ...sample,
      }));
      const sampleEdges = SAMPLE_EDGES.map(([from, to, kind], index) => ({
        id: `e${s.seq + SAMPLE.length + index}`,
        from: repoIds[from],
        to: repoIds[to],
        kind,
      }));
      return {
        ...s,
        repos: [...s.repos, ...sampleRepos],
        edges: [...s.edges, ...sampleEdges],
        seq: s.seq + SAMPLE.length + SAMPLE_EDGES.length,
      };
    });
  };

  const deleteEdge = (id: string) =>
    setState((s) => ({ ...s, edges: s.edges.filter((e) => e.id !== id) }));

  const deleteNode = (id: string) => {
    setState((s) => ({
      ...s,
      repos: s.repos.filter((r) => r.id !== id),
      edges: s.edges.filter((e) => e.from !== id && e.to !== id),
    }));
    setSelectedId(null);
  };

  const setNodeType = (repo: RepoView, type: RepoType) => {
    if (repo.connection) {
      const connId = repo.connection.id;
      setState((s) => ({
        ...s,
        connMeta: {
          ...s.connMeta,
          [connId]: { project: s.connMeta[connId]?.project ?? null, type },
        },
      }));
    } else {
      setState((s) => ({
        ...s,
        repos: s.repos.map((r) => (r.id === repo.id ? { ...r, type } : r)),
      }));
    }
  };

  const assignConnProject = (repo: RepoView, projectId: string | null) => {
    if (!repo.connection) return;
    const connId = repo.connection.id;
    setState((s) => ({
      ...s,
      connMeta: {
        ...s.connMeta,
        [connId]: { project: projectId, type: s.connMeta[connId]?.type ?? "be" },
      },
    }));
  };

  const autoLayout = () =>
    setState((s) => {
      const custom = { ...s.custom };
      for (const repo of repos) delete custom[repo.id];
      return { ...s, custom };
    });

  if (!hydrated) {
    return (
      <section className="scr">
        <div className="page-h">
          <IconMap size={18} />
          <h2>Repository map</h2>
        </div>
      </section>
    );
  }

  const emptyProject = repos.length === 0;
  const graphStats = (c: ConnectionEntry) =>
    (c.last_run?.stats?.graph ?? null) as { files?: number; modules?: number; symbols?: number } | null;

  /* ---------------- Render ---------------- */
  return (
    <section
      className="scr"
      style={{
        display: "flex",
        flexDirection: "column",
        // Fill the shell's main area: the map owns its own scrolling regions.
        height: "calc(100vh - 36px)",
        margin: "-18px -22px -60px",
      }}
    >
      {/* ---- Top bar: crumb + link tools + counts ---- */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          minHeight: 62,
          flex: "0 0 auto",
          flexWrap: "wrap",
          padding: "9px 20px",
          borderBottom: "1px solid var(--line)",
          background: "linear-gradient(180deg, oklch(0.2 0.018 295), oklch(0.175 0.014 295))",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 9, whiteSpace: "nowrap" }}>
          <IconMap size={16} style={{ color: "var(--acc)" }} />
          <span style={{ ...mono(11), color: "var(--mut)" }}>Repository map</span>
          <span style={{ color: "oklch(0.42 0.03 300)", fontSize: 12 }}>/</span>
          <span style={{ fontSize: 13.5, fontWeight: 700, letterSpacing: "-0.01em" }}>
            {project?.name ?? "No project"}
          </span>
        </div>

        <div style={{ display: "flex", gap: 9, alignItems: "center", flexWrap: "wrap" }}>
          {linkKind === "api" ? (
            <button
              type="button"
              className="btn"
              style={{
                borderColor: "oklch(0.66 0.16 300)",
                background: "oklch(0.30 0.08 300)",
                color: "oklch(0.94 0.04 300)",
                boxShadow: "0 0 22px -6px oklch(0.66 0.18 300)",
              }}
              onClick={() => {
                setLinkKind(null);
                setLinkFrom(null);
              }}
            >
              <span
                style={{
                  width: 15,
                  height: 2,
                  borderRadius: 2,
                  background: "oklch(0.85 0.14 300)",
                  display: "block",
                  animation: "om-pulse 1.2s ease-in-out infinite",
                }}
              />
              Linking… cancel
            </button>
          ) : (
            <button
              type="button"
              className="btn glow"
              onClick={() => {
                setLinkKind("api");
                setLinkFrom(null);
              }}
            >
              <span
                style={{
                  width: 15,
                  height: 2,
                  borderRadius: 2,
                  background: "var(--acc)",
                  display: "block",
                }}
              />
              Link API call
            </button>
          )}
          {linkKind === "data" ? (
            <button
              type="button"
              className="btn"
              style={{
                borderColor: "oklch(0.66 0.13 200)",
                background: "oklch(0.30 0.06 200)",
                color: "oklch(0.94 0.04 200)",
                boxShadow: "0 0 22px -6px oklch(0.66 0.14 200)",
              }}
              onClick={() => {
                setLinkKind(null);
                setLinkFrom(null);
              }}
            >
              <span
                style={{
                  width: 15,
                  height: 0,
                  borderTop: "2px dashed oklch(0.86 0.12 200)",
                  display: "block",
                  animation: "om-pulse 1.2s ease-in-out infinite",
                }}
              />
              Linking… cancel
            </button>
          ) : (
            <button
              type="button"
              className="btn"
              onClick={() => {
                setLinkKind("data");
                setLinkFrom(null);
              }}
            >
              <span
                style={{
                  width: 15,
                  height: 0,
                  borderTop: "2px dashed var(--flow)",
                  display: "block",
                }}
              />
              Link data flow
            </button>
          )}
          <button type="button" className="btn" onClick={() => setShowAdd(!showAdd)}>
            + Repository
          </button>
          <button type="button" className="btn" onClick={autoLayout}>
            Auto layout
          </button>
        </div>

        <div style={{ flex: "1 0 0" }} />
        <div style={{ ...mono(11), color: "var(--mut)", whiteSpace: "nowrap" }}>
          {repos.length} repositories · {edges.length} relations
        </div>
      </div>

      {linkKind && (
        <div
          style={{
            flex: "0 0 34px",
            display: "flex",
            alignItems: "center",
            padding: "0 20px",
            background: "oklch(0.23 0.04 300)",
            borderBottom: "1px solid oklch(0.32 0.05 300)",
            ...mono(11),
            color: "oklch(0.84 0.05 300)",
          }}
        >
          {linkFrom && byId[linkFrom]
            ? `Source: ${byId[linkFrom].name} — now click the target repository.`
            : "Click the source repository, then the target."}
        </div>
      )}

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* ---- Projects column ---- */}
        <div
          style={{
            flex: "0 0 218px",
            borderRight: "1px solid var(--line)",
            background: "linear-gradient(180deg, oklch(0.19 0.016 295), oklch(0.17 0.012 295))",
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "16px 14px 8px",
            }}
          >
            <span style={{ ...mono(9.5, 0.18), color: "var(--mut)" }}>PROJECTS</span>
            <button
              type="button"
              className="btn"
              style={{ padding: "3px 7px", fontSize: 11, lineHeight: 1 }}
              onClick={() => setShowAddProject(!showAddProject)}
            >
              +
            </button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, padding: "0 10px 14px" }}>
            {showAddProject && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                  padding: 11,
                  border: "1px solid oklch(0.32 0.04 300)",
                  borderRadius: 10,
                  background: "oklch(0.20 0.02 300)",
                  marginBottom: 4,
                }}
              >
                <input
                  value={projectDraft}
                  onChange={(event) => setProjectDraft(event.target.value)}
                  onKeyDown={(event) => event.key === "Enter" && addProject()}
                  placeholder="Project name"
                  style={{ fontSize: 11 }}
                />
                <div style={{ display: "flex", gap: 6 }}>
                  <button
                    type="button"
                    className="btn p"
                    style={{ flex: 1, justifyContent: "center" }}
                    onClick={addProject}
                  >
                    Create
                  </button>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setShowAddProject(false)}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
            {state.projects.map((p) => {
              const isActive = p.id === project?.id;
              const repoCount =
                state.repos.filter((r) => r.project === p.id).length +
                connections.filter(
                  (c) =>
                    GIT_KINDS.has(c.kind) &&
                    ((state.connMeta[c.id]?.project ?? null) === null ||
                      state.connMeta[c.id]?.project === p.id),
                ).length;
              return (
                <div
                  key={p.id}
                  onClick={() => openProject(p.id)}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 5,
                    padding: "10px 11px",
                    borderRadius: 10,
                    cursor: "pointer",
                    border: `1px solid ${isActive ? "oklch(0.36 0.06 300)" : "var(--line)"}`,
                    background: isActive ? "oklch(0.225 0.025 300)" : "oklch(0.185 0.014 295)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        flex: "0 0 8px",
                        borderRadius: 3,
                        display: "block",
                        background: isActive ? "var(--acc)" : "oklch(0.36 0.03 300)",
                        boxShadow: isActive ? "0 0 10px var(--acc)" : "none",
                      }}
                    />
                    <span
                      style={{
                        flex: 1,
                        fontSize: 12,
                        fontWeight: 500,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {p.name}
                    </span>
                  </div>
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 8, paddingLeft: 16 }}
                  >
                    <span style={{ ...mono(9.5, 0.08), color: "var(--mut)" }}>{p.key}</span>
                    <span style={{ flex: 1 }} />
                    <span style={{ ...mono(9.5), color: "var(--mut)" }}>{repoCount} repos</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ---- Canvas ---- */}
        <div
          style={{
            flex: 1,
            overflow: "auto",
            position: "relative",
            background:
              "radial-gradient(120% 90% at 30% 0%, oklch(0.22 0.035 300) 0%, oklch(0.155 0.012 295) 62%)",
          }}
        >
          <div
            style={{
              position: "relative",
              width: layout.width,
              height: layout.height,
              minWidth: "100%",
            }}
          >
            <div className="canvas-grid" style={{ position: "absolute", inset: 0 }} />

            {layout.columns.map((column) => (
              <div
                key={column.label}
                style={{
                  position: "absolute",
                  left: column.x,
                  top: column.y,
                  width: column.wide ? 400 : W,
                  ...mono(10, 0.2),
                  color: "oklch(0.56 0.05 300)",
                }}
              >
                <span
                  style={{
                    display: "block",
                    width: 22,
                    height: 1,
                    background: "oklch(0.42 0.06 300)",
                    marginBottom: 9,
                  }}
                />
                {column.label}
              </div>
            ))}

            <svg
              width={layout.width}
              height={layout.height}
              style={{ position: "absolute", left: 0, top: 0, overflow: "visible", pointerEvents: "none" }}
            >
              <defs>
                <marker
                  id="arrowApi"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="6.5"
                  markerHeight="6.5"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="oklch(0.74 0.16 300)" />
                </marker>
                <marker
                  id="arrowData"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="6.5"
                  markerHeight="6.5"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="oklch(0.76 0.13 200)" />
                </marker>
                <filter id="edgeGlow" x="-30%" y="-30%" width="160%" height="160%">
                  <feGaussianBlur stdDeviation="3.2" result="b" />
                  <feMerge>
                    <feMergeNode in="b" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              {edges.map((edge) => {
                const from = layout.pos[edge.from];
                const to = layout.pos[edge.to];
                if (!from || !to) return null;
                const kind = KIND[edge.kind];
                const hot =
                  !!selectedId && (edge.from === selectedId || edge.to === selectedId);
                const on = !selectedId || hot;
                const isSel = edge.id === selectedEdgeId;
                return (
                  <path
                    key={edge.id}
                    d={pathFor(from, to)}
                    fill="none"
                    stroke={kind.color}
                    strokeWidth={isSel ? 3 : hot ? 2.6 : 1.6}
                    strokeLinecap="round"
                    strokeDasharray={kind.dash}
                    opacity={on ? (selectedId ? 1 : 0.62) : 0.07}
                    markerEnd={edge.kind === "api" ? "url(#arrowApi)" : "url(#arrowData)"}
                    filter={hot || isSel ? "url(#edgeGlow)" : undefined}
                    onClick={() => {
                      setSelectedEdgeId(edge.id);
                      setSelectedId(null);
                    }}
                    style={{
                      pointerEvents: "stroke",
                      cursor: "pointer",
                      // Data-flow dashes stream while the relation is hot.
                      animation:
                        edge.kind === "data" && (hot || isSel)
                          ? "om-flow 1.1s linear infinite"
                          : undefined,
                    }}
                  />
                );
              })}
            </svg>

            {repos.map((repo) => {
              const p = layout.pos[repo.id] ?? { x: 0, y: 0 };
              const on = !selectedId || related.has(repo.id);
              const isSel = repo.id === selectedId;
              const isFrom = repo.id === linkFrom;
              const isDrag = repo.id === dragging;
              const degree = edges.filter(
                (e) => e.from === repo.id || e.to === repo.id,
              ).length;
              const ring = isFrom
                ? "oklch(0.82 0.16 300)"
                : isSel
                  ? "oklch(0.70 0.16 300)"
                  : "transparent";
              return (
                <div
                  key={repo.id}
                  onMouseDown={onNodeDown(repo.id)}
                  style={{
                    position: "absolute",
                    left: p.x,
                    top: p.y,
                    width: W,
                    height: H,
                    cursor: isDrag ? "grabbing" : "grab",
                    userSelect: "none",
                    transition: isDrag
                      ? "none"
                      : "opacity .2s, box-shadow .2s, left .18s, top .18s",
                    opacity: on ? 1 : 0.22,
                    borderRadius: 12,
                    outline: `1.5px solid ${ring}`,
                    outlineOffset: 3,
                    boxShadow: isDrag
                      ? "0 22px 44px -14px rgba(0,0,0,0.9), 0 0 44px -8px oklch(0.70 0.18 300)"
                      : isSel || isFrom
                        ? "0 0 40px -8px oklch(0.70 0.18 300)"
                        : "none",
                    zIndex: isDrag ? 5 : isSel ? 3 : 2,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "center",
                      gap: 8,
                      height: "100%",
                      padding: "12px 14px",
                      borderRadius: 11,
                      background:
                        "linear-gradient(180deg, oklch(0.245 0.018 295), oklch(0.205 0.014 295))",
                      border: "1px solid var(--line2)",
                      boxShadow:
                        "0 10px 26px -12px rgba(0,0,0,0.85), inset 0 1px 0 oklch(0.34 0.02 295)",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                      <ConnectorMark kind={repo.provider} size={24} />
                      <span
                        style={{
                          ...mono(12.5),
                          fontWeight: 500,
                          color: "var(--ink)",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {repo.name}
                      </span>
                      {repo.connection && (
                        <span
                          title="Synced connection"
                          style={{
                            width: 6,
                            height: 6,
                            flex: "0 0 6px",
                            borderRadius: "50%",
                            background: "var(--ok)",
                            boxShadow: "0 0 8px var(--ok)",
                            animation: "om-pulse 2.4s ease-in-out infinite",
                          }}
                        />
                      )}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                      <span style={typeDot(repo.type)} />
                      <span
                        style={{
                          fontSize: 10,
                          letterSpacing: "0.07em",
                          color: "var(--mut)",
                          textTransform: "uppercase",
                        }}
                      >
                        {TYPES[repo.type].label}
                      </span>
                      <span style={{ flex: 1 }} />
                      <span style={{ ...mono(9.5), color: "oklch(0.48 0.02 295)" }}>
                        {degree ? `×${degree}` : "—"}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}

            {emptyProject && (
              <div
                style={{
                  position: "absolute",
                  left: 60,
                  top: 120,
                  maxWidth: 440,
                  padding: 20,
                  border: "1px dashed oklch(0.32 0.03 300)",
                  borderRadius: 12,
                  background: "oklch(0.19 0.02 300)",
                  fontSize: 12.5,
                  lineHeight: 1.65,
                  color: "var(--ink2)",
                }}
              >
                This project has no repositories yet. Use{" "}
                <span style={{ color: "oklch(0.82 0.13 300)" }}>+ Repository</span> to add the
                first one, connect a real one in{" "}
                <Link href="/admin">Settings</Link>, or{" "}
                <button
                  type="button"
                  onClick={loadSample}
                  style={{
                    border: 0,
                    padding: 0,
                    background: "none",
                    color: "var(--flow)",
                    cursor: "pointer",
                    font: "inherit",
                  }}
                >
                  load a sample map
                </button>{" "}
                to see the idea.
              </div>
            )}
          </div>
        </div>

        {/* ---- Inspector ---- */}
        <div
          style={{
            flex: "0 0 336px",
            borderLeft: "1px solid var(--line)",
            background: "linear-gradient(180deg, oklch(0.195 0.016 295), oklch(0.175 0.012 295))",
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
          }}
        >
          {showAdd && (
            <div
              style={{
                padding: "18px 20px 20px",
                borderBottom: "1px solid var(--line)",
                display: "flex",
                flexDirection: "column",
                gap: 12,
              }}
            >
              <div style={{ ...mono(10.5, 0.14), color: "var(--mut)" }}>
                NEW REPOSITORY IN {project?.key}
              </div>
              <input
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                onKeyDown={(event) => event.key === "Enter" && addRepo()}
                placeholder="repository-name"
              />
              <select
                value={draft.provider}
                onChange={(event) => setDraft({ ...draft, provider: event.target.value })}
              >
                {PROVIDERS.map((provider) => (
                  <option key={provider} value={provider}>
                    {CONNECTOR_LABELS[provider] ?? provider}
                  </option>
                ))}
              </select>
              <select
                value={draft.type}
                onChange={(event) => setDraft({ ...draft, type: event.target.value as RepoType })}
              >
                {(Object.keys(TYPES) as RepoType[]).map((type) => (
                  <option key={type} value={type}>
                    {TYPES[type].label}
                  </option>
                ))}
              </select>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className="btn p"
                  style={{ flex: 1, justifyContent: "center" }}
                  onClick={addRepo}
                >
                  Add
                </button>
                <button type="button" className="btn" onClick={() => setShowAdd(false)}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          {selectedEdge && (
            <div style={{ padding: "22px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={sectionLabel}>RELATION</div>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                  padding: 15,
                  border: "1px solid var(--line2)",
                  borderRadius: 11,
                  background: "oklch(0.225 0.018 295)",
                }}
              >
                <div style={mono(12.5)}>{byId[selectedEdge.from]?.name}</div>
                <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                  <span
                    style={{
                      width: 18,
                      height: 2,
                      borderRadius: 2,
                      display: "block",
                      background: KIND[selectedEdge.kind].color,
                      boxShadow: `0 0 10px ${KIND[selectedEdge.kind].color}`,
                    }}
                  />
                  <span style={{ fontSize: 11, color: "var(--ink2)", letterSpacing: "0.03em" }}>
                    {KIND[selectedEdge.kind].label}
                  </span>
                </div>
                <div style={mono(12.5)}>{byId[selectedEdge.to]?.name}</div>
              </div>
              <button
                type="button"
                className="btn"
                style={{ borderColor: "oklch(0.38 0.09 20)", color: "oklch(0.72 0.12 20)" }}
                onClick={() => {
                  deleteEdge(selectedEdge.id);
                  setSelectedEdgeId(null);
                }}
              >
                Delete relation
              </button>
            </div>
          )}

          {selected && !selectedEdge && (
            <div style={{ padding: "22px 20px", display: "flex", flexDirection: "column", gap: 20 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                  <ConnectorMark kind={selected.provider} size={30} />
                  <div style={{ ...mono(14), fontWeight: 500, wordBreak: "break-all" }}>
                    {selected.name}
                  </div>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  <span className="chip">
                    {CONNECTOR_LABELS[selected.provider] ?? selected.provider}
                  </span>
                  <span style={typeChip(selected.type)}>{TYPES[selected.type].label}</span>
                  {selected.connection && (
                    <span className="chip" style={{ color: "var(--ok)", borderColor: "var(--ok)" }}>
                      synced
                    </span>
                  )}
                </div>
                {selected.connection && (
                  <div style={{ ...mono(11), color: "var(--mut)", wordBreak: "break-all" }}>
                    {selected.connection.base_url}
                  </div>
                )}
              </div>

              {selected.connection && (
                <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                  <div style={sectionLabel}>CODE GRAPH</div>
                  {(() => {
                    const stats = graphStats(selected.connection);
                    return stats ? (
                      <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                        {(
                          [
                            ["files", stats.files],
                            ["modules", stats.modules],
                            ["symbols", stats.symbols],
                          ] as const
                        ).map(([label, value]) => (
                          <div key={label} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                            <span style={{ ...mono(15), fontWeight: 700 }}>
                              {value?.toLocaleString("en-GB") ?? "—"}
                            </span>
                            <span style={{ ...mono(9, 0.14), color: "var(--mut)" }}>
                              {label.toUpperCase()}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div style={{ fontSize: 11.5, color: "var(--mut)" }}>
                        Not synced yet — run a sync in Settings.
                      </div>
                    );
                  })()}
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                <div style={sectionLabel}>TYPE / LAYER</div>
                <select
                  value={selected.type}
                  onChange={(event) => setNodeType(selected, event.target.value as RepoType)}
                >
                  {(Object.keys(TYPES) as RepoType[]).map((type) => (
                    <option key={type} value={type}>
                      {TYPES[type].label}
                    </option>
                  ))}
                </select>
                {selected.connection && (
                  <>
                    <div style={{ ...sectionLabel, marginTop: 4 }}>PROJECT</div>
                    <select
                      value={state.connMeta[selected.connection.id]?.project ?? ""}
                      onChange={(event) =>
                        assignConnProject(selected, event.target.value || null)
                      }
                    >
                      <option value="">All projects</option>
                      {state.projects.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </>
                )}
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                <div style={sectionLabel}>CONSUMES →</div>
                {outgoing.map((edge) => (
                  <RelationRow
                    key={edge.id}
                    edge={edge}
                    other={byId[edge.to]}
                    onOpen={() => {
                      setSelectedId(edge.to);
                      setSelectedEdgeId(null);
                    }}
                    onDelete={() => deleteEdge(edge.id)}
                  />
                ))}
                {outgoing.length === 0 && (
                  <div style={{ fontSize: 11.5, color: "var(--mut)", padding: "2px 0" }}>
                    No outgoing relations.
                  </div>
                )}
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                <div style={sectionLabel}>← CONSUMED BY</div>
                {incoming.map((edge) => (
                  <RelationRow
                    key={edge.id}
                    edge={edge}
                    other={byId[edge.from]}
                    onOpen={() => {
                      setSelectedId(edge.from);
                      setSelectedEdgeId(null);
                    }}
                    onDelete={() => deleteEdge(edge.id)}
                  />
                ))}
                {incoming.length === 0 && (
                  <div style={{ fontSize: 11.5, color: "var(--mut)", padding: "2px 0" }}>
                    No incoming relations.
                  </div>
                )}
              </div>

              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className="btn glow"
                  style={{ flex: 1, justifyContent: "center" }}
                  onClick={() => {
                    setLinkKind("api");
                    setLinkFrom(selected.id);
                  }}
                >
                  + Relation
                </button>
                {selected.connection ? (
                  <Link href="/admin" className="btn">
                    Manage in Settings
                  </Link>
                ) : (
                  <button
                    type="button"
                    className="btn"
                    style={{ borderColor: "oklch(0.34 0.06 20)", color: "oklch(0.68 0.10 20)" }}
                    onClick={() => deleteNode(selected.id)}
                  >
                    Remove
                  </button>
                )}
              </div>
            </div>
          )}

          {!selected && !selectedEdge && (
            <div style={{ padding: "22px 20px", display: "flex", flexDirection: "column", gap: 20 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                <div style={sectionLabel}>PROJECT</div>
                <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-0.01em" }}>
                  {project?.name}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  <span className="chip" style={mono(10, 0.08)}>
                    {project?.key}
                  </span>
                  <span className="chip">
                    {connections.filter((c) => GIT_KINDS.has(c.kind)).length} synced sources
                  </span>
                </div>
              </div>

              <div style={{ height: 1, background: "var(--line)" }} />
              <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                <div style={sectionLabel}>LEGEND</div>
                <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                  <span
                    style={{
                      width: 22,
                      height: 2,
                      borderRadius: 2,
                      background: "var(--acc)",
                      boxShadow: "0 0 10px var(--acc)",
                      display: "block",
                    }}
                  />
                  <span style={{ fontSize: 11.5, color: "var(--ink2)" }}>
                    API call / service consumption
                  </span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                  <span
                    style={{
                      width: 22,
                      height: 0,
                      borderTop: "2px dashed var(--flow)",
                      display: "block",
                    }}
                  />
                  <span style={{ fontSize: 11.5, color: "var(--ink2)" }}>Data flow</span>
                </div>
              </div>

              <div style={{ height: 1, background: "var(--line)" }} />
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={sectionLabel}>LAYERS</div>
                {(Object.keys(TYPES) as RepoType[])
                  .map((type) => ({
                    type,
                    count: repos.filter((repo) => repo.type === type).length,
                  }))
                  .filter((row) => row.count > 0)
                  .map((row) => (
                    <div key={row.type} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={typeDot(row.type)} />
                      <span style={{ flex: 1, fontSize: 11.5, color: "var(--ink2)" }}>
                        {TYPES[row.type].label}
                      </span>
                      <span style={{ ...mono(11), color: "var(--mut)" }}>{row.count}</span>
                    </div>
                  ))}
                {repos.length === 0 && (
                  <div style={{ fontSize: 11.5, color: "var(--mut)" }}>Nothing on the map yet.</div>
                )}
              </div>

              <div
                style={{
                  padding: 14,
                  border: "1px solid var(--line)",
                  borderRadius: 11,
                  background: "oklch(0.20 0.02 300)",
                  fontSize: 11.5,
                  lineHeight: 1.6,
                  color: "var(--mut)",
                }}
              >
                Drag any card to reposition it, click to inspect, or use{" "}
                <span style={{ color: "oklch(0.80 0.13 300)" }}>Link</span> to draw a relation.
                Relations live in this browser for now — server-side persistence is on the
                roadmap.
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function RelationRow({
  edge,
  other,
  onOpen,
  onDelete,
}: {
  edge: MapEdge;
  other?: RepoView;
  onOpen: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 12px",
        border: "1px solid var(--line)",
        borderRadius: 9,
        background: "oklch(0.22 0.016 295)",
      }}
    >
      <span
        style={{
          width: 11,
          height: 2,
          borderRadius: 2,
          display: "block",
          flex: "0 0 11px",
          background: KIND[edge.kind].color,
          boxShadow: `0 0 8px ${KIND[edge.kind].color}`,
        }}
      />
      <span
        onClick={onOpen}
        style={{
          flex: 1,
          fontFamily: "var(--font-mono)",
          fontSize: 11.5,
          cursor: "pointer",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {other?.name ?? "?"}
      </span>
      <button
        type="button"
        onClick={onDelete}
        aria-label="delete relation"
        style={{
          border: 0,
          background: "transparent",
          color: "var(--mut)",
          fontSize: 14,
          lineHeight: 1,
          cursor: "pointer",
          padding: "2px 4px",
        }}
      >
        ×
      </button>
    </div>
  );
}
