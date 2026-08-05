"""Code graph + impact analysis (S5-4).

Modules are top-level directories (matching the vendor's module taxonomy convention,
e.g. `billing-core/…`). Impact confidence ladder:
- HIGH   — a query term hits a symbol name directly,
- MEDIUM — a file in an import-neighborhood of a HIGH hit,
- LOW    — only free-text/doc keyword overlap.
LOW-confidence modules get a discovery-effort suggestion instead of silent certainty
(ARCHITECTURE known-risk #1: static analysis has holes on legacy estates).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from estimo_code.treesitter import ParsedFile, Symbol, parse_repo
from estimo_core import Confidence, tr_lower

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN_RE = re.compile(r"[\wçğıöşüÇĞİÖŞÜ]+")


def _split_identifier(name: str) -> list[str]:
    return [part.lower() for part in _CAMEL_RE.sub(" ", name).replace("_", " ").split()]


@dataclass
class CodeGraph:
    repo: str
    commit: str
    files: list[ParsedFile]
    module_of: dict[str, str] = field(default_factory=dict)
    import_edges: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    symbol_terms: dict[str, set[tuple[str, str, int, int]]] = field(
        default_factory=lambda: defaultdict(set)
    )

    @classmethod
    def build(cls, root: Path, *, repo: str, commit: str = "workdir") -> CodeGraph:
        return cls._assemble(repo, commit, parse_repo(root))

    @classmethod
    def _assemble(cls, repo: str, commit: str, files: list[ParsedFile]) -> CodeGraph:
        graph = cls(repo=repo, commit=commit, files=files)
        by_symbol_name: dict[str, set[str]] = defaultdict(set)
        for parsed in files:
            module = parsed.path.split("/")[0] if "/" in parsed.path else "(root)"
            graph.module_of[parsed.path] = module
            for symbol in parsed.symbols:
                by_symbol_name[symbol.name.lower()].add(parsed.path)
                for term in _split_identifier(symbol.name):
                    graph.symbol_terms[term].add(
                        (parsed.path, symbol.name, symbol.start_line, symbol.end_line)
                    )
        for parsed in files:
            for import_stmt in parsed.imports:
                tail = import_stmt.split(".")[-1].split("/")[-1].strip("'\" {}")
                for target in by_symbol_name.get(tail.lower(), set()):
                    if target != parsed.path:
                        graph.import_edges[parsed.path].add(target)
        return graph

    def evidence_uri(self, path: str, start: int, end: int) -> str:
        return f"repo://{self.repo}@{self.commit}/{path}#L{start}-L{end}"

    def to_payload(self) -> dict[str, Any]:
        """JSON-serializable form for persistence (S13-2).

        Only `files` is stored: `module_of`, `import_edges` and `symbol_terms` are
        derived in `_assemble`, and storing them too would let the stored copy drift
        from the derivation the code actually uses.
        """
        return {
            "repo": self.repo,
            "commit": self.commit,
            "files": [
                {
                    "path": f.path,
                    "language": f.language,
                    "line_count": f.line_count,
                    "imports": list(f.imports),
                    "symbols": [
                        {
                            "name": s.name,
                            "kind": s.kind,
                            "path": s.path,
                            "start_line": s.start_line,
                            "end_line": s.end_line,
                            "doc": s.doc,
                        }
                        for s in f.symbols
                    ],
                }
                for f in self.files
            ],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CodeGraph:
        files = [
            ParsedFile(
                path=f["path"],
                language=f["language"],
                line_count=f["line_count"],
                imports=tuple(f["imports"]),
                symbols=tuple(Symbol(**s) for s in f["symbols"]),
            )
            for f in payload["files"]
        ]
        return cls._assemble(str(payload["repo"]), str(payload["commit"]), files)


# Turkish query term → identifier-language synonyms (identifiers are English).
_TERM_SYNONYMS: dict[str, tuple[str, ...]] = {
    "taksit": ("installment",),
    "fatura": ("invoice", "billing", "bill"),
    "kampanya": ("campaign",),
    "bayi": ("dealer",),
    "uygunluk": ("eligibility",),
    "ödeme": ("payment",),
    "bakiye": ("balance",),
    "muhasebe": ("accounting", "ledger"),
    "rapor": ("report", "export"),
    "sipariş": ("order",),
    "müşteri": ("customer",),
    "komisyon": ("commission", "fee"),
    "sözleşme": ("contract",),
    "abone": ("subscriber", "subscription"),
}


@dataclass(frozen=True)
class ModuleImpact:
    module: str
    confidence: Confidence
    evidence_uris: tuple[str, ...]
    reason: str
    discovery_suggested: bool = False


def impact_for(graph: CodeGraph, text: str, *, max_evidence: int = 3) -> list[ModuleImpact]:
    """Rank modules likely touched by `text` (a work item / requirement)."""
    terms: set[str] = set()
    for token in _TOKEN_RE.findall(tr_lower(text)):
        if len(token) < 3:
            continue
        terms.add(token)
        terms.update(_TERM_SYNONYMS.get(token, ()))
        # Morphological bridge: the token must EXTEND the full base (taksitli -> taksit),
        # never merely share a prefix window (kampüs must not bridge to campaign).
        for base, synonyms in _TERM_SYNONYMS.items():
            if len(token) > len(base) and token.startswith(base):
                terms.update(synonyms)

    direct_hits: dict[str, list[tuple[str, str, int, int]]] = defaultdict(list)
    for term in terms:
        for hit in graph.symbol_terms.get(term, ()):
            direct_hits[hit[0]].append(hit)

    neighbor_files: set[str] = set()
    for path in direct_hits:
        neighbor_files.update(graph.import_edges.get(path, set()))
        neighbor_files.update(src for src, targets in graph.import_edges.items() if path in targets)
    neighbor_files -= set(direct_hits)

    impacts: dict[str, ModuleImpact] = {}
    for path, hits in direct_hits.items():
        module = graph.module_of[path]
        uris = tuple(graph.evidence_uri(p, s, e) for p, _, s, e in sorted(hits)[:max_evidence])
        existing = impacts.get(module)
        if existing is None or existing.confidence is not Confidence.HIGH:
            impacts[module] = ModuleImpact(
                module=module,
                confidence=Confidence.HIGH,
                evidence_uris=uris,
                reason=f"symbol match: {', '.join(sorted({h[1] for h in hits})[:3])}",
            )
    for path in neighbor_files:
        module = graph.module_of[path]
        if module in impacts:
            continue
        parsed = next(f for f in graph.files if f.path == path)
        impacts[module] = ModuleImpact(
            module=module,
            confidence=Confidence.MEDIUM,
            evidence_uris=(graph.evidence_uri(path, 1, parsed.line_count),),
            reason="import neighborhood of a direct hit",
        )

    if not impacts:
        # Keyword-only fallback over docs/comments; explicitly LOW + discovery flag.
        for parsed in graph.files:
            haystack = (
                " ".join(filter(None, (s.doc for s in parsed.symbols))).lower()
                + parsed.path.lower()
            )
            if any(term in haystack for term in terms):
                module = graph.module_of[parsed.path]
                if module not in impacts:
                    impacts[module] = ModuleImpact(
                        module=module,
                        confidence=Confidence.LOW,
                        evidence_uris=(graph.evidence_uri(parsed.path, 1, parsed.line_count),),
                        reason="keyword overlap only — static signal weak",
                        discovery_suggested=True,
                    )

    order = {Confidence.HIGH: 0, Confidence.MEDIUM: 1, Confidence.LOW: 2}
    return sorted(impacts.values(), key=lambda i: (order[i.confidence], i.module))
