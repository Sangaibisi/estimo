"""Repository guards (S1-4): provider-SDK isolation and open-core path hygiene.

These run in CI on every PR. The detector itself is also tested against planted
violations, so the guard failing to fire is a test failure too.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The one module allowed to speak to the LLM endpoint (ADR-0001). The `openai` package
# is permitted there strictly as the OpenAI-compatible protocol client.
GATEWAY_PREFIX = "packages/gateway/"

FORBIDDEN_SDKS = (
    "openai",
    "anthropic",
    "litellm",
    "cohere",
    "mistralai",
    "groq",
    "together",
    "google.genai",
    "google.generativeai",
)

_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(" + "|".join(re.escape(s) for s in FORBIDDEN_SDKS) + r")\b",
    re.MULTILINE,
)
# Namespace-package form: `from google import genai` evades the dotted pattern above.
_GOOGLE_NAMESPACE_RE = re.compile(
    r"^\s*from\s+google\s+import\s+[^\n]*\b(genai|generativeai)\b", re.MULTILINE
)


def tracked_files(pattern: str | None = None) -> list[str]:
    args = ["git", "ls-files"] + ([pattern] if pattern else [])
    out = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


def find_sdk_imports(source: str) -> list[str]:
    hits = [match.group(1) for match in _IMPORT_RE.finditer(source)]
    hits += [f"google.{m.group(1)}" for m in _GOOGLE_NAMESPACE_RE.finditer(source)]
    return hits


class TestProviderSdkGuard:
    def test_detector_fires_on_planted_violation(self) -> None:
        planted = "import os\nfrom anthropic import Anthropic\nimport openai\n"
        assert find_sdk_imports(planted) == ["anthropic", "openai"]

    def test_detector_ignores_lookalikes(self) -> None:
        benign = "import openai_guard_docs\nfrom mypkg.openai_utils import x\n"
        assert find_sdk_imports(benign) == []

    def test_detector_catches_namespace_package_form(self) -> None:
        planted = "from google import genai\n"
        assert find_sdk_imports(planted) == ["google.genai"]

    def test_no_provider_sdk_outside_gateway(self) -> None:
        """The gateway is exempt for `openai` ONLY (protocol client, ADR-0001) — an
        `anthropic` import inside the gateway is still a violation."""
        violations: list[str] = []
        for path in tracked_files("*.py"):
            in_gateway = path.startswith(GATEWAY_PREFIX)
            hits = find_sdk_imports((REPO_ROOT / path).read_text(encoding="utf-8"))
            violations.extend(
                f"{path}: {sdk}" for sdk in hits if not (in_gateway and sdk == "openai")
            )
        assert not violations, "provider SDK imports violating ADR-0001: " + ", ".join(violations)


class TestOpenCorePathGuard:
    def test_no_ee_or_enterprise_paths(self) -> None:
        """AGENTS §2.9: never copy code from open-core ee//enterprise/ trees — and never
        create such trees here, so provenance stays unambiguous."""
        flagged = [
            path
            for path in tracked_files()
            if any(part in {"ee", "enterprise"} for part in Path(path).parts[:-1])
        ]
        assert not flagged, f"forbidden open-core-style paths: {flagged}"
