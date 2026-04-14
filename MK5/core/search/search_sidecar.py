from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.cognition.hash_resolver import HashResolver
from core.cognition.input_segmenter import InputSegmenter
from core.entities.conclusion import CoreConclusion


@dataclass(slots=True)
class SearchEvidence:
    title: str
    snippet: str
    url: str
    provider: str = 'wikipedia'
    source_type: str = 'search'
    claim_domain: str = 'world_fact'
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text_for_graph(self) -> str:
        if self.snippet:
            return f'{self.title}: {self.snippet}'
        return self.title


@dataclass(slots=True)
class SearchSidecar:
    max_results: int = 2
    timeout_seconds: float = 4.0
    hash_resolver: HashResolver = field(default_factory=HashResolver)
    segmenter: InputSegmenter = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'segmenter', InputSegmenter(hash_resolver=self.hash_resolver))

    def should_search(self, message: str, conclusion: CoreConclusion) -> bool:
        compact = ' '.join((message or '').split())
        has_interrogative_form = compact.endswith('?') or compact.endswith('？')
        sparse_graph = len(conclusion.activated_concepts) <= 2 and len(conclusion.key_relations) <= 1
        unstable_graph = len(conclusion.detected_conflicts) > 0 and len(conclusion.key_relations) <= 2

        if conclusion.inferred_intent == 'memory_probe':
            return False
        if conclusion.inferred_intent == 'open_information_request':
            return has_interrogative_form
        return has_interrogative_form and (sparse_graph or unstable_graph)

    def search(self, message: str, conclusion: CoreConclusion) -> list[SearchEvidence]:
        if not self.should_search(message, conclusion):
            return []
        query = self._build_query(message)
        if not query:
            return []
        results = self._search_wikipedia(query, lang='ko')
        if results:
            return results[: self.max_results]
        return self._search_wikipedia(query, lang='en')[: self.max_results]

    def _build_query(self, message: str) -> str:
        blocks = self.segmenter.segment(message)
        noun_parts: list[str] = []
        for block in blocks:
            if block.block_kind != 'noun_phrase':
                continue
            token = block.normalized_text.strip()
            if len(token) < 2:
                continue
            if token in noun_parts:
                continue
            noun_parts.append(token)
            if len(noun_parts) >= 4:
                break
        if noun_parts:
            return ' '.join(noun_parts)
        return ' '.join(message.split())[:80]

    def _search_wikipedia(self, query: str, *, lang: str) -> list[SearchEvidence]:
        base = f'https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={quote(query)}&limit={self.max_results}&namespace=0&format=json'
        request = Request(base, headers={'User-Agent': 'MK5-SearchSidecar/0.1'})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except Exception:
            return []

        titles = payload[1] if len(payload) > 1 else []
        descriptions = payload[2] if len(payload) > 2 else []
        urls = payload[3] if len(payload) > 3 else []
        evidences: list[SearchEvidence] = []
        for index, title in enumerate(titles[: self.max_results]):
            snippet = descriptions[index] if index < len(descriptions) else ''
            url = urls[index] if index < len(urls) else ''
            if not title:
                continue
            evidences.append(
                SearchEvidence(
                    title=str(title),
                    snippet=str(snippet or ''),
                    url=str(url or ''),
                    provider=f'wikipedia-{lang}',
                    metadata={'query': query, 'lang': lang},
                )
            )
        return evidences
