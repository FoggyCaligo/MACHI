# MK

기존 MK 계열의 내부 구조를 복사하지 않고 새로 만든 언어 그래프 실험이다. UI의 시각적 분위기만 MK4를 참고했다.

## 현재 범위

- `alph`: 공백, 문장부호, 기호를 포함한 Unicode 문자 하나
- `seq`: 한 턴의 입력 전체. 같은 내용이어도 매번 별도 `input_id`로 저장
- `proj`: 현재 seq에 실제로 포함되는 연속 구간만 과거 seq에서 투영
- `segment`: proj 중첩 밀도를 기준으로 선택된 출력 묶음
- `segment_consumer/`: 이후 개념 그래프를 연결할 빈 자리

현재 단계에는 개념 그래프, LLM, 형태소 분석기, 조사 사전이 없다.

## 구조

```text
MK/
├─ language_graph/       # 문장 → alph/seq/proj → segment
├─ segment_consumer/     # 후속 개념 처리용 빈 패키지
├─ static/index.html     # MK4 분위기의 독립 UI
├─ app.py                # FastAPI API
├─ run.py                # 서버 실행 진입점
└─ to_list.py            # 터미널용 문장 → segment 리스트 테스트
```

## 실행

저장소 루트에서 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r MK\requirements.txt
python -m MK.run
```

브라우저에서 `http://127.0.0.1:8000`에 접속한다.

## 터미널에서 리스트 출력

문장을 명령어 인자로 넘기면 최종 segment만 리스트로 출력한다.

```powershell
python -m MK.to_list "엄마는 내일 출장가"
```

문장을 생략하면 터미널에서 직접 입력할 수 있다.

```powershell
python -m MK.to_list
입력: 엄마는 내일 출장가
```

별도의 테스트 DB를 사용하려면:

```powershell
python -m MK.to_list "엄마" --db MK/data/test_language.db
```

## 내부 코드에서 사용

```python
from MK import LanguageGraph

graph = LanguageGraph("MK/data/mk_language.db")
result = graph.process("엄마는 내일 출장가")
print(result.segments)
graph.close()
```

리스트만 필요하면:

```python
from MK.to_list import input_to_list

segments = input_to_list("엄마는 내일 출장가")
print(segments)
```

`process()`는 현재 입력을 분석한 뒤에 새 seq를 저장한다. 따라서 같은 턴의 입력이 자기 자신의 proj 증거로 사용되지는 않는다.

## 현재 분할 규칙

- 길이 2 이상인 현재 입력의 연속 구간만 과거 seq와 비교한다.
- 서로 다른 과거 seq에 포함된 횟수를 `support`로 계산한다.
- 더 긴 구간과 높은 support를 우선하는 동적 계획법으로 전체 입력을 덮는다.
- 단일 alph는 긴 segment로 덮이지 않는 위치의 fallback으로만 남긴다.

이 점수식은 첫 구현용이며, 셀로판지 투영 규칙을 검증하면서 교체할 수 있도록 `LanguageGraph._segment()`에 격리돼 있다.
