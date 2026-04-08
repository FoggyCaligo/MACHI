from memory.stores.profile_store import ProfileStore
from memory.stores.correction_store import CorrectionStore
from memory.stores.episode_store import EpisodeStore
from memory.stores.summary_store import SummaryStore
from memory.stores.raw_message_store import RawMessageStore


class RecallRetriever:
    def __init__(self) -> None:
        self.profile_store = ProfileStore()
        self.correction_store = CorrectionStore()
        self.episode_store = EpisodeStore()
        self.summary_store = SummaryStore()
        self.raw_message_store = RawMessageStore()

    def _clip_text(self, text: str | None, max_len: int = 220) -> str:
        if not text:
            return ""
        text = " ".join(str(text).strip().split())
        if len(text) > max_len:
            return text[:max_len].rstrip() + "..."
        return text

    def _build_impacts(
        self,
        corrections: list[dict],
        profiles: list[dict],
        summaries: list[dict],
    ) -> list[str]:
        impacts: list[str] = []

        for correction in corrections:
            topic = correction.get("topic") or "general"
            content = self._clip_text(correction.get("content"), max_len=180)
            impacts.append(f"정정 반영: [{topic}] {content}")

        for profile in profiles:
            topic = profile.get("topic") or "general"
            content = self._clip_text(profile.get("content"), max_len=180)
            impacts.append(f"현재 프로필: [{topic}] {content}")

        for summary in summaries:
            topic = summary.get("topic") or "general"
            content = self._clip_text(summary.get("content"), max_len=180)
            impacts.append(f"요약 기억: [{topic}] {content}")

        return impacts

    def _build_trace_block(self, rows: list[dict], include_status: bool = False) -> list[dict]:
        trace: list[dict] = []

        for row in rows:
            item = {
                "id": row.get("id"),
                "topic": row.get("topic"),
                "content": self._clip_text(
                    row.get("content") or row.get("summary"),
                    max_len=220,
                ),
                "created_at": row.get("created_at") or row.get("updated_at"),
            }
            if include_status:
                item["status"] = row.get("status")
            trace.append(item)

        return trace

    def _build_episode_trace(self, episodes: list[dict]) -> list[dict]:
        trace: list[dict] = []

        for episode in episodes:
            trace.append(
                {
                    "id": episode.get("id"),
                    "topic": episode.get("topic"),
                    "summary": self._clip_text(episode.get("summary"), max_len=220),
                    "raw_ref": self._clip_text(episode.get("raw_ref"), max_len=220),
                    "created_at": episode.get("created_at"),
                    "last_referenced_at": episode.get("last_referenced_at"),
                    "state": episode.get("state"),
                }
            )

        return trace

    def _fallback_raw_expansions(
        self,
        query: str,
        episodes: list[dict],
        corrections: list[dict],
        profiles: list[dict],
        summaries: list[dict],
    ) -> list[dict]:
        expansions: list[dict] = []
        seen_anchor_ids: set[str] = set()

        candidates: list[tuple[str, str]] = []

        for episode in episodes:
            if episode.get("raw_ref"):
                candidates.append(("episode.raw_ref", str(episode["raw_ref"])))
            if episode.get("summary"):
                candidates.append(("episode.summary", str(episode["summary"])))

        for correction in corrections:
            if correction.get("content"):
                candidates.append(("correction.content", str(correction["content"])))

        for profile in profiles:
            if profile.get("content"):
                candidates.append(("profile.content", str(profile["content"])))

        for summary in summaries:
            if summary.get("content"):
                candidates.append(("summary.content", str(summary["content"])))

        for match_basis, text in candidates:
            hits = self.raw_message_store.find_context_by_anchor_text(
                anchor_text=text,
                limit=1,
                before=2,
                after=2,
                match_type="anchor_fallback",
            )
            for hit in hits:
                anchor_id = str(hit.get("anchor_message", {}).get("id") or "")
                if not anchor_id or anchor_id in seen_anchor_ids:
                    continue
                seen_anchor_ids.add(anchor_id)
                hit["match_basis"] = match_basis
                hit["query"] = query
                expansions.append(hit)
                if len(expansions) >= 3:
                    return expansions

        return expansions

    def retrieve(self, query: str) -> dict:
        episodes = self.episode_store.find_relevant(query, limit=3)
        corrections = self.correction_store.search(query, limit=3)
        profiles = self.profile_store.search(query, limit=3)
        summaries = self.summary_store.search(query, limit=2)

        for episode in episodes:
            if episode.get("id"):
                self.episode_store.reference(episode["id"])

        found = bool(episodes or corrections or profiles or summaries)
        episode_summary = [self._clip_text(e.get("summary"), max_len=220) for e in episodes] if episodes else []
        time_context = [e["created_at"] for e in episodes if e.get("created_at")] if episodes else []

        impacts = self._build_impacts(
            corrections=corrections,
            profiles=profiles,
            summaries=summaries,
        )

        raw_expansions = self.raw_message_store.search_with_context(
            query=query,
            limit=2,
            before=2,
            after=2,
        )

        if not raw_expansions and found:
            raw_expansions = self._fallback_raw_expansions(
                query=query,
                episodes=episodes,
                corrections=corrections,
                profiles=profiles,
                summaries=summaries,
            )

        raw_available = bool(raw_expansions)

        return {
            "found": found,
            "episode_summary": episode_summary or None,
            "time_context": time_context or None,
            "impact_on_current_understanding": impacts or None,
            "raw_available": raw_available,
            "raw_expansions": raw_expansions or None,
            "trace": {
                "episodes": self._build_episode_trace(episodes),
                "corrections": self._build_trace_block(corrections, include_status=True),
                "profiles": self._build_trace_block(profiles, include_status=True),
                "summaries": self._build_trace_block(summaries),
            },
        }