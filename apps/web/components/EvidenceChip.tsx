/** Evidence chip with kind-specific color (UI-VISION: EvidenceChip). */

const KIND_COLOR: Record<string, string> = {
  code: "var(--ev-code)",
  wiki: "var(--ev-wiki)",
  ledger: "var(--ev-analog)",
  answer: "var(--ev-ans)",
  note: "var(--mut)",
};

export function EvidenceChip({
  uri,
  kind,
  label,
}: {
  uri: string;
  kind: string;
  label?: string | null;
}) {
  const color = KIND_COLOR[kind] ?? "var(--mut)";
  return (
    <span
      className="chip"
      title={uri}
      style={{ borderColor: color, color, marginRight: 6, marginBottom: 4 }}
    >
      {kind}
      {label ? ` · ${label.slice(0, 40)}` : ""}
    </span>
  );
}
