"""Module wiki generation (S5-3): "purpose + interfaces + dependencies" pages.

Deterministic skeleton from the graph (docs, public symbols, import edges); an optional
gateway LLM pass tightens the purpose paragraph. Pages are returned as retrieval-ready
chunk payloads (source_type="code-wiki") for the S3 knowledge shelf — the mid-altitude
grounding tier between repo map and raw code.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass

from estimo_code.graph import CodeGraph
from estimo_gateway import GatewayClient, GatewayError

logger = logging.getLogger("estimo.code")

_PURPOSE_PROMPT = (
    "Summarize this software module's purpose in 2-3 sentences for an estimation "
    "knowledge base. Factual, no marketing. Reply with ONLY a JSON object: "
    '{"purpose": "<summary>"}. Module data:\n'
)


@dataclass(frozen=True)
class ModuleWikiPage:
    module: str
    title: str
    text: str
    source_ref: str


def _skeleton(graph: CodeGraph, module: str) -> tuple[str, str]:
    files = [f for f in graph.files if graph.module_of[f.path] == module]
    docs = [s.doc for f in files for s in f.symbols if s.doc]
    interfaces = [
        f"- {s.kind} `{s.name}` ({f.path}:L{s.start_line})"
        for f in files
        for s in f.symbols
        if s.kind in ("class", "interface", "enum", "function")
    ]
    deps: set[str] = set()
    for parsed in files:
        for target in graph.import_edges.get(parsed.path, set()):
            target_module = graph.module_of[target]
            if target_module != module:
                deps.add(target_module)
    purpose = (docs[0] if docs else f"{module} module ({len(files)} source files).")[:400]
    body = "\n".join(
        [
            f"# {module}",
            "",
            "## Purpose",
            purpose,
            "",
            "## Interfaces",
            *(interfaces or ["- (no public symbols found)"]),
            "",
            "## Depends on",
            *(sorted(f"- {d}" for d in deps) or ["- (no cross-module imports found)"]),
        ]
    )
    return purpose, body


async def generate_module_wikis(
    graph: CodeGraph, *, client: GatewayClient | None = None
) -> list[ModuleWikiPage]:
    modules: dict[str, list[str]] = defaultdict(list)
    for path, module in graph.module_of.items():
        modules[module].append(path)

    pages: list[ModuleWikiPage] = []
    for module in sorted(modules):
        purpose, body = _skeleton(graph, module)
        if client is not None:
            try:
                result = await client.complete(
                    "knowledge",
                    [{"role": "user", "content": _PURPOSE_PROMPT + body[:4000]}],
                    temperature=0.2,
                    max_tokens=200,
                )
                payload = json.loads(result.text)
                if not isinstance(payload, dict):
                    msg = f"gateway reply was JSON {type(payload).__name__}, expected object"
                    raise TypeError(msg)
                refined = str(payload.get("purpose", "")).strip()
                if 20 < len(refined) < 600:
                    body = body.replace(purpose, refined, 1)
            except (GatewayError, json.JSONDecodeError, TypeError) as exc:
                logger.warning("module wiki refinement degraded: %s", exc)
        pages.append(
            ModuleWikiPage(
                module=module,
                title=f"Module: {module}",
                text=body,
                source_ref=graph.evidence_uri(module, 1, 1).rsplit("#", 1)[0],
            )
        )
    return pages
