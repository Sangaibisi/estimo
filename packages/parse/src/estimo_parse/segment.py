"""Requirement segmentation over the block IR.

Extraction ladder (most to least structured):
1. `coded` — list items / paragraphs carrying an explicit code (`G-01: …`).
2. `table` — requirement tables (a header cell matching 'gereksinim'), with acceptance
   criteria captured when a 'kabul' column exists.
3. `heuristic` — modal-verb sentence candidates, only when 1+2 find nothing (messy,
   e-mail-style BRDs).

IDs are stable across re-parses: derived from the source code when present
(`REQ-G-01`), else from a content hash (`REQ-H1A2B3C4D`).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from estimo_core import AnchorFlag, Requirement
from estimo_parse import ambiguity
from estimo_parse.anchors import detect_anchors
from estimo_parse.docx import Block, load_blocks
from estimo_parse.models import ParsedBrd

_CODE_RE = re.compile(r"^\s*([A-ZÇĞİÖŞÜ]{1,5}-\d{1,4})\s*[:.\-–]\s*(.+)$", re.DOTALL)
# Compared against the UPPERCASE capture directly (no IGNORECASE: the İ/i casefold trap).
_NON_REQ_LABEL_PREFIXES = {"EK", "NOT", "SSS", "REV", "TABLO", "ŞEKİL"}
_EXCLUDED_SECTION_RE = re.compile(r"varsayım|kısıt|onay|imza|revizyon|versiyon", re.IGNORECASE)
# Exact-ish header: accepts "Gereksinim(ler)", "Gereksinim Açıklaması/Tanımı/Metni";
# rejects "Gereksinim Sahibi", "İlgili Gereksinim", caption rows.
_REQ_TABLE_HEADER_RE = re.compile(
    r"^\s*gereksinim(?:ler)?(?:\s+(?:açıklamas[ıi]|tan[ıi]m[ıi]|metni))?\s*$", re.IGNORECASE
)
_ACCEPTANCE_HEADER_RE = re.compile(r"kabul", re.IGNORECASE)
_OPEN_POINT_RE = re.compile(
    r"[^.]*(?:netleştirilecek|belirlenecek|karar verilecek|toplantıda konuş)[^.]*\.?",
    re.IGNORECASE,
)
_HEURISTIC_RE = re.compile(
    r"(malıdır|melidir|malı\b|meli\b|görünsün|lazım|gerekiyor|istiyoruz|"
    r"beklentimiz|olmalı|güncellenmeli|açılması gerek|sağlanmalı|yansıtılmalı)",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ])")


def _slug_id(code: str) -> str:
    normalized = unicodedata.normalize("NFKD", code)
    ascii_code = "".join(ch for ch in normalized if ch.isascii() and (ch.isalnum() or ch == "-"))
    return f"REQ-{ascii_code.upper()}"


def _hash_id(text: str) -> str:
    digest = hashlib.sha1(" ".join(text.lower().split()).encode()).hexdigest()
    return f"REQ-H{digest[:8].upper()}"


def _source_ref(block: Block) -> str:
    trail = " > ".join(block.heading_trail) or "(root)"
    return f"block#{block.index} @ {trail}"


def _in_excluded_section(block: Block) -> bool:
    return any(_EXCLUDED_SECTION_RE.search(h) for h in block.heading_trail)


def _finalize(req: Requirement) -> Requirement:
    score, issues = ambiguity.rule_score(req)
    return req.model_copy(update={"ambiguity_score": score, "ambiguity_issues": issues})


def _coded_requirements(blocks: list[Block]) -> list[Requirement]:
    found: list[Requirement] = []
    for block in blocks:
        if block.kind not in ("list_item", "paragraph"):
            continue
        match = _CODE_RE.match(block.text)
        if match is None or _in_excluded_section(block):
            continue
        code, text = match.group(1), " ".join(match.group(2).split())
        if code.rsplit("-", 1)[0] in _NON_REQ_LABEL_PREFIXES:
            # Annex/note/figure labels are not requirements — and must not starve the
            # heuristic rung by making the document look "coded".
            continue
        found.append(
            _finalize(
                Requirement(
                    id=_slug_id(code),
                    text=text,
                    source_ref=_source_ref(block),
                    extraction="coded",
                    anchors=detect_anchors(text),
                )
            )
        )
    return found


def _table_requirements(blocks: list[Block]) -> list[Requirement]:
    found: list[Requirement] = []
    for block in blocks:
        if block.kind != "table" or not block.rows or _in_excluded_section(block):
            continue
        header = block.rows[0]
        req_col = next(
            (i for i, cell in enumerate(header) if _REQ_TABLE_HEADER_RE.search(cell)), None
        )
        if req_col is None:
            continue
        acc_col = next(
            (i for i, cell in enumerate(header) if _ACCEPTANCE_HEADER_RE.search(cell)), None
        )
        for row in block.rows[1:]:
            text = " ".join(row[req_col].split())
            if not text:
                continue
            code_cell = row[0].strip()
            code_match = _CODE_RE.match(f"{code_cell}: x")
            use_code = (
                code_match is not None
                and code_cell.rsplit("-", 1)[0] not in _NON_REQ_LABEL_PREFIXES
            )
            req_id = _slug_id(code_cell) if use_code else _hash_id(text)
            acceptance = (
                " ".join(row[acc_col].split()) if acc_col is not None and row[acc_col] else None
            )
            found.append(
                _finalize(
                    Requirement(
                        id=req_id,
                        text=text,
                        source_ref=_source_ref(block),
                        extraction="table",
                        acceptance_criteria=acceptance,
                        anchors=detect_anchors(text),
                    )
                )
            )
    return found


def _heuristic_requirements(blocks: list[Block]) -> list[Requirement]:
    found: list[Requirement] = []
    seen: set[str] = set()
    for block in blocks:
        if block.kind not in ("paragraph", "list_item") or _in_excluded_section(block):
            continue
        for sentence in _SENTENCE_SPLIT_RE.split(block.text):
            sentence = " ".join(sentence.split()).strip()
            if len(sentence) < 15 or not _HEURISTIC_RE.search(sentence):
                continue
            req_id = _hash_id(sentence)
            if req_id in seen:
                continue
            seen.add(req_id)
            found.append(
                _finalize(
                    Requirement(
                        id=req_id,
                        text=sentence,
                        source_ref=_source_ref(block),
                        extraction="heuristic",
                        anchors=detect_anchors(sentence),
                    )
                )
            )
    return found


def _doc_meta(blocks: list[Block]) -> dict[str, str]:
    for block in blocks:
        if block.kind == "heading":
            break
        if block.kind == "table" and block.rows and len(block.rows[0]) == 2:
            return {row[0].strip(): row[1].strip() for row in block.rows if row[0].strip()}
    return {}


def parse_brd(path: Path) -> ParsedBrd:
    blocks = load_blocks(path)

    title = next((b.text for b in blocks if b.kind == "title"), path.stem)
    meta = _doc_meta(blocks)
    brd_ref = meta.get("Doküman No") or meta.get("Talep No") or path.stem

    # Merge the structured rungs by ID: the table copy (carrying acceptance criteria)
    # wins over a coded restatement; duplicates within one rung collapse. Insertion
    # order is preserved, so IDs stay document-ordered and stable.
    merged: dict[str, Requirement] = {}
    for req in _coded_requirements(blocks) + _table_requirements(blocks):
        prev = merged.get(req.id)
        if prev is None or (req.acceptance_criteria and not prev.acceptance_criteria):
            merged[req.id] = req
    requirements = list(merged.values())
    if not requirements:
        requirements = _heuristic_requirements(blocks)

    doc_anchors: list[AnchorFlag] = []
    open_points: list[str] = []
    for block in blocks:
        if block.kind == "table":
            texts = [cell for row in block.rows for cell in row if cell.strip()]
        elif block.kind in ("paragraph", "list_item", "title", "heading"):
            texts = [block.text]
        else:
            continue
        for text in texts:
            for anchor in detect_anchors(text):
                if not any(a.snippet == anchor.snippet for a in doc_anchors):
                    doc_anchors.append(anchor)
            for match in _OPEN_POINT_RE.finditer(text):
                point = " ".join(match.group(0).split())
                if point not in open_points:
                    open_points.append(point)

    return ParsedBrd(
        brd_ref=brd_ref,
        title=title,
        source_file=path.name,
        meta=meta,
        requirements=tuple(requirements),
        doc_anchors=tuple(doc_anchors),
        open_points=tuple(open_points),
        headings=tuple(b.text for b in blocks if b.kind == "heading"),
        table_count=sum(1 for b in blocks if b.kind == "table"),
    )
