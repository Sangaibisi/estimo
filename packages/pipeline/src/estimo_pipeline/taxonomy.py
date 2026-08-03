"""Ontology-guided module attribution (S4-2).

v0 is the deterministic floor: Turkish keyword → module mapping over the Aurora
taxonomy (fixtures/README.md). The optional LLM refinement can add tags but never
removes the deterministic ones. Telco eTOM/SID labels ride along as optional metadata.
"""

from __future__ import annotations

from estimo_core import tr_lower

# Ordered: the first matching group provides the PRIMARY module.
MODULE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("campaign-engine", ("kampanya", "taksit planı", "komisyon")),
    ("dealer-portal", ("bayi",)),
    ("crm-suite", ("çağrı merkezi", "müşteri temsilcisi", "crm", "maliyet merkezi")),
    ("selfcare-web", ("selfcare", "online kanal", "web kanal")),
    ("payment-adapter", ("ödeme", "kredi kartı", "tahsilat")),
    ("invoice-render", ("pdf", "şablon", "fatura üst bilgi")),
    ("product-catalog", ("katalog", "paket")),
    ("integration-hub", ("entegrasyon", "api", "muhasebe", "sms", "bildirim", "raporlan")),
    ("billing-core", ("fatura", "taksit", "bakiye", "tarife", "ücret")),
)

AURORA_MODULES: frozenset[str] = frozenset(module for module, _ in MODULE_KEYWORDS)


def modules_for(text: str) -> tuple[str, ...]:
    """All matching modules, primary first; empty when nothing matches (flagged upstream)."""
    lowered = tr_lower(text)
    matches = [
        module
        for module, keywords in MODULE_KEYWORDS
        if any(keyword in lowered for keyword in keywords)
    ]
    return tuple(matches)
