# mk6_1

`mk6_1`은 현재 `MK6`에서 실제 대화 실행에 필요한 핵심 흐름만 남긴 정리본이다.

남긴 흐름:

1. 사용자 입력을 개념 참조와 빈 슬롯으로 번역한다.
2. WorldGraph의 기존 노드와 국소 그래프를 임시 사고 그래프에 올린다.
3. 빈 슬롯은 검색 컨텍스트와 함께 신규 개념 노드로 보강한다.
4. 입력 관계와 목표 연결을 엣지로 구성하고 WorldGraph에 커밋한다.
5. 결론 그래프를 SurfaceFrame JSON으로 투영한다.
6. GraphToLang LLM이 SurfaceFrame만 보고 한국어 답변을 생성한다.

제외한 것:

- 문서/테스트/정적 UI
- claim/profile/activation/merge 계열 확장 분기
- 레거시 호환용 코드와 사용되지 않는 보조 분기
- 실행 경로에 직접 필요하지 않은 주석성 설계 산출물

실행:

```bash
pip install -r mk6_1/requirements.txt
python -m mk6_1.run_cli
python -m mk6_1.run_server
```

API:

```bash
curl -X POST http://127.0.0.1:8006/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"안녕? 난 신재용이야"}'
```
