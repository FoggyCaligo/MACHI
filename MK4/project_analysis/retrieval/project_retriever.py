import re

from project_analysis.stores.project_file_store import ProjectFileStore
from project_analysis.stores.project_chunk_store import ProjectChunkStore


class ProjectRetriever:
    def __init__(self) -> None:
        self.project_file_store = ProjectFileStore()
        self.project_chunk_store = ProjectChunkStore()

    def _normalize(self, text: str) -> str:
        return (text or "").strip().lower()

    def _tokenize(self, text: str) -> list[str]:
        """
        한글/영문/숫자 토큰을 단순 추출한다.
        너무 짧은 토큰과 흔한 불용어는 제거한다.
        """
        text = self._normalize(text)
        raw_tokens = re.findall(r"[가-힣a-zA-Z0-9_]+", text)

        stopwords = {
            "이", "그", "저", "것", "수", "등", "더", "좀", "잘", "관련",
            "파일", "코드", "부분", "문제", "구조", "설명", "분석", "개선",
            "what", "how", "why", "the", "and", "for", "with", "from",
            "this", "that", "are", "was", "were", "is", "to", "of", "in",
        }

        tokens = []
        for token in raw_tokens:
            if len(token) <= 1:
                continue
            if token in stopwords:
                continue
            tokens.append(token)

        return list(dict.fromkeys(tokens))

    def _path_bonus(self, question: str, file_path: str) -> float:
        q = self._normalize(question)
        p = self._normalize(file_path)

        bonus = 0.0

        # 구조 질문
        if any(word in q for word in ["구조", "책임", "분리", "아키텍처", "흐름"]):
            if any(key in p for key in ["readme", "api", "route", "orchestrator", "service", "store", "retriev"]):
                bonus += 3.0

        # 버그/에러 질문
        if any(word in q for word in ["버그", "오류", "에러", "예외", "실패", "빈 응답"]):
            if any(key in p for key in ["orchestrator", "agent", "client", "builder", "retriev", "store"]):
                bonus += 3.0

        # 리팩토링 질문
        if any(word in q for word in ["리팩토링", "중복", "개선", "정리", "나눠", "분리"]):
            if any(key in p for key in ["service", "store", "builder", "retriev", "policy", "agent"]):
                bonus += 2.5

        # 설정/실행 질문
        if any(word in q for word in ["실행", "설정", "config", "환경", "배포"]):
            if any(key in p for key in ["config", "api", "main", "app", "yaml", "toml", "json"]):
                bonus += 2.5

        return bonus

    def _score_chunk(self, question: str, file_path: str, chunk_content: str) -> float:
        question_tokens = self._tokenize(question)
        if not question_tokens:
            return 0.0

        norm_path = self._normalize(file_path)
        norm_content = self._normalize(chunk_content)

        score = 0.0

        for token in question_tokens:
            if token in norm_path:
                score += 4.0
            if token in norm_content:
                score += 2.0

        score += self._path_bonus(question, file_path)

        # chunk 앞부분 가중치 약간
        if norm_content.startswith(("def ", "class ", "from ", "import ")):
            score += 0.3

        return score

    def retrieve(self, project_id: str, question: str, top_k: int = 5) -> list[dict]:
        files = self.project_file_store.list_by_project(project_id)
        file_map = {f["id"]: f for f in files}

        chunks = self.project_chunk_store.list_by_project(project_id)

        scored = []
        for chunk in chunks:
            file_info = file_map.get(chunk["file_id"])
            if not file_info:
                continue

            file_path = file_info["path"]
            content = chunk["content"] or ""

            if not content.strip():
                continue

            score = self._score_chunk(
                question=question,
                file_path=file_path,
                chunk_content=content,
            )

            if score <= 0:
                continue

            scored.append(
                {
                    "file_id": file_info["id"],
                    "file_path": file_path,
                    "chunk_id": chunk["id"],
                    "chunk_index": chunk["chunk_index"],
                    "start_line": chunk["start_line"],
                    "end_line": chunk["end_line"],
                    "content": content,
                    "score": score,
                }
            )

        scored.sort(key=lambda x: (-x["score"], x["file_path"], x["chunk_index"]))
        return scored[:top_k]