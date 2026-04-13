from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

# 언어별 구분자 매핑
_LANG_SEPARATORS: dict[str, list[str]] = {
    ".py":   ["\nclass ", "\ndef ", "\n\n", "\n", " ", ""],
    ".js":   ["\nfunction ", "\nclass ", "\nconst ", "\n\n", "\n", " ", ""],
    ".ts":   ["\nfunction ", "\nclass ", "\nconst ", "\ninterface ", "\n\n", "\n", " ", ""],
    ".jsx":  ["\nfunction ", "\nclass ", "\nconst ", "\n\n", "\n", " ", ""],
    ".tsx":  ["\nfunction ", "\nclass ", "\nconst ", "\ninterface ", "\n\n", "\n", " ", ""],
    ".sql":  ["\n-- ", "\nCREATE ", "\nSELECT ", "\n\n", "\n", " ", ""],
    ".md":   ["\n## ", "\n### ", "\n\n", "\n", " ", ""],
    ".html": ["\n<", "\n\n", "\n", " ", ""],
}
_DEFAULT_SEPARATORS = ["\n\n", "\n", " ", ""]

_CHUNK_SIZE    = 1200   # characters
_CHUNK_OVERLAP = 200    # characters


def chunk_text(content: str, file_ext: str = "") -> list[dict]:
    """
    RecursiveCharacterTextSplitter 기반 청킹.
    반환값은 기존 chunk_text_by_lines()와 동일한 스키마:
      { chunk_index, start_line, end_line, content }
    """
    if not content:
        return []

    separators = _LANG_SEPARATORS.get(file_ext.lower(), _DEFAULT_SEPARATORS)

    splitter = RecursiveCharacterTextSplitter(
        separators=separators,
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
        length_function=len,
        is_separator_regex=False,
    )

    raw_chunks = splitter.split_text(content)
    if not raw_chunks:
        return []

    # start_line / end_line 계산
    # content 전체에서 각 chunk text의 위치를 찾아 줄 번호로 변환
    result: list[dict] = []
    search_start = 0

    for idx, chunk_text_val in enumerate(raw_chunks):
        pos = content.find(chunk_text_val, search_start)
        if pos == -1:
            # fallback: overlap 때문에 못 찾는 경우 처음부터 재탐색
            pos = content.find(chunk_text_val)
        if pos == -1:
            start_line = 1
            end_line = content.count("\n") + 1
        else:
            start_line = content[:pos].count("\n") + 1
            end_line   = start_line + chunk_text_val.count("\n")
            # 다음 탐색은 현재 chunk 시작 이후부터 (overlap 허용)
            search_start = pos + max(1, len(chunk_text_val) - _CHUNK_OVERLAP)

        result.append(
            {
                "chunk_index": idx,
                "start_line":  start_line,
                "end_line":    end_line,
                "content":     chunk_text_val,
            }
        )

    return result


# 하위 호환: project_ingest_service.py가 기존 함수명으로 호출하는 경우 대비
def chunk_text_by_lines(content: str, file_ext: str = "", **_kwargs) -> list[dict]:
    return chunk_text(content, file_ext=file_ext)