_LANG_SEPARATORS: dict[str, list[str]] = {
    ".py": ["\nclass ", "\ndef ", "\n\n", "\n", " ", ""],
    ".js": ["\nfunction ", "\nclass ", "\nconst ", "\n\n", "\n", " ", ""],
    ".ts": ["\nfunction ", "\nclass ", "\nconst ", "\ninterface ", "\n\n", "\n", " ", ""],
    ".jsx": ["\nfunction ", "\nclass ", "\nconst ", "\n\n", "\n", " ", ""],
    ".tsx": ["\nfunction ", "\nclass ", "\nconst ", "\ninterface ", "\n\n", "\n", " ", ""],
    ".sql": ["\n-- ", "\nCREATE ", "\nSELECT ", "\n\n", "\n", " ", ""],
    ".md": ["\n## ", "\n### ", "\n\n", "\n", " ", ""],
    ".html": ["\n<", "\n\n", "\n", " ", ""],
}
_DEFAULT_SEPARATORS = ["\n\n", "\n", " ", ""]

_CHUNK_SIZE = 1200
_CHUNK_OVERLAP = 200
_MIN_SEPARATOR_SPLIT_DISTANCE = _CHUNK_OVERLAP + 1


def _separator_cut_index(text: str, *, start: int, hard_end: int, separators: list[str]) -> int:
    search_start = min(start + 1, len(text))
    min_cut = start + _MIN_SEPARATOR_SPLIT_DISTANCE

    for separator in separators:
        if not separator:
            continue
        cut = text.rfind(separator, search_start, hard_end + 1)
        if cut < min_cut:
            continue
        return cut

    return hard_end


def _split_text(text: str, *, separators: list[str]) -> list[str]:
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        hard_end = min(start + _CHUNK_SIZE, text_len)
        if hard_end >= text_len:
            final_chunk = text[start:text_len]
            if final_chunk:
                chunks.append(final_chunk)
            break

        end = _separator_cut_index(text, start=start, hard_end=hard_end, separators=separators)
        if end <= start:
            end = hard_end

        chunk = text[start:end]
        if not chunk:
            end = hard_end
            chunk = text[start:end]

        chunks.append(chunk)

        next_start = max(end - _CHUNK_OVERLAP, start + 1)
        if next_start <= start:
            next_start = start + 1
        start = next_start

    return chunks


def _build_chunk_rows(content: str, raw_chunks: list[str]) -> list[dict]:
    result: list[dict] = []
    search_start = 0

    for idx, chunk_text_val in enumerate(raw_chunks):
        pos = content.find(chunk_text_val, search_start)
        if pos == -1:
            pos = content.find(chunk_text_val)

        if pos == -1:
            start_line = 1
            end_line = content.count("\n") + 1
        else:
            start_line = content[:pos].count("\n") + 1
            end_line = start_line + chunk_text_val.count("\n")
            search_start = pos + max(1, len(chunk_text_val) - _CHUNK_OVERLAP)

        result.append(
            {
                "chunk_index": idx,
                "start_line": start_line,
                "end_line": end_line,
                "content": chunk_text_val,
            }
        )

    return result


def chunk_text(content: str, file_ext: str = "") -> list[dict]:
    if not content:
        return []

    separators = _LANG_SEPARATORS.get(file_ext.lower(), _DEFAULT_SEPARATORS)
    raw_chunks = _split_text(content, separators=separators)
    return _build_chunk_rows(content, raw_chunks)


def chunk_text_by_lines(content: str, file_ext: str = "", **_kwargs) -> list[dict]:
    return chunk_text(content, file_ext=file_ext)
