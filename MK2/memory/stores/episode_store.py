import json
import uuid
from typing import Any

from memory.db import connection_context, utc_now
from memory.stores.topic_store import TopicStore
from tools.text_embedding import cosine_similarity, embed_text


class EpisodeStore:
    def __init__(self) -> None:
        self.topic_store = TopicStore()

    def _resolve_topic_id(self, *, topic: str | None = None, topic_id: str | None = None, create_if_missing: bool = False) -> str | None:
        if topic_id:
            return topic_id
        if not topic or str(topic).strip().lower() == "general":
            return None
        if create_if_missing:
            return self.topic_store.ensure_topic(topic, source="episode_store", confidence=0.6)
        return self.topic_store.find_exact_topic_id(topic)

    def _base_select(self) -> str:
        return (
            "SELECT e.*, t.name AS topic_name, t.summary AS topic_summary "
            "FROM episodes e LEFT JOIN topics t ON e.topic_id = t.id"
        )

    def create_episode(self, topic: str, summary: str, raw_ref: str | None = None, importance: float = 0.5, topic_id: str | None = None):
        episode_id = str(uuid.uuid4())
        now = utc_now()
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=True)
        
        # Compute embedding for semantic search
        embedding = embed_text(summary, kind="passage")
        embedding_json = json.dumps(embedding, ensure_ascii=False)
        
        with connection_context() as conn:
            conn.execute(
                """
                INSERT INTO episodes (id, topic_id, summary, raw_ref, importance, last_referenced_at, created_at, state, pinned, embedding_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, ?)
                """,
                (episode_id, resolved_topic_id, summary, raw_ref, importance, now, now, embedding_json),
            )
        return episode_id

    def reference(self, episode_id: str):
        with connection_context() as conn:
            conn.execute(
                "UPDATE episodes SET last_referenced_at = ? WHERE id = ?",
                (utc_now(), episode_id),
            )

    def find_relevant(self, query: str, limit: int = 5):
        """Find relevant episodes using semantic similarity (embedding-based).
        
        Ranking factors (in order):
        1. Semantic similarity (cosine of query embedding vs episode embedding)
        2. Pinned status
        3. Importance score
        4. Last referenced time
        """
        # Compute query embedding
        query_embedding = embed_text(query, kind="passage")
        
        # Load all active episodes
        with connection_context() as conn:
            rows = conn.execute(
                f"{self._base_select()} WHERE e.state != 'dropped' ORDER BY e.created_at DESC LIMIT 100",
            ).fetchall()
        
        if not rows:
            return []
        
        # Rank by semantic similarity + contextual signals
        scored: list[dict] = []
        for row in rows:
            row_dict = dict(row)
            embedding_json = row_dict.get("embedding_json")
            
            if embedding_json:
                try:
                    episode_embedding = json.loads(embedding_json)
                    similarity = cosine_similarity(query_embedding, episode_embedding)
                except (json.JSONDecodeError, TypeError):
                    similarity = 0.0
            else:
                similarity = 0.0
            
            # Combine signals: similarity (0.6 weight) + contextual (0.4 weight)
            pinned = float(row_dict.get("pinned") or 0)
            importance = float(row_dict.get("importance") or 0.5)
            
            # Contextual score: (pinned * 2 + importance) / 3
            contextual_score = (pinned * 2.0 + importance) / 3.0
            
            # Final score: weighted combination
            final_score = (similarity * 0.6) + (contextual_score * 0.4)
            
            scored.append({
                **row_dict,
                "_similarity": similarity,
                "_contextual_score": contextual_score,
                "_final_score": final_score,
            })
        
        # Sort by final score descending
        scored.sort(key=lambda x: x["_final_score"], reverse=True)
        
        # Return top-k, removing internal scoring fields
        result = []
        for item in scored[:limit]:
            clean_item = {k: v for k, v in item.items() if not k.startswith("_")}
            result.append(clean_item)
        
        return result

    def get_recent(self, limit: int = 5):
        with connection_context() as conn:
            rows = conn.execute(
                f"{self._base_select()} WHERE e.state != 'dropped' ORDER BY e.created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_compressed(self, episode_id: str):
        with connection_context() as conn:
            conn.execute("UPDATE episodes SET state = 'compressed' WHERE id = ? AND pinned = 0", (episode_id,))

    def mark_dropped(self, episode_id: str):
        with connection_context() as conn:
            conn.execute("UPDATE episodes SET state = 'dropped' WHERE id = ? AND pinned = 0", (episode_id,))

    def transition_state(self):
        return None
