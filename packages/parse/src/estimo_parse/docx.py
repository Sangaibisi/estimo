"""DOCX loading via Docling's MsWord backend, flattened into a light block IR.

Deliberately bypasses `docling.document_converter`: that module unconditionally imports
the full PDF chain (docling-parse), which we do not ship (ADR-0005 scope discipline —
the slim install carries only convert-core + format-docx + pypdfium2). Revisit if
docling makes converter imports lazy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from docling.backend.msword_backend import MsWordDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import InputDocument
from docling_core.types.doc.items.table.table import TableItem

BlockKind = Literal["title", "heading", "paragraph", "list_item", "table"]


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    level: int
    index: int
    heading_trail: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()


def load_blocks(path: Path) -> list[Block]:
    in_doc = InputDocument(
        path_or_stream=path,
        format=InputFormat.DOCX,
        backend=MsWordDocumentBackend,
        filename=path.name,
    )
    if not in_doc.valid:
        msg = f"not a readable .docx file: {path}"
        raise ValueError(msg)
    doc = MsWordDocumentBackend(in_doc, path).convert()

    blocks: list[Block] = []
    trail: list[str] = []
    for index, (item, level) in enumerate(doc.iterate_items()):
        label = str(getattr(item, "label", ""))
        if isinstance(item, TableItem):
            data = item.data
            grid: list[tuple[str, ...]] = []
            for r in range(data.num_rows):
                grid.append(
                    tuple(
                        next(
                            (
                                c.text.strip()
                                for c in data.table_cells
                                if c.start_row_offset_idx == r and c.start_col_offset_idx == col
                            ),
                            "",
                        )
                        for col in range(data.num_cols)
                    )
                )
            blocks.append(
                Block(
                    kind="table",
                    text="",
                    level=level,
                    index=index,
                    heading_trail=tuple(trail),
                    rows=tuple(grid),
                )
            )
            continue

        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        if label == "title":
            blocks.append(Block(kind="title", text=text, level=level, index=index))
            continue
        if label == "section_header":
            # Maintain the heading trail by section level.
            while trail and len(trail) >= level - 1:
                trail.pop()
            trail.append(text)
            blocks.append(
                Block(
                    kind="heading",
                    text=text,
                    level=level,
                    index=index,
                    heading_trail=tuple(trail),
                )
            )
            continue
        kind: BlockKind = "list_item" if label == "list_item" else "paragraph"
        blocks.append(
            Block(kind=kind, text=text, level=level, index=index, heading_trail=tuple(trail))
        )
    return blocks
