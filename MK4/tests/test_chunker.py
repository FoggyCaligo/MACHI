import unittest

from project_analysis.injest.chunker import (
    _CHUNK_OVERLAP,
    _CHUNK_SIZE,
    chunk_text,
    chunk_text_by_lines,
)


class ChunkerTests(unittest.TestCase):
    def test_prefers_configured_separators_before_hard_cut(self) -> None:
        cases = [
            (".py", "\nclass Next:\n    pass\n"),
            (".ts", "\ninterface Shape {\n  kind: string;\n}\n"),
            (".md", "\n## Section\nBody\n"),
        ]

        for file_ext, separator in cases:
            with self.subTest(file_ext=file_ext):
                content = ("a" * 1000) + separator + ("b" * 500)
                chunks = chunk_text(content, file_ext=file_ext)

                self.assertGreaterEqual(len(chunks), 2)
                self.assertLess(len(chunks[0]["content"]), _CHUNK_SIZE)
                self.assertEqual(chunks[0]["content"], content[: len(chunks[0]["content"])])

    def test_falls_back_to_hard_cut_without_separator(self) -> None:
        content = "x" * (_CHUNK_SIZE + 50)
        chunks = chunk_text(content)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]["content"]), _CHUNK_SIZE)
        self.assertEqual(chunks[1]["content"], content[_CHUNK_SIZE - _CHUNK_OVERLAP :])

    def test_overlap_progress_does_not_create_empty_chunks(self) -> None:
        content = "0123456789" * 400
        chunks = chunk_text(content)

        self.assertEqual(len(chunks), 4)
        self.assertTrue(all(chunk["content"] for chunk in chunks))
        self.assertEqual([chunk["chunk_index"] for chunk in chunks], list(range(len(chunks))))

    def test_line_numbers_stay_self_consistent(self) -> None:
        content = "\n".join(f"line {idx}" for idx in range(1, 260))
        chunks = chunk_text(content, file_ext=".md")

        total_lines = content.count("\n") + 1
        self.assertGreaterEqual(len(chunks), 2)

        for chunk in chunks:
            self.assertEqual(
                chunk["end_line"],
                chunk["start_line"] + chunk["content"].count("\n"),
            )
            self.assertGreaterEqual(chunk["start_line"], 1)
            self.assertLessEqual(chunk["end_line"], total_lines)

    def test_wrapper_remains_compatible(self) -> None:
        content = ("a" * 1000) + "\nclass Next:\n    pass\n" + ("b" * 500)
        self.assertEqual(
            chunk_text_by_lines(content, file_ext=".py"),
            chunk_text(content, file_ext=".py"),
        )


if __name__ == "__main__":
    unittest.main()
