# MK4

`MK4`는 `MK3`의 그래프 사고를 유지하되, **단어와 의미를 같은 층에서 다루던 문제를 분리하려는 단계**다.

`MK3`에서는 그래프의 노드를 단어 중심으로 세웠기 때문에, 이름만 다른 같은 개념도 서로 다른 노드로 시작하게 되는 문제가 있었다. 말이 다르면 노드도 달라지고, 그 뒤에야 관계로 맞춰야 했기 때문에, 같은 개념이 표면형 차이 때문에 쪼개지는 일이 자주 생긴다.

`MK4`는 이 문제를 해결하기 위해, 언어를 그래프 본체가 아니라 **그래프에 접근하기 위한 주소 계층**으로 내린다.

## 목표

`MK4`의 목표는 다음과 같다.

> 단어는 의미 그 자체가 아니라 노드에 접근하는 표면 주소로 쓰고, 실제 사고와 기억은 그 뒤의 의미 그래프에서 수행한다.

즉 이 단계가 고치려는 문제는 아래와 같다.

- 같은 개념이 다른 단어라는 이유만으로 다른 노드가 되는 문제
- 언어 표면형이 그래프 본체를 과하게 지배하는 문제

## 기능

### 1. 언어와 그래프의 분리

- 단어는 직접 의미 노드가 아니다.
- 단어는 먼저 정규화되고, 해시 주소를 통해 그래프 노드에 접근한다.

### 2. 표면형 주소 테이블

- `words` 테이블이 `surface_form`과 `address_hash`를 연결한다.
- 하나의 표면형이 여러 후보 노드에 연결될 수 있다.

즉 단어는 "정답 노드"가 아니라, **의미 그래프에 진입하기 위한 주소 인덱스**다.

### 3. 주소 기반 노드 접근

코드 기준으로 `MK4`는 아래 순서로 주소를 만든다.

- `normalize_text(token)`
  - Unicode NFC 정규화
  - 소문자화
  - 앞뒤 공백/구두점 제거
  - 한국어 조사 제거를 한 번 수행
- `compute_hash(token)`
  - `sha256("word::" + normalized_text)`의 앞 32 hex를 사용

즉 각 단어는 표면형 그대로 저장되는 것이 아니라, **정규화된 문자열에서 계산된 `address_hash`를 타고 노드에 접근**한다.

### 4. 의미 그래프 본체

- 실제 노드는 `nodes.address_hash`를 기본 키로 가진다.
- 단어 링크는 `words`에서 관리하고, 의미 관계는 `edges`에서 관리한다.

그래프 본체는 단어 목록이 아니라, 노드와 엣지의 구조다.

### 5. 임시 사고 그래프와 영구 그래프 분리

- 입력을 받은 뒤 바로 영구 그래프를 흔들지 않는다.
- 먼저 `TempThoughtGraph`에서 사고와 조정을 수행한 뒤, 필요한 내용만 `WorldGraph`에 반영한다.

## 작동방식

`MK4`의 흐름은 아래처럼 이해하면 된다.

```text
사용자 입력
-> 단어 정규화
-> address_hash 계산
-> words 테이블을 통해 후보 노드 접근
-> 관련 LocalSubgraph 구성
-> TempThoughtGraph에서 사고/조정
-> 필요한 경우만 WorldGraph 반영
-> ConclusionGraph 생성
-> GraphToLang으로 언어화
```

이 단계에서 중요한 점은, 단어가 그래프의 본체가 아니라 **그래프를 여는 키**라는 점이다.

## 사고과정

`MK4`의 사고는 기억하신 것처럼 **목적(goal)과 현재 입력 사이의 전파**를 중심에 둔다. 다만 코드 기준으로 보면, "가장 먼저 닿은 노드 하나"만 뽑는 단순 구조는 아니다.

실제 흐름은 아래에 더 가깝다.

### 1. 목표 노드를 먼저 세운다

- `Pipeline`이 전역 goal graph를 초기화하고
- `ThoughtEngine`이 `TempThoughtGraph`에 goal node를 먼저 심는다

즉 사고의 기준점은 항상 현재 턴의 입력이 아니라, **먼저 존재하는 목적 노드**다.

### 2. 현재 입력을 그래프로 번역해 goal에 연결한다

- `lang_to_graph()`가 입력을 `TranslatedGraph`로 바꾼다
- direct input으로 잡힌 `ConceptPointer`들은 `tg.connect_to_goal(...)`로 goal에 연결된다
- direct input match는 user anchor에도 연결된다

즉 현재 입력은 독립적으로 떠 있는 것이 아니라, **처음부터 목적과 사용자 축에 묶인 채로 사고 그래프에 들어간다**.

### 3. 관련 기억을 더 실어 온다

`ThoughtEngine.think()`는 입력만 넣고 끝나지 않는다. 아래 subgraph도 함께 불러온다.

- goal node 주변 subgraph
- profile activation seed hashes
- 이전 턴 `previous_key_hashes`
- 이전 assertion state의 node hashes
- user / assistant anchor 주변 subgraph

그래서 실제 `TempThoughtGraph`는 "지금 입력" 하나가 아니라, **목적 + 현재 입력 + 이전 맥락 + 프로필 + identity anchor**가 같이 들어 있는 작업 공간이다.

### 4. 루프 안에서 slot 채우기와 구조 조정을 반복한다

루프 안에서는 아래가 반복된다.

- empty slot이 있으면 검색으로 채운다
- `concept_differentiation`으로 구분이 필요한 개념을 분화한다
- `surface_variant_evidence`를 쌓는다
- 필요하면 `concept_merge`를 수행한다
- `goal_alignment.score_goal_alignment(...)`로 현재 그래프가 목적과 얼마나 맞는지 본다

즉 사고는 "전파 후 바로 답변"이 아니라, **goal alignment가 좋아지는 방향으로 그래프를 반복 조정하는 과정**이다.

### 5. 결론은 activation 기반으로 추린다

마지막에는 `build_activation_conclusion_graphs(...)`가 호출되어, 현재 `TempThoughtGraph` 안에서 활성화와 정렬이 높은 구조를 결론 그래프로 뽑는다.

따라서 `MK4`의 사고를 한 줄로 정리하면 이렇다.

> 목적 노드를 기준점으로 두고, 현재 입력과 관련 기억들을 그 주변에 연결한 뒤, goal alignment가 높은 방향으로 임시 그래프를 반복 조정하고, 그중 활성화된 결론 구조만 추려 언어화한다.

## 기억구조

`MK4`의 기억 구조는 크게 세 층이다.

### 1. 언어 주소층

- 저장소: `words`
- 역할: 표면형 단어를 `address_hash`에 연결

### 2. 의미 그래프층

- 저장소: `nodes`, `edges`
- 역할: 실제 개념과 관계를 저장

### 3. 사고 작업층

- 구조: `TempThoughtGraph`
- 역할: 현재 턴에서만 쓰는 임시 조정 공간

즉 `MK4`의 핵심은 **언어는 lookup 계층, 의미 그래프는 본체, 사고는 임시 그래프에서**라는 분리다.

## 실행방법

아래는 Windows PowerShell 기준으로, 빈 PC에서 새로 내려받아 실행하는 순서다.

### 1. 저장소 받기

```powershell
git clone https://github.com/FoggyCaligo/MACHI.git
cd MACHI\MK4
```

### 2. 가상환경 만들기

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Ollama 준비

`MK4`는 생성 모델과 임베딩 모델을 둘 다 쓴다.

```powershell
ollama serve
```

새 PowerShell 창에서:

```powershell
ollama pull gemma3:4b
ollama pull nomic-embed-text
```

### 4. 서버 실행

```powershell
python run_server.py --host 127.0.0.1 --port 8000 --reload
```

### 5. 접속 확인

브라우저에서 아래 주소를 연다.

```text
http://127.0.0.1:8000/
```

CLI로 바로 시험하려면:

```powershell
python run_cli.py
```

구현을 볼 때 우선순위가 높은 파일은 아래다.

- `core/utils/hash_resolver.py`
- `core/storage/world_graph.py`
- `core/translation/lang_to_graph.py`
- `core/thinking/temp_thought_graph.py`
- `core/thinking/thought_engine.py`
- `docs/architecture/graph_schema.md`

