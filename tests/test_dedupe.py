"""Dedupe-key stability for the signals + ledger pipelines.

If these keys flip across whitespace / capitalization / minor
formatting changes, re-ingesting the same source produces duplicate
rows — exactly what dedupe is supposed to prevent.
"""
from __future__ import annotations

import unittest
from datetime import date

from services.signal_collectors.persistence import _dedupe_key as signal_key
from services.reimbursement_api.ledger_loader import _hash_row


class SignalDedupeTest(unittest.TestCase):
    def test_identical_inputs_same_key(self) -> None:
        a = signal_key("https://example.com/agenda", "Council action", date(2026, 5, 1))
        b = signal_key("https://example.com/agenda", "Council action", date(2026, 5, 1))
        self.assertEqual(a, b)

    def test_case_difference_collapses(self) -> None:
        a = signal_key("https://example.com/agenda", "Council action", date(2026, 5, 1))
        b = signal_key("https://example.com/agenda", "COUNCIL ACTION", date(2026, 5, 1))
        self.assertEqual(a, b)

    def test_punctuation_difference_collapses(self) -> None:
        a = signal_key("https://example.com/agenda", "Council Action: MUD", date(2026, 5, 1))
        b = signal_key("https://example.com/agenda", "Council Action - MUD", date(2026, 5, 1))
        self.assertEqual(a, b)

    def test_url_difference_changes_key(self) -> None:
        a = signal_key("https://example.com/agenda", "Council action", date(2026, 5, 1))
        b = signal_key("https://example.com/agenda2", "Council action", date(2026, 5, 1))
        self.assertNotEqual(a, b)

    def test_date_difference_changes_key(self) -> None:
        a = signal_key("https://example.com/agenda", "Council action", date(2026, 5, 1))
        b = signal_key("https://example.com/agenda", "Council action", date(2026, 6, 1))
        self.assertNotEqual(a, b)


class LedgerDedupeTest(unittest.TestCase):
    @staticmethod
    def _row(**overrides: object) -> dict[str, object]:
        base = {
            "posted_on": "2026-04-15",
            "vendor": "ACME Engineering",
            "invoice_number": "INV-1001",
            "description": "Civil engineering — Phase 1",
            "amount": "12345.67",
            "gl_account": "5100-Engineering",
        }
        base.update(overrides)
        return base

    def test_identical_rows_hash_same(self) -> None:
        a = _hash_row("lavon-pilot", self._row())
        b = _hash_row("lavon-pilot", self._row())
        self.assertEqual(a, b)

    def test_different_deal_slugs_hash_differently(self) -> None:
        a = _hash_row("lavon-pilot", self._row())
        b = _hash_row("celina-deal", self._row())
        self.assertNotEqual(a, b)

    def test_amount_change_hashes_differently(self) -> None:
        a = _hash_row("lavon-pilot", self._row())
        b = _hash_row("lavon-pilot", self._row(amount="9999.99"))
        self.assertNotEqual(a, b)

    def test_description_change_hashes_differently(self) -> None:
        a = _hash_row("lavon-pilot", self._row())
        b = _hash_row("lavon-pilot", self._row(description="Civil engineering — Phase 2"))
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
