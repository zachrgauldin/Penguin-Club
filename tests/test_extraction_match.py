"""Source-ref overlap matcher and date-pairing logic for Agent 3.

The kill-switch invariant rests on this matcher — a critical date is
canonical only when both extraction passes agree on value AND
source_ref overlaps. Regressions here silently let mismatched
extractions through.
"""
from __future__ import annotations

import unittest
from datetime import date

from services.sharepoint_watcher.extraction import _source_overlap, match_dates
from services.sharepoint_watcher.schemas import ContractExtraction, ExtractedDate


def _date(kind: str, value: date, source: str, *, critical: bool = False) -> ExtractedDate:
    return ExtractedDate(
        kind=kind,  # type: ignore[arg-type]
        label=f"test-{kind}",
        value=value,
        source_ref=source,
        is_critical=critical,
        confidence=0.9,
    )


def _ce(*dates: ExtractedDate) -> ContractExtraction:
    return ContractExtraction(
        contract_kind="psa",
        counterparty="Test",
        counterparty_tier=None,
        title="test",
        effective_date=None,
        dates=list(dates),
        obligations=[],
        takedown_schedule=None,
    )


class SourceOverlapTest(unittest.TestCase):
    def test_identical_strings_overlap(self) -> None:
        self.assertTrue(_source_overlap("p. 12, §4.3(b)", "p. 12, §4.3(b)"))

    def test_page_number_only_overlap(self) -> None:
        self.assertTrue(_source_overlap("p. 12, §4.3(b)", "p. 12, Section 4.3(b)"))

    def test_substring_form_overlaps(self) -> None:
        self.assertTrue(_source_overlap("p. 12, §4.3", "p. 12, §4.3(b)"))

    def test_different_pages_no_overlap(self) -> None:
        self.assertFalse(_source_overlap("p. 12, §4.3", "p. 18, §4.3"))

    def test_empty_does_not_overlap(self) -> None:
        self.assertFalse(_source_overlap("", "p. 12"))
        self.assertFalse(_source_overlap("p. 12", ""))
        self.assertFalse(_source_overlap(None, "p. 12"))


class MatchDatesTest(unittest.TestCase):
    def test_both_passes_agree_value_and_source(self) -> None:
        a = _ce(_date("closing", date(2026, 6, 1), "p. 8, §3.2", critical=True))
        b = _ce(_date("closing", date(2026, 6, 1), "p. 8, §3.2(a)", critical=True))
        rows = match_dates(a, b)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].agreed)
        self.assertEqual(rows[0].value, date(2026, 6, 1))

    def test_value_match_source_disagree_not_agreed(self) -> None:
        a = _ce(_date("closing", date(2026, 6, 1), "p. 8, §3.2", critical=True))
        b = _ce(_date("closing", date(2026, 6, 1), "p. 18, §3.2", critical=True))
        rows = match_dates(a, b)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].agreed)
        self.assertIsNone(rows[0].value)

    def test_unmatched_pass_a_lands_alone(self) -> None:
        a = _ce(_date("closing", date(2026, 6, 1), "p. 8, §3.2", critical=True))
        b = _ce()
        rows = match_dates(a, b)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].agreed)
        self.assertEqual(rows[0].extraction_a_value, date(2026, 6, 1))
        self.assertIsNone(rows[0].extraction_b_value)

    def test_unmatched_pass_b_lands_alone(self) -> None:
        a = _ce()
        b = _ce(_date("closing", date(2026, 6, 1), "p. 8, §3.2", critical=True))
        rows = match_dates(a, b)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].agreed)
        self.assertIsNone(rows[0].extraction_a_value)
        self.assertEqual(rows[0].extraction_b_value, date(2026, 6, 1))

    def test_value_disagreement_produces_two_unmatched_rows(self) -> None:
        a = _ce(_date("closing", date(2026, 6, 1), "p. 8, §3.2", critical=True))
        b = _ce(_date("closing", date(2026, 7, 1), "p. 8, §3.2", critical=True))
        rows = match_dates(a, b)
        self.assertEqual(len(rows), 2)
        self.assertFalse(any(r.agreed for r in rows))


if __name__ == "__main__":
    unittest.main()
