
"""ConceptMerge — 유사도가 극도로 높은 노드를 하나로 통합."""
from __future__ import annotations

from itertools import combinations
from .temp_thought_graph import TempThoughtGraph
from .concept_differentiation import composite_score
from ... import config

# 병합을 위한 별도 임계값 (분화보다 훨씬 엄격하게)
MERGE_THRESHOLD = 0.94 

def run(tg: TempThoughtGraph) -> int:
    """임시 사고 그래프 내 노드 쌍을 검사해 병합을 수행한다.
    
    Returns:
        병합된 노드 쌍의 수
    """
    merge_count = 0
    
    # 후보 노드 (비추상, 목표 노드 제외)
    nodes = [
        n for n in tg.all_nodes()
        if n.embedding is not None
        and n.is_active
        and not n.is_abstract
        and n.address_hash != tg.goal_hash
    ]

    # 이웃 정보 캐싱
    neighbor_cache = {
        n.address_hash: tg.neighbor_hashes(n.address_hash)
        for n in nodes
    }

    # 이번 루프 회차에서 변경/추가된 노드들 (Delta 활용)
    delta = tg.current_delta()
    modified_hashes = set(delta.added_nodes) | set(delta.modified_nodes)

    # 유사한 쌍 찾기
    for node_a, node_b in combinations(nodes, 2):
        hash_a, hash_b = node_a.address_hash, node_b.address_hash
        
        # 1. 둘 중 하나가 이미 병합되어 사라졌으면 건너뜀
        if tg.get_node(hash_a) is None or tg.get_node(hash_b) is None:
            continue

        # 2. 증분 검사 최적화: 
        # 두 노드 모두 이번 회차에서 변한 게 없고, 이미 이전 회차들에서 검사했다면 스킵.
        if hash_a not in modified_hashes and hash_b not in modified_hashes:
            if tg.is_pair_checked(hash_a, hash_b):
                continue

        # 검사 완료 마킹
        tg.mark_pair_checked(hash_a, hash_b)

        score = composite_score(
            node_a, node_b, 
            neighbor_cache[hash_a], 
            neighbor_cache[hash_b]
        )

        if score >= MERGE_THRESHOLD:
            # 병합 결정: 더 안정적인 노드(stability_score가 높은 노드)를 남김
            if node_a.stability_score >= node_b.stability_score:
                survivor, deprecated = node_a, node_b
            else:
                survivor, deprecated = node_b, node_a
            
            print(f"[merge] merging {deprecated.primary_label() or deprecated.address_hash[:8]} "
                  f"into {survivor.primary_label() or survivor.address_hash[:8]} (score={score:.3f})")
            
            tg.merge_nodes(deprecated.address_hash, survivor.address_hash)
            merge_count += 1

    return merge_count
