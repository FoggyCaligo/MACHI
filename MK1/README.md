# MK1

`MK1`은 기존 sLLM이 **대화 문맥을 이어가지 못하고, 사용자를 기억하지 못하는 문제**를 해결하기 위해 만든 구현이다.

로컬 모델은 한 번의 질문에 답할 수는 있어도, 대화가 길어지면 앞에서 나온 맥락을 놓치기 쉽고, 사용자의 취향이나 선호를 다음 답변에 반영하지 못하는 경우가 많다.  
그래서 같은 사람과 여러 번 대화해도, 매번 처음 만나는 상대처럼 반응하게 된다.

`MK1`은 이 문제를 해결하기 위해, 로컬 LLM 앞단에 **최근 대화 기억**과 **사용자 메모**를 붙여서 답변을 만들도록 구성한다.

## 목표

`MK1`의 목표는 다음과 같다.

> 로컬 LLM이 최근 문맥을 이어가고, 사용자의 취향을 조금씩 기억하면서 더 개인화된 답변을 하게 만드는 것

즉 `MK1`이 해결하려는 문제는 아래 두 가지다.

- 대화 문맥이 턴마다 끊기는 문제
- 사용자에 대한 기억이 남지 않는 문제

## 기능

### 1. 최근 대화를 저장한다

- 사용자와 assistant의 메시지를 SQLite에 저장한다.
- 다음 답변을 만들 때 최근 대화를 다시 불러온다.

### 2. 사용자 메모를 유지한다

- 사용자의 취향, 선호, 성향을 JSON 파일에 저장한다.
- 이 메모는 다음 답변에서 프롬프트 컨텍스트로 다시 들어간다.

### 3. 사용자 메모를 갱신한다

- 새 사용자 입력에서 특정 표현을 찾아 간단한 선호 정보를 추가한다.
- 방식 자체는 규칙 기반 갱신에 가깝다.

### 4. 필요하면 검색으로 보강한다

- 로컬 모델만으로 부족한 최신 정보는 `trusted_search`로 보강한다.

## 작동방식

`MK1`은 아래 순서로 움직인다.

```text
사용자 입력
-> 메시지 저장
-> 사용자 입력에서 프로필 업데이트
-> 시스템 프롬프트 + 사용자 프로필 + 최근 대화 구성
-> 로컬 LLM 호출
-> 필요하면 검색 보강
-> 최종 답변 저장
```

조금 더 풀어서 보면 이렇다.

1. 사용자가 메시지를 보낸다.
2. 시스템은 그 메시지를 대화 기록에 저장한다.
3. 메시지 안에서 사용자 취향이나 선호와 관련된 표현을 찾는다.
4. 찾은 내용을 사용자 메모에 반영한다.
5. 최근 대화와 사용자 메모를 함께 프롬프트에 붙인다.
6. 로컬 LLM이 그 정보를 참고해 답변한다.
7. 필요하면 검색 결과를 덧붙여 답변을 보강한다.

핵심은 **프롬프트 앞단에 기억을 붙여, sLLM이 문맥과 사용자를 유지하게 만드는 것**이다.

## 기억구조

`MK1`의 기억은 두 부분으로 나뉜다.

### 1. 최근 대화 기록

- 저장소: `data/chat_history.db`
- 역할: 직전 대화 문맥 유지

### 2. 사용자 프로필 메모

- 저장소: `data/user_profile.json`
- 역할: 취향, 선호, 반복 성향 저장

즉 `MK1`의 기억은 **대화 로그 + 사용자 요약 메모**를 프롬프트에서 다시 조립하는 구조다.

## 파일 구조와 역할

`MK1`의 핵심 파일은 아래와 같다.

```text
MK1/
├─ app.py                    # 서버 시작점. 요청을 받고 응답 흐름을 연결함
├─ agent.py                  # LLM에게 실제 답변을 생성하게 하는 부분
├─ memory.py                 # 대화 기록과 사용자 메모를 읽고 저장하는 부분
├─ trusted_search.py         # 필요할 때 외부 검색으로 정보를 보강하는 부분
├─ config.py                 # 경로, 모델명, 기본 설정 관리
├─ system_prompt.txt         # AI의 기본 지시문
├─ requirements.txt          # 설치해야 할 Python 패키지 목록
├─ README.md                 # 프로젝트 설명 문서
└─ data/
   ├─ chat_history.db        # 최근 대화가 저장되는 SQLite 파일
   └─ user_profile.json      # 사용자 취향과 성향 메모가 저장되는 파일
```

한마디로 보면 `MK1`은 아래처럼 나뉜다.

- `app.py`가 요청을 받는 입구 역할을 한다.
- `memory.py`가 대화 기록과 사용자 메모를 관리한다.
- `agent.py`가 그 기억을 붙여 답변을 만든다.
- `data/`가 실제 기억 저장소 역할을 한다.

## 실행방법

아래는 Windows PowerShell 기준으로, 빈 PC에서 새로 내려받아 실행하는 순서다.

### 1. 저장소 받기

```powershell
git clone https://github.com/FoggyCaligo/MACHI.git
cd MACHI\MK1
```

### 2. Python 설치

Python이 없다면 먼저 설치한다.

- 다운로드: [https://www.python.org/downloads/windows/](https://www.python.org/downloads/windows/)

설치할 때 `Add Python to PATH` 옵션을 켜 두는 것이 좋다.

설치 후 확인:

```powershell
python --version
```

### 3. 가상환경 만들기

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Ollama 준비

`MK1`은 로컬 Ollama가 필요하다. 기본값은 `gemma4:26b-a4b-it-q4_K_M`이다.

먼저 PowerShell에서 Ollama 서버를 실행한다.

```powershell
ollama serve
```

새 PowerShell 창을 열고 모델을 내려받는다.

```powershell
ollama pull gemma4:26b-a4b-it-q4_K_M
```

메모리가 부족하면 더 작은 모델로 바꾸고 실행할 수 있다.

```powershell
$env:OLLAMA_MODEL="qwen2.5:3b"
```

### 5. 서버 실행

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

### 6. 접속 확인

브라우저에서 아래 주소를 연다.

```text
http://127.0.0.1:8000/docs
```

## 코드로 확인하고 싶다면

구현 흐름을 직접 보고 싶다면 아래 파일부터 보면 된다.

- `app.py`
- `agent.py`
- `memory.py`
- `trusted_search.py`

## 한 줄 요약

`MK1`은 로컬 LLM이 최근 대화를 이어서 보고, 사용자 취향 메모를 함께 참고하면서,  
**문맥과 사용자를 완전히 잊지 않은 상태로 답변하게 만드는 구현**이다.
