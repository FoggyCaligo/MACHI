from __future__ import annotations

# Transitional shared lexical resources.
# These are centralized to avoid duplicated drift across files.
# Long-term, passage/evidence selection should rely primarily on embeddings/model judgment.
FIRST_PERSON_MARKERS = {
    "나는", "내가", "나의", "저는", "제가", "저의", "i am", "i'm", "my ",
}

PREFERENCE_MARKERS = {
    "좋아", "싫어", "선호", "원한다", "바란다", "중요", "필요", "need",
    "기준", "습관", "성향", "생각", "판단", "prefer", "want", "important",
    "habit", "style",
}
