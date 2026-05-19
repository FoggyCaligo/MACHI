from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import config

ANCHOR_USER = "anchor:user"
ANCHOR_ASSISTANT = "anchor:assistant"
KO_PARTICLES = ("으로부터", "에게서", "으로서", "으로써", "까지", "부터", "에게", "한테", "께", "에서", "으로", "로", "은", "는", "이", "가", "을", "를", "와", "과", "도", "만", "의", "에")
EDGE_PUNCT = " \t\r\n.,!?;:'\"“”‘’()[]{}<>"
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+\-./#]*|[가-힣]{2,}")
EmbedFn = Callable[[str], Awaitable[list[float]]]
SearchFn = Callable[[str], Awaitable[str | None]]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_text(token: str) -> str:
    value = unicodedata.normalize("NFC", token).strip().lower().strip(EDGE_PUNCT)
    for particle in KO_PARTICLES:
        if len(value) > len(particle) + 1 and value.endswith(particle):
            stripped = value[: -len(particle)]
            if len(stripped) >= 2:
                return stripped
    return value


def compute_hash(token: str) -> str:
    return hashlib.sha256(f"word::{normalize_text(token)}".encode("utf-8")).hexdigest()[:32]


@dataclass
class Node:
    address_hash: str
    node_kind: str = "concept"
    formation_source: str = "ingest"
    labels: list[str] = field(default_factory=list)
    is_abstract: bool = False
    trust_score: float = 0.5
    stability_score: float = 0.5
    is_active: bool = True
    embedding: list[float] | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def primary_label(self) -> str:
        return self.labels[0] if self.labels else self.address_hash[:8]

    def touch(self) -> None:
        self.updated_at = utcnow()


@dataclass
class Edge:
    edge_id: str
    source_hash: str
    target_hash: str
    edge_family: str = "concept"
    connect_type: str = "neutral"
    proposed_connect_type: str | None = None
    provenance_source: str = "thought"
    proposal_reason: str | None = None
    support_count: int = 0
    conflict_count: int = 0
    contradiction_pressure: float = 0.0
    trust_score: float = 0.5
    edge_weight: float = 0.5
    translation_confidence: float | None = None
    is_active: bool = True
    is_temporary: bool = False
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def touch(self) -> None:
        self.updated_at = utcnow()


@dataclass
class WordEntry:
    word_id: str
    surface_form: str
    address_hash: str
    language: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class LocalSubgraph:
    center_hash: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    hop_radius: int = 0


@dataclass
class ConceptPointer:
    address_hash: str
    label: str
    local_subgraph: LocalSubgraph | None = None
    confidence: float = 1.0
    importance: float = 1.0
    is_direct_input_match: bool = True


@dataclass
class EmptySlot:
    concept_hint: str
    importance: float = 1.0
    unfound: bool = True


ConceptRef = ConceptPointer | EmptySlot


@dataclass
class TranslatedEdge:
    source_ref: ConceptRef
    target_ref: ConceptRef
    edge_family: str = "concept"
    connect_type: str = "neutral"
    confidence: float = 0.5
    proposed_connect_type: str | None = None


@dataclass
class TranslatedGraph:
    nodes: list[ConceptRef]
    edges: list[TranslatedEdge]
    source: str
    near_refs: list[ConceptRef] = field(default_factory=list)
    far_refs: list[ConceptRef] = field(default_factory=list)


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (address_hash TEXT PRIMARY KEY,node_kind TEXT NOT NULL,formation_source TEXT NOT NULL,labels_json TEXT NOT NULL,is_abstract INTEGER NOT NULL,trust_score REAL NOT NULL,stability_score REAL NOT NULL,is_active INTEGER NOT NULL,embedding_json TEXT,payload_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS edges (edge_id TEXT PRIMARY KEY,source_hash TEXT NOT NULL,target_hash TEXT NOT NULL,edge_family TEXT NOT NULL,connect_type TEXT NOT NULL,proposed_connect_type TEXT,provenance_source TEXT NOT NULL,proposal_reason TEXT,support_count INTEGER NOT NULL,conflict_count INTEGER NOT NULL,contradiction_pressure REAL NOT NULL,trust_score REAL NOT NULL,edge_weight REAL NOT NULL,translation_confidence REAL,is_active INTEGER NOT NULL,is_temporary INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS words (word_id TEXT PRIMARY KEY,surface_form TEXT NOT NULL,address_hash TEXT NOT NULL,language TEXT,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_words_surface ON words(surface_form);
CREATE INDEX IF NOT EXISTS idx_words_hash ON words(address_hash);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_hash);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_hash);
"""


def open_db(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def close_db(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None, default: Any) -> Any:
    return json.loads(value) if value else default


def _iso(value: datetime) -> str:
    return value.isoformat()


def _node(row) -> Node | None:
    if row is None:
        return None
    return Node(row["address_hash"], row["node_kind"], row["formation_source"], _loads(row["labels_json"], []), bool(row["is_abstract"]), float(row["trust_score"]), float(row["stability_score"]), bool(row["is_active"]), _loads(row["embedding_json"], None), _loads(row["payload_json"], {}), datetime.fromisoformat(row["created_at"]), datetime.fromisoformat(row["updated_at"]))


def _edge(row) -> Edge | None:
    if row is None:
        return None
    return Edge(row["edge_id"], row["source_hash"], row["target_hash"], row["edge_family"], row["connect_type"], row["proposed_connect_type"], row["provenance_source"], row["proposal_reason"], int(row["support_count"]), int(row["conflict_count"]), float(row["contradiction_pressure"]), float(row["trust_score"]), float(row["edge_weight"]), row["translation_confidence"], bool(row["is_active"]), bool(row["is_temporary"]), datetime.fromisoformat(row["created_at"]), datetime.fromisoformat(row["updated_at"]))


def insert_node(conn, node: Node) -> None:
    conn.execute("INSERT OR REPLACE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (node.address_hash, node.node_kind, node.formation_source, _j(node.labels), int(node.is_abstract), node.trust_score, node.stability_score, int(node.is_active), _j(node.embedding) if node.embedding is not None else None, _j(node.payload), _iso(node.created_at), _iso(node.updated_at)))


def update_node(conn, node: Node) -> None:
    insert_node(conn, node)


def get_node(conn, address_hash: str) -> Node | None:
    return _node(conn.execute("SELECT * FROM nodes WHERE address_hash=?", (address_hash,)).fetchone())


def get_active_nodes(conn, limit: int | None = None) -> list[Node]:
    sql = "SELECT * FROM nodes WHERE is_active=1 ORDER BY updated_at DESC" + (" LIMIT ?" if limit else "")
    rows = conn.execute(sql, (limit,) if limit else ()).fetchall()
    return [n for n in (_node(r) for r in rows) if n]


def insert_edge(conn, edge: Edge) -> None:
    conn.execute("INSERT OR REPLACE INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (edge.edge_id, edge.source_hash, edge.target_hash, edge.edge_family, edge.connect_type, edge.proposed_connect_type, edge.provenance_source, edge.proposal_reason, edge.support_count, edge.conflict_count, edge.contradiction_pressure, edge.trust_score, edge.edge_weight, edge.translation_confidence, int(edge.is_active), int(edge.is_temporary), _iso(edge.created_at), _iso(edge.updated_at)))


def update_edge(conn, edge: Edge) -> None:
    insert_edge(conn, edge)


def get_edge_by_endpoints(conn, source_hash: str, target_hash: str) -> Edge | None:
    return _edge(conn.execute("SELECT * FROM edges WHERE source_hash=? AND target_hash=? AND is_active=1 ORDER BY edge_weight DESC LIMIT 1", (source_hash, target_hash)).fetchone())


def get_edges_for_node(conn, address_hash: str) -> list[Edge]:
    rows = conn.execute("SELECT * FROM edges WHERE is_active=1 AND (source_hash=? OR target_hash=?)", (address_hash, address_hash)).fetchall()
    return [e for e in (_edge(r) for r in rows) if e]


def insert_word(conn, word: WordEntry) -> None:
    conn.execute("INSERT OR REPLACE INTO words VALUES (?, ?, ?, ?, ?)", (word.word_id, word.surface_form, word.address_hash, word.language, _iso(word.created_at)))


def get_word(conn, surface_form: str) -> WordEntry | None:
    row = conn.execute("SELECT * FROM words WHERE surface_form=? ORDER BY created_at DESC LIMIT 1", (surface_form,)).fetchone()
    return WordEntry(row["word_id"], row["surface_form"], row["address_hash"], row["language"], datetime.fromisoformat(row["created_at"])) if row else None


def word_link_exists(conn, surface_form: str, address_hash: str) -> bool:
    return conn.execute("SELECT 1 FROM words WHERE surface_form=? AND address_hash=? LIMIT 1", (surface_form, address_hash)).fetchone() is not None


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]


def extract_tokens(text: str) -> list[str]:
    return [normalize_text(m.group(0)) for m in TOKEN_RE.finditer(text)]


def tokenize(text: str) -> list[list[str]]:
    return [extract_tokens(s) for s in split_sentences(text)]


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def extract_subgraph(conn, center_hash: str, hop_radius: int | None = None, trust_threshold: float | None = None) -> LocalSubgraph:
    radius = config.LOCAL_GRAPH_N_HOP if hop_radius is None else hop_radius
    threshold = config.LOCAL_GRAPH_TRUST_THRESHOLD if trust_threshold is None else trust_threshold
    visited, nodes, edge_map = set(), [], {}
    q = deque([(center_hash, 0)])
    while q:
        h, depth = q.popleft()
        if h in visited:
            continue
        visited.add(h)
        node = get_node(conn, h)
        if not node or not node.is_active or (depth > 0 and node.trust_score < threshold):
            continue
        nodes.append(node)
        if depth >= radius:
            continue
        for edge in get_edges_for_node(conn, h):
            edge_map[edge.edge_id] = edge
            other = edge.target_hash if edge.source_hash == h else edge.source_hash
            q.append((other, depth + 1))
    return LocalSubgraph(center_hash, nodes, list(edge_map.values()), radius)


async def _resolve_token(token: str, conn, embed_fn: EmbedFn) -> ConceptRef:
    word = get_word(conn, token)
    if word:
        node = get_node(conn, word.address_hash)
        if node:
            return ConceptPointer(node.address_hash, node.primary_label(), extract_subgraph(conn, node.address_hash), 1.0)
    embedding = await embed_fn(token)
    candidates = [n for n in get_active_nodes(conn, config.LANG_TO_GRAPH_MAX_EMBEDDING_NODES) if n.embedding]
    score, node = max(((cosine(embedding, n.embedding), n) for n in candidates), default=(0.0, None), key=lambda x: x[0])
    if node and score >= config.LANG_TO_GRAPH_SIMILARITY_THRESHOLD:
        return ConceptPointer(node.address_hash, node.primary_label(), extract_subgraph(conn, node.address_hash), score, is_direct_input_match=False)
    return EmptySlot(token)


async def translate(text: str, conn, embed_fn: EmbedFn) -> TranslatedGraph:
    sentence_tokens = tokenize(text)
    flat = [t for s in sentence_tokens for t in s]
    refs = [await _resolve_token(t, conn, embed_fn) for t in flat]
    vectors = {t: await embed_fn(t) for t in dict.fromkeys(flat)}
    valid = [v for v in vectors.values() if v]
    if valid:
        centroid = [sum(v[i] for v in valid) / len(valid) for i in range(len(valid[0]))]
        scores = {t: cosine(vectors.get(t), centroid) for t in flat}
    else:
        scores = {t: float(len(t)) for t in flat}
    for ref in refs:
        label = ref.label if isinstance(ref, ConceptPointer) else ref.concept_hint
        ref.importance = scores.get(label, 0.0)
    ranked = sorted(refs, key=lambda r: r.importance, reverse=True)
    near_n = max(config.TOKEN_IMPORTANCE_MIN, math.ceil(len(ranked) * config.TOKEN_IMPORTANCE_NEAR_RATIO)) if ranked else 0
    far_n = math.ceil(len(ranked) * config.TOKEN_IMPORTANCE_FAR_RATIO) if ranked else 0
    near = ranked[:near_n]
    near_ids = {id(r) for r in near}
    far = [r for r in ranked[-far_n:] if id(r) not in near_ids] if far_n else []
    edges, cursor = [], 0
    for sentence in sentence_tokens:
        sent_refs = refs[cursor: cursor + len(sentence)]
        cursor += len(sentence)
        for left, right in zip(sent_refs, sent_refs[1:]):
            edges.append(TranslatedEdge(left, right, confidence=min(left.importance or 0.5, right.importance or 0.5) or 0.5))
    return TranslatedGraph(refs, edges, text, near, far)


@dataclass
class GraphDelta:
    added_nodes: set[str] = field(default_factory=set)
    added_edges: set[str] = field(default_factory=set)
    def is_empty(self) -> bool:
        return not self.added_nodes and not self.added_edges


class TempThoughtGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}
        self.empty_slots: list[EmptySlot] = []
        self.goal_hash: str | None = None
        self.delta = GraphDelta()
        self.all_added_node_hashes: set[str] = set()
        self.all_added_edge_ids: set[str] = set()

    def add_node(self, node: Node, committed: bool = False) -> None:
        existed = node.address_hash in self.nodes
        self.nodes[node.address_hash] = node
        if not committed and not existed:
            self.delta.added_nodes.add(node.address_hash)
            self.all_added_node_hashes.add(node.address_hash)

    def add_edge(self, edge: Edge, committed: bool = False) -> None:
        if edge.edge_id in self.edges:
            return
        self.edges[edge.edge_id] = edge
        if not committed:
            self.delta.added_edges.add(edge.edge_id)
            self.all_added_edge_ids.add(edge.edge_id)

    def set_goal_node(self, node: Node) -> None:
        self.goal_hash = node.address_hash
        self.add_node(node, committed=True)

    def load_from_translated(self, translated: TranslatedGraph) -> None:
        for ref in translated.nodes:
            if isinstance(ref, ConceptPointer) and ref.local_subgraph:
                for node in ref.local_subgraph.nodes:
                    self.add_node(node, committed=True)
                for edge in ref.local_subgraph.edges:
                    self.add_edge(edge, committed=True)
            elif isinstance(ref, EmptySlot):
                self.empty_slots.append(ref)

    def get_node(self, h: str) -> Node | None:
        return self.nodes.get(h)

    def all_nodes(self) -> list[Node]:
        return list(self.nodes.values())

    def get_edge(self, edge_id: str) -> Edge | None:
        return self.edges.get(edge_id)

    def all_edges(self) -> list[Edge]:
        return list(self.edges.values())

    def reset_delta(self) -> None:
        self.delta = GraphDelta()

    def fill_slot(self, slot: EmptySlot, node: Node) -> None:
        self.add_node(node)
        if slot in self.empty_slots:
            self.empty_slots.remove(slot)

    def connect_to_goal(self, concept_hash: str) -> None:
        if not self.goal_hash or self.goal_hash == concept_hash:
            return
        now = utcnow()
        self.add_edge(Edge(str(uuid.uuid4()), self.goal_hash, concept_hash, provenance_source="system", proposed_connect_type="goal_context", edge_weight=0.4, trust_score=0.4, created_at=now, updated_at=now))


@dataclass
class ConclusionView:
    nodes: list[Node]
    edges: list[Edge]
    goal_hash: str | None
    had_empty_slots: bool
    loop_count: int
    model: str | None = None
    user_input: str | None = None
    key_hashes: set[str] = field(default_factory=set)
    ref_hashes: set[str] = field(default_factory=set)
    search_node_hashes: set[str] = field(default_factory=set)
    topic_continuity: str = "new_topic"


def _ref_hash(ref: ConceptRef) -> str:
    return ref.address_hash if isinstance(ref, ConceptPointer) else compute_hash(ref.concept_hint)


class ThoughtEngine:
    def __init__(self, conn, embed_fn: EmbedFn, search_fn: SearchFn, goal_node: Node) -> None:
        self.conn, self.embed_fn, self.search_fn, self.goal_node = conn, embed_fn, search_fn, goal_node

    async def think(self, translated: TranslatedGraph, *, model: str | None = None, user_input: str | None = None, previous_key_hashes: set[str] | None = None) -> ConclusionView:
        tg = TempThoughtGraph()
        tg.set_goal_node(self.goal_node)
        for node in extract_subgraph(self.conn, self.goal_node.address_hash).nodes:
            tg.add_node(node, committed=True)
        tg.load_from_translated(translated)
        for ref in translated.nodes:
            if isinstance(ref, ConceptPointer):
                tg.connect_to_goal(ref.address_hash)
        seen = set()
        self._add_translated_edges(tg, translated.edges, seen)
        had_empty_slots = bool(tg.empty_slots)
        search_hashes, loops = set(), 0
        while tg.empty_slots and loops < config.THINK_MAX_LOOPS:
            loops += 1
            tg.reset_delta()
            search_hashes |= await self._fill_empty_slots(tg)
            self._add_translated_edges(tg, translated.edges, seen)
            if tg.delta.is_empty():
                break
        key_hashes = {_ref_hash(r) for r in translated.near_refs if tg.get_node(_ref_hash(r))}
        key_hashes |= {_ref_hash(r) for r in translated.nodes if isinstance(r, EmptySlot) and tg.get_node(_ref_hash(r))}
        ref_hashes = {_ref_hash(r) for r in translated.far_refs if tg.get_node(_ref_hash(r)) and _ref_hash(r) not in key_hashes}
        if previous_key_hashes:
            ref_hashes |= previous_key_hashes - key_hashes
        self._commit(tg)
        continuity = "new_topic" if not previous_key_hashes else ("continued_topic" if key_hashes & previous_key_hashes else "shifted_topic")
        return ConclusionView(tg.all_nodes(), tg.all_edges(), tg.goal_hash, had_empty_slots, loops, model, user_input, key_hashes, ref_hashes, search_hashes, continuity)

    def _add_translated_edges(self, tg: TempThoughtGraph, edges: list[TranslatedEdge], seen: set[tuple[str, str]]) -> None:
        for edge in edges:
            src, tgt = _ref_hash(edge.source_ref), _ref_hash(edge.target_ref)
            if src == tgt or (src, tgt) in seen or not tg.get_node(src) or not tg.get_node(tgt):
                continue
            seen.add((src, tgt))
            tg.add_edge(Edge(str(uuid.uuid4()), src, tgt, edge.edge_family, edge.connect_type, edge.proposed_connect_type, "lang_to_graph", edge_weight=edge.confidence, translation_confidence=edge.confidence))

    async def _fill_empty_slots(self, tg: TempThoughtGraph) -> set[str]:
        slots = sorted(tg.empty_slots, key=lambda s: s.importance, reverse=True)
        query = " ".join(s.concept_hint for s in slots[:3] if s.concept_hint.strip())
        try:
            search_text = await asyncio.wait_for(self.search_fn(query), timeout=config.SEARCH_TIMEOUT) if query else None
        except asyncio.TimeoutError:
            search_text = None
        nodes, search_hashes = [], set()
        for slot in list(slots):
            node = await self._node_from_slot(slot, search_text)
            tg.fill_slot(slot, node)
            tg.connect_to_goal(node.address_hash)
            nodes.append(node)
            if search_text:
                search_hashes.add(node.address_hash)
        for i, left in enumerate(nodes):
            for right in nodes[i + 1:]:
                tg.add_edge(Edge(str(uuid.uuid4()), left.address_hash, right.address_hash, proposed_connect_type="co_occurrence", provenance_source="search", proposal_reason="같은 입력/검색 맥락에서 함께 보강된 개념", edge_weight=0.5))
        return search_hashes

    async def _node_from_slot(self, slot: EmptySlot, search_text: str | None) -> Node:
        hint, h = normalize_text(slot.concept_hint), compute_hash(slot.concept_hint)
        existing = get_node(self.conn, h)
        if existing:
            if search_text and not existing.payload.get("search_summary"):
                existing.payload["search_summary"] = search_text[:800]
                existing.touch()
                update_node(self.conn, existing)
                self.conn.commit()
            return existing
        try:
            embedding = await self.embed_fn(hint)
        except Exception:
            embedding = None
        now = utcnow()
        node = Node(h, "concept", "ingest", [hint], trust_score=config.COMMIT_TRUST_WEAK, stability_score=config.COMMIT_STABILITY_WEAK, embedding=embedding, payload={"search_summary": search_text[:800]} if search_text else {}, created_at=now, updated_at=now)
        insert_node(self.conn, node)
        if not word_link_exists(self.conn, hint, h):
            insert_word(self.conn, WordEntry(str(uuid.uuid4()), hint, h, None, now))
        self.conn.commit()
        return node

    def _commit(self, tg: TempThoughtGraph) -> None:
        for h in tg.all_added_node_hashes:
            node = tg.get_node(h)
            if node:
                insert_node(self.conn, node)
        for edge_id in tg.all_added_edge_ids:
            edge = tg.get_edge(edge_id)
            if not edge or edge.is_temporary:
                continue
            existing = get_edge_by_endpoints(self.conn, edge.source_hash, edge.target_hash)
            if existing:
                existing.edge_weight = max(existing.edge_weight, edge.edge_weight)
                existing.support_count += 1
                existing.touch()
                update_edge(self.conn, existing)
            else:
                insert_edge(self.conn, edge)
        self.conn.commit()


def render_surface_frame(conclusion: ConclusionView) -> str:
    node_by_hash = {n.address_hash: n for n in conclusion.nodes}
    key_nodes = [node_by_hash[h] for h in conclusion.key_hashes if h in node_by_hash]
    ref_nodes = [node_by_hash[h] for h in conclusion.ref_hashes if h in node_by_hash]
    visible = {n.address_hash for n in key_nodes + ref_nodes}
    frames = []
    for edge in conclusion.edges:
        if edge.source_hash in visible or edge.target_hash in visible:
            s, t = node_by_hash.get(edge.source_hash), node_by_hash.get(edge.target_hash)
            if s and t:
                frames.append({"source": s.primary_label(), "relation": edge.proposed_connect_type or edge.connect_type, "target": t.primary_label(), "weight": round(edge.edge_weight, 3), "evidence": edge.proposal_reason})
    search_context = [n.payload.get("search_summary") for n in key_nodes + ref_nodes if n.payload.get("search_summary")]
    frame = {"surface_frame_version": "mk6_1.core", "mode": "answer_from_conclusion" if frames or search_context else "acknowledge_context_update", "copy_user_input": False, "max_sentences": 4, "topic_continuity": conclusion.topic_continuity, "key_concepts": [n.primary_label() for n in key_nodes], "reference_concepts": [n.primary_label() for n in ref_nodes], "frames": frames[:24], "search_context": search_context[:6]}
    return json.dumps(frame, ensure_ascii=False, indent=2)
