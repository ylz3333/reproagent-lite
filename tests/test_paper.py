"""Tests for deterministic paper extraction and optional model enrichment."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from reproagent_lite import llm, paper
from reproagent_lite.paper import PageText


class PaperTests(unittest.TestCase):
    """Ensure candidates retain evidence and model output stays constrained."""

    def test_pages_from_text_uses_one_indexed_form_feed_pages(self) -> None:
        pages = paper.pages_from_text("first page\fsecond page")
        self.assertEqual(pages, [PageText(1, "first page"), PageText(2, "second page")])

    def test_claim_candidates_keep_page_evidence(self) -> None:
        pages = [
            PageText(1, "Introduction. The benchmark was first published in 2021."),
            PageText(2, "Table 2\nAdult test set\nOur method obtains AUC 0.913 ± 0.006."),
        ]
        draft = paper.find_claim_candidates(pages, "Adult AUC")
        self.assertAlmostEqual(draft.candidate_values[0], 0.913)
        self.assertEqual(draft.evidence[0].page, 2)
        self.assertEqual(draft.evidence[0].table, "Table 2")
        self.assertNotIn(2021.0, draft.candidate_values)

    def test_unrelated_pages_are_not_searched(self) -> None:
        pages = [
            PageText(3, "AUC for another dataset is 0.99."),
            PageText(4, "Adult preprocessing details are provided without a result."),
        ]
        draft = paper.find_claim_candidates(pages, "Adult AUC")
        self.assertEqual(draft.candidate_values, ())

    def test_write_claim_draft_emits_json(self) -> None:
        draft = paper.find_claim_candidates(
            [PageText(2, "Table 3. Adult AUC = 0.913")], "Adult AUC"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = paper.write_claim_draft(draft, Path(directory) / "claim.json")
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertAlmostEqual(payload["candidate_values"][0], 0.913)
        self.assertEqual(payload["evidence"][0]["page"], 2)

    def test_pdf_dependency_error_is_clear(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fixture")
            missing = ModuleNotFoundError("No module named 'pymupdf'", name="pymupdf")
            with mock.patch.object(paper.importlib, "import_module", side_effect=missing):
                with self.assertRaisesRegex(paper.PDFDependencyError, r"reproagent-lite\[pdf\]"):
                    paper.extract_pdf_pages(pdf_path)


class _FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class _FakeClient:
    def __init__(self, output_text: str) -> None:
        self.responses = _FakeResponses(output_text)


class LLMTests(unittest.TestCase):
    def test_responses_api_can_be_injected(self) -> None:
        client = _FakeClient(
            '```json\n{"target_hint":"Adult AUC","metric":"AUC",'
            '"reported_value":0.913,"unit":null,"evidence":[],"unresolved_fields":[]}\n```'
        )
        result = llm.enrich_claim_draft(
            [PageText(2, "Adult AUC is 0.913")],
            "Adult AUC",
            model="test-model",
            client=client,
        )
        self.assertAlmostEqual(float(result["reported_value"]), 0.913)
        self.assertEqual(client.responses.calls[0]["model"], "test-model")

    def test_model_configuration_is_required(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(llm.LLMConfigurationError, "OPENAI_MODEL"):
                llm.enrich_claim_draft(
                    [PageText(1, "AUC 0.8")], "AUC", client=_FakeClient("{}")
                )

    def test_non_json_output_is_rejected(self) -> None:
        with self.assertRaisesRegex(llm.LLMResponseError, "valid JSON"):
            llm.enrich_claim_draft(
                [PageText(1, "AUC 0.8")],
                "AUC",
                model="test-model",
                client=_FakeClient("AUC is 0.8"),
            )


if __name__ == "__main__":
    unittest.main()
