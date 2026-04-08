def chunk_text_by_lines(content: str, lines_per_chunk: int = 120, overlap: int = 20) -> list[dict]:
    lines = content.splitlines()

    if not lines:
        return []

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(lines):
        end = min(start + lines_per_chunk, len(lines))
        chunk_lines = lines[start:end]

        chunks.append(
            {
                "chunk_index": chunk_index,
                "start_line": start + 1,
                "end_line": end,
                "content": "\n".join(chunk_lines),
            }
        )

        if end >= len(lines):
            break

        start = max(end - overlap, start + 1)
        chunk_index += 1

    return chunks