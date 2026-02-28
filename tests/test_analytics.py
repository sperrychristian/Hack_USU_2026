"""
test_analytics.py

This file contains unit tests for the analytics module.

I wrote these tests to verify that:
1. The summary calculations behave correctly in edge cases.
2. Language aggregation logic correctly counts and sorts languages.

I am using Python’s built-in unittest framework to keep the testing
structure simple and explicit.
"""

import unittest
from analytics import compute_summary, top_languages


class TestAnalytics(unittest.TestCase):
    """
    This test class validates the behavior of functions
    inside analytics.py.

    Each test method checks a specific behavior or edge case.
    """

    def test_compute_summary_empty(self):
        """
        This test verifies that compute_summary() handles an empty list safely.

        Rationale:
        If the GitHub API returns no repositories (e.g., new user,
        private account, or error case), the function should not crash.
        Instead, it should return zero values.

        I am specifically checking:
        - repo_count
        - total_stars
        - active_30d (recent activity metric)

        This ensures defensive programming for edge cases.
        """

        summary = compute_summary([])

        # I expect zero repositories
        self.assertEqual(summary["repo_count"], 0)

        # No repos means no stars
        self.assertEqual(summary["total_stars"], 0)

        # No repos means no recent activity
        self.assertEqual(summary["active_30d"], 0)


    def test_top_languages_counts(self):
        """
        This test verifies that top_languages() correctly:
        1. Counts occurrences of each language
        2. Ignores None values
        3. Sorts results by highest count first

        Instead of calling the GitHub API, I construct mock
        repository dictionaries that simulate API responses.
        """

        # Simulated GitHub API response structure
        repos = [
            {"language": "Python"},
            {"language": "Python"},
            {"language": "JavaScript"},
            {"language": None}  # GitHub sometimes returns None
        ]

        # Request the top languages (limit 10 for this test)
        langs = top_languages(repos, n=10)

        """
        Expected result:

        Python → 2 repos
        JavaScript → 1 repo

        Since Python has the highest frequency,
        it should appear first in the list.
        """

        # First entry should be Python with count 2
        self.assertEqual(langs[0]["language"], "Python")
        self.assertEqual(langs[0]["repo_count"], 2)

        # Second entry should be JavaScript with count 1
        self.assertEqual(langs[1]["language"], "JavaScript")
        self.assertEqual(langs[1]["repo_count"], 1)


# This allows the test file to be run directly from the command line:
# python test_analytics.py
if __name__ == "__main__":
    unittest.main()