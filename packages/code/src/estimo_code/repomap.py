"""Token-budgeted repo map (Aider-style ranking, S5-1).

Symbols are ranked by inbound reference pressure (how many files import their file)
plus doc presence; the map renders module-by-module until the budget runs out.
"""

from __future__ import annotations

from collections import defaultdict

from estimo_code.graph import CodeGraph


def render_repo_map(graph: CodeGraph, *, token_budget: int = 1500) -> str:
    inbound: dict[str, int] = defaultdict(int)
    for targets in graph.import_edges.values():
        for target in targets:
            inbound[target] += 1

    by_module: dict[str, list[str]] = defaultdict(list)
    for parsed in sorted(graph.files, key=lambda f: (-inbound[f.path], f.path)):
        entries = [
            f"  {symbol.kind} {symbol.name} (L{symbol.start_line})"
            + (f" — {symbol.doc[:80]}" if symbol.doc else "")
            for symbol in parsed.symbols
        ]
        if entries:
            by_module[graph.module_of[parsed.path]].append(
                f"{parsed.path} (in:{inbound[parsed.path]})\n" + "\n".join(entries)
            )

    lines = [f"# Repo map — {graph.repo}@{graph.commit}"]
    budget = token_budget * 4  # rough chars-per-token
    used = len(lines[0])
    for module in sorted(by_module):
        header = f"\n## {module}"
        if used + len(header) > budget:
            lines.append("\n… (token budget reached)")
            break
        lines.append(header)
        used += len(header)
        for block in by_module[module]:
            if used + len(block) > budget:
                lines.append("… (token budget reached)")
                used = budget
                break
            lines.append(block)
            used += len(block)
    return "\n".join(lines)
