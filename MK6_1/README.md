# MK6_1

MK6_1은 MK6에서 실제 실행 경로에 걸리는 핵심 파이프라인만 분리하기 위한 작업 브랜치입니다.

현재 반영 상태:

- 포함: CLI 진입점, app 패키지, config 핵심 설정
- app/pipeline.py와 app/server.py는 현재 MK6 핵심 실행 경로를 가리키는 미러입니다.
- 제외 의도: docs, tests, rewritten README, 과거 설계 문서, 실행 경로와 무관한 자료

주의:

현재 커넥터 환경에서는 GitHub 디렉터리 전체 복사와 tree 기반 일괄 커밋을 사용할 수 없어, 모든 실제 모듈을 독립 복사하는 작업은 완료하지 못했습니다. 따라서 이 PR은 최종 추출본이 아니라 MK6_1 구조 생성과 실행 진입점 분리의 WIP입니다.

다음 단계:

1. MK6/core, MK6/tools, MK6/app/static 중 import graph에 걸리는 파일만 MK6_1로 실제 복사
2. MK6_1 내부 import를 MK6_1 기준으로 치환
3. answer_contract_clean.py, docs, tests, 백업/rewritten 문서 제외
4. python -m compileall MK6_1 또는 최소 CLI/server import 검증
