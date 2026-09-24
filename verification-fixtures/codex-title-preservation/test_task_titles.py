import unittest

from task_titles import title_from_line


class TitleFromLineTests(unittest.TestCase):
    def test_lf_is_removed(self) -> None:
        self.assertEqual(title_from_line("Review the invoice\n"), "Review the invoice")

    def test_crlf_is_removed(self) -> None:
        self.assertEqual(
            title_from_line("Review the invoice\r\n"), "Review the invoice"
        )

    def test_line_without_newline_is_unchanged(self) -> None:
        self.assertEqual(title_from_line("Review the invoice"), "Review the invoice")


if __name__ == "__main__":
    unittest.main()
