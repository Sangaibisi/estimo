"""Code-shelf eval (S5-6): known change scenarios over the meridyen-mini fixture repo."""

from pathlib import Path

import pytest
from estimo_code import (
    CodeGraph,
    generate_module_wikis,
    impact_for,
    parse_repo,
    render_repo_map,
)

from estimo_core import Confidence, EvidenceRef

REPO = Path(__file__).resolve().parents[3] / "fixtures" / "repo" / "meridyen-mini"


@pytest.fixture(scope="module")
def graph() -> CodeGraph:
    return CodeGraph.build(REPO, repo="meridyen-mini", commit="fixture")


class TestParsing:
    def test_parses_java_and_typescript(self) -> None:
        files = parse_repo(REPO)
        languages = {f.language for f in files}
        assert languages == {"java", "typescript", "tsx"}
        assert len(files) == 10

    def test_symbols_carry_docs_and_lines(self, graph: CodeGraph) -> None:
        service = next(
            s
            for f in graph.files
            for s in f.symbols
            if s.name == "InstallmentService" and s.kind == "class"
        )
        assert service.doc is not None and "Taksit" in service.doc
        assert service.start_line > 1


class TestImpact:
    def test_installment_plan_scenario(self, graph: CodeGraph) -> None:
        impacts = impact_for(graph, "Kampanya bazlı taksit planı desteği eklenmelidir")
        by_module = {i.module: i for i in impacts}
        assert by_module["campaign-engine"].confidence is Confidence.HIGH
        assert by_module["billing-core"].confidence is Confidence.HIGH
        for impact in impacts:
            for uri in impact.evidence_uris:
                EvidenceRef.from_uri(uri)  # must be valid evidence URIs (S5-5)

    def test_dealer_eligibility_scenario(self, graph: CodeGraph) -> None:
        impacts = impact_for(graph, "Bayi kanalında uygunluk sorgusu geliştirilecek")
        by_module = {i.module: i for i in impacts}
        assert by_module["dealer-portal"].confidence is Confidence.HIGH

    def test_accounting_scenario_uses_synonyms(self, graph: CodeGraph) -> None:
        impacts = impact_for(graph, "Muhasebe sistemine günlük rapor gönderilmeli")
        assert any(
            i.module == "integration-hub" and i.confidence is Confidence.HIGH for i in impacts
        )

    def test_unknown_text_yields_low_or_empty_with_discovery(self, graph: CodeGraph) -> None:
        impacts = impact_for(graph, "Blockchain tabanlı sadakat puanı takası")
        assert all(i.confidence is Confidence.LOW for i in impacts)
        assert all(i.discovery_suggested for i in impacts)


class TestRepoMap:
    def test_budget_respected_and_modules_present(self, graph: CodeGraph) -> None:
        full = render_repo_map(graph, token_budget=4000)
        assert "billing-core" in full and "InstallmentService" in full
        tiny = render_repo_map(graph, token_budget=60)
        assert "token budget reached" in tiny
        assert len(tiny) < len(full)


class TestModuleWikis:
    async def test_deterministic_pages(self, graph: CodeGraph) -> None:
        pages = await generate_module_wikis(graph)
        assert {p.module for p in pages} == {
            "billing-core",
            "campaign-engine",
            "crm-suite",
            "dealer-portal",
            "integration-hub",
        }
        billing = next(p for p in pages if p.module == "billing-core")
        assert "## Interfaces" in billing.text
        assert "InstallmentService" in billing.text
        assert billing.source_ref.startswith("repo://meridyen-mini@fixture/")


class TestS5ReviewRegressions:
    def test_prefix_bridge_requires_full_base(self, graph: CodeGraph) -> None:
        """kampüs must NOT bridge to campaign; kampanyalı must."""
        impacts = impact_for(graph, "Kampüs lokasyon listesi güncellenecek")
        assert not any(
            i.module == "campaign-engine" and i.confidence is Confidence.HIGH for i in impacts
        )
        inflected = impact_for(graph, "Kampanyalı satış akışı düzenlenecek")
        assert any(
            i.module == "campaign-engine" and i.confidence is Confidence.HIGH for i in inflected
        )

    def test_tsx_and_arrow_functions_extracted(self, graph: CodeGraph) -> None:
        names = {s.name for f in graph.files for s in f.symbols}
        assert "CampaignBanner" in names
        assert "publishOrderStatusFeed" in names
        banner = next(s for f in graph.files for s in f.symbols if s.name == "CampaignBanner")
        assert banner.doc is not None and "taksit" in banner.doc.lower()

    def test_symlink_outside_root_is_ignored(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.java"
        outside.write_text("public class Secret {}", encoding="utf-8")
        repo_root = tmp_path / "repo" / "mod"
        repo_root.mkdir(parents=True)
        (repo_root / "Ok.java").write_text("public class Ok {}", encoding="utf-8")
        (repo_root / "Leak.java").symlink_to(outside)
        parsed = parse_repo(tmp_path / "repo")
        assert [f.path for f in parsed] == ["mod/Ok.java"]
