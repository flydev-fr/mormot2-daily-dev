from __future__ import annotations

import datetime
import pathlib
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_commits  # noqa: E402


class CalendarEditionTests(unittest.TestCase):
    def test_default_is_last_closed_zagreb_day(self):
        now = datetime.datetime(2026, 10, 14, 7, 30,
                                tzinfo=datetime.timezone.utc)
        self.assertEqual(
            fetch_commits.default_edition(now, "Europe/Zagreb"),
            "2026-10-13",
        )

    def test_bounds_follow_daylight_saving_time(self):
        self.assertEqual(
            fetch_commits.edition_bounds("2026-03-29", "Europe/Zagreb"),
            ("2026-03-28T23:00:00Z", "2026-03-29T22:00:00Z"),
        )
        self.assertEqual(
            fetch_commits.edition_bounds("2026-10-25", "Europe/Zagreb"),
            ("2026-10-24T22:00:00Z", "2026-10-25T23:00:00Z"),
        )


class GitGraphSelectionTests(unittest.TestCase):
    @mock.patch("fetch_commits.api_get")
    def test_compare_returns_every_newly_reachable_commit(self, api_get):
        commits = [{"sha": f"sha-{i:03d}"} for i in range(40)]
        api_get.return_value = {
            "status": "ahead",
            "ahead_by": 40,
            "total_commits": 40,
            "commits": commits,
        }

        result = fetch_commits.compare_commit_shas("base", "head", 60)

        self.assertEqual(result, [commit["sha"] for commit in commits])
        api_get.assert_called_once_with(
            f"/repos/{fetch_commits.UPSTREAM}/compare/base...head",
            {"per_page": 100, "page": 1},
        )

    @mock.patch("fetch_commits.api_get")
    def test_compare_fails_instead_of_truncating_busy_day(self, api_get):
        api_get.return_value = {
            "status": "ahead",
            "ahead_by": 61,
            "total_commits": 61,
            "commits": [],
        }

        with self.assertRaisesRegex(RuntimeError, "above MAX_COMMITS"):
            fetch_commits.compare_commit_shas("base", "head", 60)


class PayloadChangeTests(unittest.TestCase):
    def test_generation_time_alone_does_not_trigger_a_commit(self):
        previous = {"generated_at": "2026-10-14T05:00:00Z", "commits": [{"sha": "a"}]}
        current = {"generated_at": "2026-10-14T06:00:00Z", "commits": [{"sha": "a"}]}
        self.assertFalse(fetch_commits.payload_changed(previous, current))

    def test_removing_a_wrongly_grouped_commit_triggers_a_commit(self):
        previous = {"commits": [{"sha": "a"}, {"sha": "wrong-day"}]}
        current = {"commits": [{"sha": "a"}]}
        self.assertTrue(fetch_commits.payload_changed(previous, current))


if __name__ == "__main__":
    unittest.main()
