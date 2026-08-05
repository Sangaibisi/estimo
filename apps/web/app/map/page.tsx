"use client";

/** Repository map — the product's centerpiece surface (docs/design/
 * repository-map.dc.html, ported 1:1 where it made sense).
 *
 * The map answers "what are this company's repositories and how do they relate":
 * typed nodes (frontend … infra) laid out by architectural layer, with directed
 * API-call and data-flow relations drawn between them. A node either IS a synced
 * connection — carrying its live code-graph stats — or is one somebody declared
 * because it exists in the architecture even if Estimo does not index it.
 *
 * Everything here is server state (S14-1): projects, nodes, relations, placement
 * and typing live in the tenant's database under RLS. Shaping the map is the
 * project owner's job; everyone in the workspace can read it, and for them the
 * editing affordances are simply absent rather than present-and-failing.
 */

import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  type ConnectionEntry,
  type MapRelation,
  type MapRepo,
  type ProjectEntry,
  type ProjectMap,
} from "@/lib/api";
import { canShapeMap } from "@/lib/auth";
import { useSession } from "@/components/Session";
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

const nodeType = (repo: MapRepo): RepoType =>
  (repo.node_type in TYPES ? repo.node_type : "be") as RepoType;

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

/* ---------------- Page ---------------- */

export default function MapPage() {
  const session = useSession();
  const mayEdit = canShapeMap(session.role) || !session.accountsExist;

  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [board, setBoard] = useState<ProjectMap | null>(null);
  const [connections, setConnections] = useState<ConnectionEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [linkKind, setLinkKind] = useState<EdgeKind | null>(null);
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  // Placement while a card is under the cursor. The server hears about it once,
  // on release — not sixty times a second.
  const [drafted, setDrafted] = useState<Record<string, { x: number; y: number }>>({});

  const [showAdd, setShowAdd] = useState(false);
  const [showAddProject, setShowAddProject] = useState(false);
  const [projectDraft, setProjectDraft] = useState("");
  const [draft, setDraft] = useState({
    name: "",
    provider: "github",
    type: "be" as RepoType,
    connectionId: "",
  });

  const loadProjects = useCallback(async () => {
    const rows = await api.listProjects();
    setProjects(rows);
    setProjectId((current) => current ?? rows[0]?.id ?? null);
    return rows;
  }, []);

  const loadBoard = useCallback(async (id: string) => {
    setBoard(await api.projectMap(id));
  }, []);

  useEffect(() => {
    let live = true;
    Promise.all([loadProjects(), api.listConnections().catch(() => [])])
      .then(([, conns]) => {
        if (!live) return;
        setConnections(conns as ConnectionEntry[]);
        setLoading(false);
      })
      .catch((err) => {
        if (!live) return;
        setError(String(err));
        setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [loadProjects]);

  useEffect(() => {
    if (!projectId) {
      setBoard(null);
      return;
    }
    let live = true;
    api
      .projectMap(projectId)
      .then((next) => live && setBoard(next))
      .catch((err) => live && setError(String(err)));
    setSelectedId(null);
    setSelectedEdgeId(null);
    setDrafted({});
    return () => {
      live = false;
    };
  }, [projectId]);

  const repos = useMemo(() => board?.repos ?? [], [board]);
  const relations: MapRelation[] = useMemo(() => board?.relations ?? [], [board]);

  const byId = useMemo(() => {
    const map: Record<string, MapRepo> = {};
    for (const repo of repos) map[repo.id] = repo;
    return map;
  }, [repos]);

  /** Connections not yet on this map — the "add a synced repository" shortlist. */
  const unplaced = useMemo(() => {
    const linked = new Set(repos.map((repo) => repo.connection_id).filter(Boolean));
    return connections.filter((c) => GIT_KINDS.has(c.kind) && !linked.has(c.id));
  }, [connections, repos]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      if (projectId) await loadBoard(projectId);
      await loadProjects();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  /* ---- Layout: layer columns, platform row, dragged points on top. ---- */
  const layout = useMemo(() => {
    const pos: Record<string, { x: number; y: number }> = {};
    const columns: { label: string; x: number; y: number; wide?: boolean }[] = [];
    const colX: Record<string, number> = { client: 60, middleware: 402, service: 744, data: 1086 };
    const groups: Record<string, MapRepo[]> = {};
    for (const repo of repos) (groups[TYPES[nodeType(repo)].layer] ??= []).push(repo);
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
      const stored =
        drafted[repo.id] ??
        (repo.pos_x !== null && repo.pos_y !== null ? { x: repo.pos_x, y: repo.pos_y } : null);
      if (stored) pos[repo.id] = stored;
      const point = pos[repo.id];
      if (point) {
        width = Math.max(width, point.x + W + 70);
        height = Math.max(height, point.y + H + 70);
      }
    }
    return { pos, columns, width, height };
  }, [repos, drafted]);

  const posRef = useRef(layout.pos);
  posRef.current = layout.pos;

  /* ---- Selection & linking ---- */
  const select = useCallback(
    (id: string) => {
      if (linkKind && mayEdit) {
        if (!linkFrom) {
          setLinkFrom(id);
          return;
        }
        if (linkFrom === id) {
          setLinkFrom(null);
          return;
        }
        const from = linkFrom;
        const kind = linkKind;
        setLinkKind(null);
        setLinkFrom(null);
        setSelectedEdgeId(null);
        setSelectedId(id);
        void run(() => api.addRelation(projectId!, from, id, kind));
        return;
      }
      setSelectedEdgeId(null);
      setSelectedId((current) => (current === id ? null : id));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [linkKind, linkFrom, mayEdit, projectId],
  );

  /* ---- Dragging ---- */
  const dragRef = useRef<{
    id: string;
    sx: number;
    sy: number;
    ox: number;
    oy: number;
    moved: number;
  } | null>(null);

  const onDragMove = useCallback((event: MouseEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    const dx = event.clientX - drag.sx;
    const dy = event.clientY - drag.sy;
    drag.moved = Math.max(drag.moved, Math.abs(dx) + Math.abs(dy));
    if (drag.moved < 4) return;
    const next = { x: Math.max(8, drag.ox + dx), y: Math.max(8, drag.oy + dy) };
    setDrafted((current) => ({ ...current, [drag.id]: next }));
  }, []);

  const onDragEnd = useCallback(() => {
    const drag = dragRef.current;
    window.removeEventListener("mousemove", onDragMove);
    window.removeEventListener("mouseup", onDragEnd);
    dragRef.current = null;
    setDragging(null);
    if (!drag) return;
    if (drag.moved < 4) {
      select(drag.id);
      return;
    }
    const point = posRef.current[drag.id];
    if (point && projectId) {
      void run(() =>
        api.updateRepo(projectId, drag.id, { pos_x: point.x, pos_y: point.y }),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onDragMove, select, projectId]);

  const onNodeDown = (id: string) => (event: React.MouseEvent) => {
    if (event.button !== 0) return;
    event.preventDefault();
    if (!mayEdit) {
      select(id);
      return;
    }
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
  const selectedEdge = relations.find((edge) => edge.id === selectedEdgeId) ?? null;
  const related = useMemo(() => {
    const set = new Set<string>();
    if (selectedId) {
      set.add(selectedId);
      for (const edge of relations) {
        if (edge.from_repo_id === selectedId) set.add(edge.to_repo_id);
        if (edge.to_repo_id === selectedId) set.add(edge.from_repo_id);
      }
    }
    return set;
  }, [selectedId, relations]);

  const outgoing = selected
    ? relations.filter((edge) => edge.from_repo_id === selected.id)
    : [];
  const incoming = selected ? relations.filter((edge) => edge.to_repo_id === selected.id) : [];

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

  const project = projects.find((entry) => entry.id === projectId) ?? null;

  if (loading) {
    return (
      <section className="scr">
        <div className="page-h">
          <IconMap size={18} />
          <h2>Repository map</h2>
        </div>
        <div style={{ color: "var(--mut)", fontSize: 12.5 }}>Loading the workspace…</div>
      </section>
    );
  }

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

        {mayEdit && project && (
          <div style={{ display: "flex", gap: 9, alignItems: "center", flexWrap: "wrap" }}>
            {(["api", "data"] as EdgeKind[]).map((kind) =>
              linkKind === kind ? (
                <button
                  key={kind}
                  type="button"
                  className="btn"
                  style={{
                    borderColor: kind === "api" ? "oklch(0.66 0.16 300)" : "oklch(0.66 0.13 200)",
                    background: kind === "api" ? "oklch(0.30 0.08 300)" : "oklch(0.30 0.06 200)",
                    color: kind === "api" ? "oklch(0.94 0.04 300)" : "oklch(0.94 0.04 200)",
                    boxShadow:
                      kind === "api"
                        ? "0 0 22px -6px oklch(0.66 0.18 300)"
                        : "0 0 22px -6px oklch(0.66 0.14 200)",
                  }}
                  onClick={() => {
                    setLinkKind(null);
                    setLinkFrom(null);
                  }}
                >
                  <span
                    style={
                      kind === "api"
                        ? {
                            width: 15,
                            height: 2,
                            borderRadius: 2,
                            background: "oklch(0.85 0.14 300)",
                            display: "block",
                            animation: "om-pulse 1.2s ease-in-out infinite",
                          }
                        : {
                            width: 15,
                            height: 0,
                            borderTop: "2px dashed oklch(0.86 0.12 200)",
                            display: "block",
                            animation: "om-pulse 1.2s ease-in-out infinite",
                          }
                    }
                  />
                  Linking… cancel
                </button>
              ) : (
                <button
                  key={kind}
                  type="button"
                  className={kind === "api" ? "btn glow" : "btn"}
                  onClick={() => {
                    setLinkKind(kind);
                    setLinkFrom(null);
                  }}
                >
                  <span
                    style={
                      kind === "api"
                        ? {
                            width: 15,
                            height: 2,
                            borderRadius: 2,
                            background: "var(--acc)",
                            display: "block",
                          }
                        : {
                            width: 15,
                            height: 0,
                            borderTop: "2px dashed var(--flow)",
                            display: "block",
                          }
                    }
                  />
                  {kind === "api" ? "Link API call" : "Link data flow"}
                </button>
              ),
            )}
            <button type="button" className="btn" onClick={() => setShowAdd(!showAdd)}>
              + Repository
            </button>
          </div>
        )}

        <div style={{ flex: "1 0 0" }} />
        <div style={{ ...mono(11), color: "var(--mut)", whiteSpace: "nowrap" }}>
          {repos.length} repositories · {relations.length} relations
        </div>
      </div>

      {error && (
        <div
          role="alert"
          style={{
            flex: "0 0 auto",
            padding: "8px 20px",
            background: "var(--crit-bg)",
            color: "var(--crit)",
            fontSize: 12,
            borderBottom: "1px solid var(--crit)",
          }}
        >
          {error}
        </div>
      )}

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
            {mayEdit && (
              <button
                type="button"
                className="btn"
                style={{ padding: "3px 7px", fontSize: 11, lineHeight: 1 }}
                onClick={() => setShowAddProject(!showAddProject)}
              >
                +
              </button>
            )}
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
                  placeholder="Project name"
                  style={{ fontSize: 11 }}
                />
                <div style={{ display: "flex", gap: 6 }}>
                  <button
                    type="button"
                    className="btn p"
                    style={{ flex: 1, justifyContent: "center" }}
                    disabled={busy || !projectDraft.trim()}
                    onClick={() =>
                      run(async () => {
                        const created = await api.createProject(projectDraft.trim());
                        setProjectDraft("");
                        setShowAddProject(false);
                        setProjectId(created.id);
                      })
                    }
                  >
                    Create
                  </button>
                  <button type="button" className="btn" onClick={() => setShowAddProject(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
            {projects.map((entry) => {
              const isActive = entry.id === projectId;
              return (
                <div
                  key={entry.id}
                  onClick={() => setProjectId(entry.id)}
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
                      {entry.name}
                    </span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, paddingLeft: 16 }}>
                    <span style={{ ...mono(9.5, 0.08), color: "var(--mut)" }}>{entry.key}</span>
                    <span style={{ flex: 1 }} />
                    <span style={{ ...mono(9.5), color: "var(--mut)" }}>
                      {entry.repos} repos · {entry.relations} rel
                    </span>
                  </div>
                </div>
              );
            })}
            {projects.length === 0 && (
              <div style={{ fontSize: 11.5, color: "var(--mut)", padding: "4px 2px" }}>
                No projects yet.
              </div>
            )}
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
              style={{
                position: "absolute",
                left: 0,
                top: 0,
                overflow: "visible",
                pointerEvents: "none",
              }}
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
              {relations.map((edge) => {
                const from = layout.pos[edge.from_repo_id];
                const to = layout.pos[edge.to_repo_id];
                if (!from || !to) return null;
                const kind = KIND[(edge.kind as EdgeKind) in KIND ? (edge.kind as EdgeKind) : "api"];
                const hot =
                  !!selectedId &&
                  (edge.from_repo_id === selectedId || edge.to_repo_id === selectedId);
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
              const type = nodeType(repo);
              const point = layout.pos[repo.id] ?? { x: 0, y: 0 };
              const on = !selectedId || related.has(repo.id);
              const isSel = repo.id === selectedId;
              const isFrom = repo.id === linkFrom;
              const isDrag = repo.id === dragging;
              const degree = relations.filter(
                (edge) => edge.from_repo_id === repo.id || edge.to_repo_id === repo.id,
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
                    left: point.x,
                    top: point.y,
                    width: W,
                    height: H,
                    cursor: isDrag ? "grabbing" : mayEdit ? "grab" : "pointer",
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
                      <span style={typeDot(type)} />
                      <span
                        style={{
                          fontSize: 10,
                          letterSpacing: "0.07em",
                          color: "var(--mut)",
                          textTransform: "uppercase",
                        }}
                      >
                        {TYPES[type].label}
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

            {projects.length === 0 && (
              <EmptyNote>
                No projects yet.{" "}
                {mayEdit
                  ? "Create one on the left — a project is a map of the repositories that make up one piece of the landscape."
                  : "A project owner has to create one before there is a map to read."}
              </EmptyNote>
            )}
            {projects.length > 0 && repos.length === 0 && (
              <EmptyNote>
                This project has no repositories yet.{" "}
                {mayEdit ? (
                  <>
                    Use <span style={{ color: "oklch(0.82 0.13 300)" }}>+ Repository</span> to add
                    one, or connect a real repository in <Link href="/admin">Settings</Link> and
                    place it here.
                  </>
                ) : (
                  "A project owner shapes the map."
                )}
              </EmptyNote>
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
          {showAdd && mayEdit && project && (
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
                NEW REPOSITORY IN {project.key}
              </div>
              {unplaced.length > 0 && (
                <>
                  <div style={{ ...sectionLabel }}>SYNCED, NOT YET PLACED</div>
                  {unplaced.map((connection) => (
                    <button
                      key={connection.id}
                      type="button"
                      className="btn"
                      style={{ justifyContent: "flex-start", gap: 9 }}
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          await api.addRepo(project.id, {
                            name: connection.name,
                            provider: connection.kind,
                            node_type: draft.type,
                            connection_id: connection.id,
                          });
                          setShowAdd(false);
                        })
                      }
                    >
                      <ConnectorMark kind={connection.kind} size={20} />
                      {connection.name}
                    </button>
                  ))}
                  <div style={{ height: 1, background: "var(--line)" }} />
                </>
              )}
              <input
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
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
                  disabled={busy || !draft.name.trim()}
                  onClick={() =>
                    run(async () => {
                      await api.addRepo(project.id, {
                        name: draft.name.trim(),
                        provider: draft.provider,
                        node_type: draft.type,
                      });
                      setDraft({ ...draft, name: "" });
                      setShowAdd(false);
                    })
                  }
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
                <div style={mono(12.5)}>{byId[selectedEdge.from_repo_id]?.name}</div>
                <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                  <span
                    style={{
                      width: 18,
                      height: 2,
                      borderRadius: 2,
                      display: "block",
                      background: KIND[selectedEdge.kind as EdgeKind].color,
                      boxShadow: `0 0 10px ${KIND[selectedEdge.kind as EdgeKind].color}`,
                    }}
                  />
                  <span style={{ fontSize: 11, color: "var(--ink2)", letterSpacing: "0.03em" }}>
                    {KIND[selectedEdge.kind as EdgeKind].label}
                  </span>
                </div>
                <div style={mono(12.5)}>{byId[selectedEdge.to_repo_id]?.name}</div>
              </div>
              {mayEdit && (
                <button
                  type="button"
                  className="btn"
                  style={{ borderColor: "oklch(0.38 0.09 20)", color: "oklch(0.72 0.12 20)" }}
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await api.deleteRelation(projectId!, selectedEdge.id);
                      setSelectedEdgeId(null);
                    })
                  }
                >
                  Delete relation
                </button>
              )}
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
                  <span style={typeChip(nodeType(selected))}>
                    {TYPES[nodeType(selected)].label}
                  </span>
                  {selected.connection ? (
                    <span className="chip" style={{ color: "var(--ok)", borderColor: "var(--ok)" }}>
                      synced
                    </span>
                  ) : (
                    <span className="chip" style={{ color: "var(--mut)" }}>
                      declared
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
                  {selected.connection.graph ? (
                    <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                      {(
                        [
                          ["files", selected.connection.graph.files],
                          ["modules", selected.connection.graph.modules],
                          ["symbols", selected.connection.graph.symbols],
                        ] as const
                      ).map(([label, value]) => (
                        <div
                          key={label}
                          style={{ display: "flex", flexDirection: "column", gap: 3 }}
                        >
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
                  )}
                </div>
              )}

              {mayEdit && (
                <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                  <div style={sectionLabel}>TYPE / LAYER</div>
                  <select
                    value={nodeType(selected)}
                    disabled={busy}
                    onChange={(event) =>
                      run(() =>
                        api.updateRepo(projectId!, selected.id, {
                          node_type: event.target.value,
                        }),
                      )
                    }
                  >
                    {(Object.keys(TYPES) as RepoType[]).map((type) => (
                      <option key={type} value={type}>
                        {TYPES[type].label}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                <div style={sectionLabel}>CONSUMES →</div>
                {outgoing.map((edge) => (
                  <RelationRow
                    key={edge.id}
                    edge={edge}
                    other={byId[edge.to_repo_id]}
                    mayEdit={mayEdit}
                    onOpen={() => {
                      setSelectedId(edge.to_repo_id);
                      setSelectedEdgeId(null);
                    }}
                    onDelete={() => run(() => api.deleteRelation(projectId!, edge.id))}
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
                    other={byId[edge.from_repo_id]}
                    mayEdit={mayEdit}
                    onOpen={() => {
                      setSelectedId(edge.from_repo_id);
                      setSelectedEdgeId(null);
                    }}
                    onDelete={() => run(() => api.deleteRelation(projectId!, edge.id))}
                  />
                ))}
                {incoming.length === 0 && (
                  <div style={{ fontSize: 11.5, color: "var(--mut)", padding: "2px 0" }}>
                    No incoming relations.
                  </div>
                )}
              </div>

              {mayEdit && (
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
                  <button
                    type="button"
                    className="btn"
                    style={{ borderColor: "oklch(0.34 0.06 20)", color: "oklch(0.68 0.10 20)" }}
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await api.deleteRepo(projectId!, selected.id);
                        setSelectedId(null);
                      })
                    }
                  >
                    Remove
                  </button>
                </div>
              )}
            </div>
          )}

          {!selected && !selectedEdge && (
            <div style={{ padding: "22px 20px", display: "flex", flexDirection: "column", gap: 20 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                <div style={sectionLabel}>PROJECT</div>
                <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-0.01em" }}>
                  {project?.name ?? "—"}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {project && (
                    <span className="chip" style={mono(10, 0.08)}>
                      {project.key}
                    </span>
                  )}
                  <span className="chip">{unplaced.length} synced, unplaced</span>
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
                    count: repos.filter((repo) => nodeType(repo) === type).length,
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
                {mayEdit ? (
                  <>
                    Drag any card to reposition it, click to inspect, or use{" "}
                    <span style={{ color: "oklch(0.80 0.13 300)" }}>Link</span> to draw a relation.
                    Everything you place is saved to this workspace.
                  </>
                ) : (
                  <>
                    Click a card to inspect it. Shaping the map — adding repositories and drawing
                    relations — is the project owner&apos;s job.
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function EmptyNote({ children }: { children: React.ReactNode }) {
  return (
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
      {children}
    </div>
  );
}

function RelationRow({
  edge,
  other,
  mayEdit,
  onOpen,
  onDelete,
}: {
  edge: MapRelation;
  other?: MapRepo;
  mayEdit: boolean;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const kind = KIND[(edge.kind as EdgeKind) in KIND ? (edge.kind as EdgeKind) : "api"];
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
          background: kind.color,
          boxShadow: `0 0 8px ${kind.color}`,
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
      {mayEdit && (
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
      )}
    </div>
  );
}
