from __future__ import annotations

import re


_FILE_MUTATION_REQUEST_PATTERNS = (
    re.compile(
        r"(?:파일|코드|html|css|js|javascript|typescript|python|문서).{0,30}"
        r"(?:수정|변경|고쳐|바꿔|추가|삭제|제거|없애|작성|만들|적용|반영|rename|이름)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:수정|변경|고쳐|바꿔|추가|삭제|제거|없애|작성|만들|적용|반영).{0,30}"
        r"(?:파일|코드|html|css|js|javascript|typescript|python|문서)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:edit|modify|update|change|remove|delete|add|create|write|rename)\b.{0,40}"
        r"\b(?:file|code|html|css|javascript|typescript|python|document)\b",
        re.IGNORECASE,
    ),
)


def requires_file_mutation(user_message: str) -> bool:
    """Return True when the user is asking MK4 to change project/file contents."""
    normalized = " ".join(str(user_message or "").split())
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _FILE_MUTATION_REQUEST_PATTERNS)


def _successful_file_mutations(tool_history: list[dict]) -> list[tuple[int, str, str]]:
    mutations: list[tuple[int, str, str]] = []
    for index, event in enumerate(tool_history):
        tool = str(event.get("tool") or "")
        result = event.get("result")
        arguments = event.get("arguments")

        if (
            tool in {"file_create", "file_update", "file_delete"}
            and isinstance(result, dict)
            and result.get("ok") is True
        ):
            path = ""
            if isinstance(arguments, dict):
                path = str(arguments.get("path") or "").strip()
            mutations.append((index, tool, path))
            continue

        if (
            tool == "terminal_command"
            and isinstance(result, dict)
            and result.get("filesystem_changed") is True
        ):
            changed_paths = result.get("changed_paths")
            if isinstance(changed_paths, list) and changed_paths:
                for changed_path in changed_paths:
                    mutations.append((index, tool, str(changed_path or "").strip()))
            else:
                mutations.append((index, tool, ""))
    return mutations


def _has_verification_after_mutation(
    *,
    tool_history: list[dict],
    mutation_index: int,
    mutation_path: str,
) -> bool:
    for event in tool_history[mutation_index + 1 :]:
        if event.get("tool") != "file_read":
            continue
        result = event.get("result")
        if not isinstance(result, dict) or result.get("ok") is not True:
            continue
        read_path = str(result.get("path") or "").strip()
        if not mutation_path or not read_path or read_path == mutation_path:
            return True
    return False


def file_mutation_completion_guard_result(
    *,
    user_message: str,
    tool_history: list[dict],
    rejected_final_answer: str,
) -> dict | None:
    """Require mutation evidence and post-mutation verification before file-edit completion."""
    if not requires_file_mutation(user_message):
        return None

    mutations = _successful_file_mutations(tool_history)
    if not mutations:
        return {
            "ok": False,
            "error": "requested_file_mutation_not_performed",
            "message": (
                "The user requested a file/code change, but no successful file mutation has occurred. "
                "Do not answer with a plan or claim completion. Inspect as needed, then call file_update, "
                "file_create, file_delete, or a verified filesystem-changing tool."
            ),
            "rejected_final_answer": rejected_final_answer,
        }

    mutation_index, mutation_tool, mutation_path = mutations[-1]
    if mutation_tool == "file_delete":
        return None

    if _has_verification_after_mutation(
        tool_history=tool_history,
        mutation_index=mutation_index,
        mutation_path=mutation_path,
    ):
        return None

    return {
        "ok": False,
        "error": "requested_file_mutation_not_verified",
        "message": (
            "A requested file change succeeded, but the changed file has not been read after the mutation. "
            "Verify the current file contents with file_read before returning a final answer."
        ),
        "path": mutation_path,
        "rejected_final_answer": rejected_final_answer,
    }
