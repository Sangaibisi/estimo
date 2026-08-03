"""tree-sitter symbol/import extraction for Java and TypeScript sources.

The graph store is indexer-agnostic: this module is today's populator; a SCIP loader
(scip-java/scip-typescript emitted `index.scip`) slots in beside it at the first
deployment with a real build chain — precision upgrades, the graph model stays.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tree_sitter_java
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

_JAVA = Language(tree_sitter_java.language())
_TYPESCRIPT = Language(tree_sitter_typescript.language_typescript())
# JSX needs the dedicated tsx grammar — the plain TS grammar errors on JSX nodes.
_TSX = Language(tree_sitter_typescript.language_tsx())

_LANGUAGES = {"java": _JAVA, "typescript": _TYPESCRIPT, "tsx": _TSX}
_SUFFIXES = {".java": "java", ".ts": "typescript", ".tsx": "tsx"}

_SYMBOL_NODES = {
    "java": {
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "method_declaration",
        "constructor_declaration",
    },
    "typescript": {
        "class_declaration",
        "interface_declaration",
        "function_declaration",
        "method_definition",
        "enum_declaration",
    },
}
_SYMBOL_NODES["tsx"] = _SYMBOL_NODES["typescript"]
_IMPORT_NODES = {"java": {"import_declaration"}, "typescript": {"import_statement"}}
_IMPORT_NODES["tsx"] = _IMPORT_NODES["typescript"]


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    doc: str | None = None


@dataclass(frozen=True)
class ParsedFile:
    path: str
    language: str
    symbols: tuple[Symbol, ...]
    imports: tuple[str, ...]
    line_count: int


def _parser_for(language: str) -> Parser:
    return Parser(_LANGUAGES[language])


def _node_name(node: Node) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is not None and name_node.text is not None:
        return name_node.text.decode("utf-8")
    return None


def _leading_comment(node: Node, source: bytes) -> str | None:
    sibling = node.prev_named_sibling
    if sibling is not None and "comment" in sibling.type:
        text = source[sibling.start_byte : sibling.end_byte].decode("utf-8", "replace")
        cleaned = " ".join(
            line.strip(" */") for line in text.splitlines() if line.strip(" */")
        ).removeprefix("/**")
        return cleaned[:300] or None
    return None


def parse_source(path: Path, relative_to: Path) -> ParsedFile | None:
    language = _SUFFIXES.get(path.suffix)
    if language is None:
        return None
    source = path.read_bytes()
    tree = _parser_for(language).parse(source)
    symbols: list[Symbol] = []
    imports: list[str] = []
    rel = str(path.relative_to(relative_to))

    def visit(node: Node) -> None:
        if (
            language != "java"
            and node.type == "variable_declarator"
            and (value := node.child_by_field_name("value")) is not None
            and value.type in ("arrow_function", "function_expression")
        ):
            name = _node_name(node)
            if name:
                # The leading comment sits on the export_statement / lexical
                # declaration, not the declarator — walk up for the doc anchor.
                decl = node.parent
                doc_anchor = (
                    decl.parent
                    if decl is not None
                    and decl.parent is not None
                    and decl.parent.type == "export_statement"
                    else decl
                )
                symbols.append(
                    Symbol(
                        name=name,
                        kind="function",
                        path=rel,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        doc=_leading_comment(doc_anchor, source)
                        if doc_anchor is not None
                        else None,
                    )
                )
        if node.type in _SYMBOL_NODES[language]:
            name = _node_name(node)
            if name:
                symbols.append(
                    Symbol(
                        name=name,
                        kind=node.type.removesuffix("_declaration").removesuffix("_definition"),
                        path=rel,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        doc=_leading_comment(node, source),
                    )
                )
        if node.type in _IMPORT_NODES[language]:
            text = source[node.start_byte : node.end_byte].decode("utf-8", "replace")
            imports.append(text.strip().rstrip(";"))
        for child in node.named_children:
            visit(child)

    visit(tree.root_node)
    return ParsedFile(
        path=rel,
        language=language,
        symbols=tuple(symbols),
        imports=tuple(imports),
        line_count=source.count(b"\n") + 1,
    )


def parse_repo(root: Path) -> list[ParsedFile]:
    resolved_root = root.resolve()
    files: list[ParsedFile] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in _SUFFIXES or not path.is_file():
            continue
        # Never follow symlinks out of the repo root (content-leak guard).
        if path.is_symlink() or not path.resolve().is_relative_to(resolved_root):
            continue
        parsed = parse_source(path, root)
        if parsed is not None:
            files.append(parsed)
    return files
