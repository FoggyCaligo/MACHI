from pathlib import Path


ALLOWED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".md", ".markdown", ".txt", ".rst",
    ".yaml", ".yml", ".toml",
    ".ini", ".sql", ".html", ".css",
}

EXCLUDED_DIR_NAMES = {
    ".git", ".venv", "node_modules", "dist", "build",
    "__pycache__", ".next", "coverage",
}


def is_allowed_file(path: Path) -> bool:
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return False

    for part in path.parts:
        if part in EXCLUDED_DIR_NAMES:
            return False

    return True
