from datetime import datetime, timedelta, timezone

from config import GENERAL_RETENTION_DAYS
from memory.db import connection_context
from memory.stores.correction_store import CorrectionStore
from memory.stores.episode_store import EpisodeStore
from memory.stores.profile_store import ProfileStore


class RetentionPolicy:
    def __init__(self) -> None:
        self.correction_store = CorrectionStore()
        self.episode_store = EpisodeStore()
        self.profile_store = ProfileStore()

    def run(self) -> None:
        self.correction_store.trim_active_queue(keep=5)
        self._transition_episodes()
        self._trim_profiles()
        self._purge_old_general_records()

    def _transition_episodes(self) -> None:
        now = datetime.now(timezone.utc)
        with connection_context() as conn:
            rows = conn.execute("SELECT * FROM episodes WHERE pinned = 0 AND state != 'dropped'").fetchall()
            for row in rows:
                episode = dict(row)
                last_ref = episode['last_referenced_at'] or episode['created_at']
                last_dt = datetime.fromisoformat(last_ref)
                age = now - last_dt
                summary_text = (episode['summary'] or '').strip()
                is_fragment = len(summary_text) < 60

                if age >= timedelta(days=180) and is_fragment:
                    conn.execute("UPDATE episodes SET state = 'dropped' WHERE id = ?", (episode['id'],))
                elif age >= timedelta(days=90):
                    conn.execute("UPDATE episodes SET state = 'compressed' WHERE id = ?", (episode['id'],))

    def _trim_profiles(self) -> None:
        active = self.profile_store.get_active_profiles()
        topic_keys = {(row.get('topic_id'), row['topic']) for row in active}
        for topic_id, topic in topic_keys:
            self.profile_store.trim_history(topic=topic, topic_id=topic_id, keep_superseded=2)

    def _purge_old_general_records(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=GENERAL_RETENTION_DAYS)
        cutoff_iso = cutoff.isoformat()
        with connection_context() as conn:
            conn.execute("DELETE FROM profiles WHERE topic = 'general' AND updated_at < ?", (cutoff_iso,))
            conn.execute("DELETE FROM summaries WHERE topic = 'general' AND updated_at < ?", (cutoff_iso,))
            conn.execute("DELETE FROM corrections WHERE topic = 'general' AND created_at < ?", (cutoff_iso,))
            conn.execute("DELETE FROM episodes WHERE topic = 'general' AND created_at < ? AND pinned = 0", (cutoff_iso,))
