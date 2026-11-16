# 핸드오프 — 2026-11-16

다음 작업자를 위한 인수인계 기록입니다. 아래 상태·수치·결과는 **2026-11-16 22:45 KST에 실제로 조회·실행한 값**이며, 그 뒤의 변경은 반영되지 않았습니다.

## 후속 수정 — CI 시작 지연과 README

사용자가 전체 수정·검증·커밋·push를 승인했다. 인증된 gh로 이전 실패 로그를 읽었으며 두 Python 조합 모두 통합시험 서버 시작 30초 초과였다. Python HTTPServer의 server_bind가 표시용 이름을 구하기 위해 socket.getfqdn을 호출하는 것을 확인했다. DNS 조회가 실패하도록 주입한 새 회귀 시험은 기존 코드에서 실패했다. 루프백 서버는 TCPServer의 바인딩을 사용하고 실제 주소·포트로 메타데이터를 설정하도록 변경했다. 이로써 시작 시 역조회 의존성을 제거했다. 이전 CI의 resolver 내부 대기 자체를 추적한 것은 아니며 새 CI 결과로 효과를 확인한다.

README 문장 제안 5건을 반영했고, 메일 협업에서 직접 실행기로 발전한 배경·사례 비교·결과 왕복 도식 및 AI 에이전트를 활용한 제작 설명을 포함했다. 아래 22:45 수치·해시·시험 개수는 수정 전 기록이다. 운영 중인 별도 실행기의 코드와 서비스는 변경하지 않았다.

로컬 전체 회귀 65개 통과(26.192초), 공개 파일 검사·diff 검사·README 로컬 링크 확인 통과. 첫 수정본 시험에서는 새 health 시험의 인증 헤더 누락과 기존 프로세스 정리 시험의 0.2초 기동 여유 부족이 드러났다. 헤더를 추가하고 해당 시험의 제한을 1초로 조정한 뒤 전체 회귀를 통과했다. 새 CI는 push 후 확인한다.

## 1. 기준 상태

- 작업 폴더: `~/Project/pickle-runner` (원격 `https://github.com/Seungyub-Jeon/pickle-runner.git`)
- 브랜치: `main`, `origin/main`과 동기
- 최신 커밋: `fac66530a95e74be64d8f42374540f257a9c52e3` — "Apply release review, MIT license and Korean documentation"
- 미커밋 변경: `README.md` 1개 파일, **+25 / −6** (`git diff --stat`). 워킹트리 README는 190줄·13,125바이트, sha256 `4ee29410fecc6dfa152e1e5bc612528d855b3fdfdc5d6df6b8b99cbd536d18c0`
- 폴더 구성: `runner/`(구현·시험), `docs/`(SETUP·PICKLE-CONNECTION·OPERATIONS·RELEASE·DEVELOPMENT), `scripts/check_public.py`, `AGENTS.md`, `SECURITY.md`, `LICENSE`, `README.md`
- 이 문서를 쓰기 전까지 저장소 루트와 `docs/`에 핸드오프 문서는 없었습니다. `HANDOFF.md`가 첫 핸드오프 기록입니다.

## 2. 로컬 시험·공개 검사 결과

| 명령 | 결과 | 비고 |
|---|---|---|
| `python3 -m unittest discover -s runner -p 'test_*.py' -v` | 종료코드 0, `Ran 64 tests in 19.872s` · `OK` | 실패 0 · 에러 0 · 스킵 0, 벽시계 약 20초 |
| `python3 scripts/check_public.py` | 종료코드 0, `Tracked-content checks: passed (heuristic; not a secrecy guarantee)` | `git ls-files` 기준 검사 |

- 인터프리터: `/usr/bin/python3` → **Python 3.9.6**. 저장소에 `.venv`·`venv`·`uv`가 없고 표준 라이브러리만 쓰므로 pytest 설치가 필요 없습니다.
- 시험 파일별 개수(합계 64와 일치): `test_integration` 15 · `test_setup` 12 · `test_observability` 8 · `test_project_results` 8 · `test_recovery` 8 · `test_projects` 7 · `test_terminal` 6
- 로그에 보이는 아래 줄들은 **실패가 아니라 통과한 시험이 일부러 만든 오류 경로**입니다. 조치할 것이 없습니다.
  - `sqlite3.IntegrityError: injected storage error` — `test_worker_database_error_is_visible_and_rejects_new_work`가 주입한 저장소 오류(결과 `ok`)
  - `invalid process marker quarantined` — 손상 복구 기록 격리 시험
  - `WARNING:pickle.access: ... status:401 / 400` — 인증·커서 검증 경로 시험
  - `독립 사용자 터널 서비스 시작 완료` — 터널 서비스 시험 출력
- **검증 범위 한계:** 이 맥에는 Python 3.9만 있어 로컬은 3.9로만 돌렸습니다. CI 매트릭스의 3.11 조합은 로컬에서 검증되지 않았습니다.
- 시험 실행으로 워킹트리에 생긴 변경은 없습니다(산출물은 임시 폴더에만 기록).

## 3. README.md 점검 결과 (Codex 점검 + 직접 교차 검증)

- 대상: 워킹트리 최신본(미커밋 수정 포함), 190줄·13,125바이트
- 방법: `codex exec -s read-only --ephemeral`(codex-cli 0.169.0), 해당 저장소 폴더 고정, 64초, 종료코드 0
- **파일은 수정하지 않았습니다.** 점검 전후 README sha256 동일, `git status`도 ` M README.md` 그대로
- 결과 요약
  - 깨진 내부 링크·이미지·앵커 **0건**
  - 외부 URL 형식 오류 **0건** — 쓰인 외부 URL 6개(배지 4개, `pickle.com/help/connect/add-connection`, `tuigunhu.com/29`, `pickle-desk`, `git clone` 주소) 모두 HTTP 200
  - 오타·맞춤법·마크다운 문법 오류 **0건** — 표 3개(41–47, 115–120, 177–184) 열 수 2·3·2 일치, `<details>`/`<summary>` 7쌍, 코드 펜스 3쌍 정상
  - 교차 검증: 내부 링크 인스턴스 16개·서로 다른 대상 9개 모두 존재, 문서 간 앵커 2개와 자기 앵커 4개 해석됨, 빠른 시작이 부르는 `runner/setup.py`·`manage.py`·`client.py`·`cloudflare_token.py` 모두 존재
  - 수치 주장이 `capabilities`와 일치: version 0.3.3, 결과 7일·2,000건, 중복 방지 30일·100,000건

### 선택 사항인 문장 개선 제안 5건

| 줄 | 원문(요지) | 문제 | 제안 |
|---|---|---|---|
| 30–35, 119 | "메일로 요청·결과를 주고받던 협업에…" / 비교표의 "초기: 메일로 요청·의견 교환…" | 최근 추가한 문단·목록·비교표에서 초기 협업 설명이 세 번 반복 | 30–32줄과 비교표 행은 두고, 34–35줄 요약 목록 생략 검토 |
| 105 | "인증된 HTTPS 요청 또는 제공 Python 클라이언트를 실행할 수 있어야 합니다." | "요청을 실행", "제공 Python"이 어색 | "인증된 HTTPS 요청을 보내거나 제공된 Python 클라이언트를 실행할 수 있어야 합니다." |
| 111 | "피클과 나눈 요청을 내 PC의 자료·실행 도구로 이어 주고" | "요청을 나누다", "도구로 이어 주다"의 의미가 흐림 | "피클에 맡긴 작업을 내 맥의 자료와 도구로 처리하고" |
| 113 | "일반 AI 도구의 기능 수보다 … 비교했습니다." | 비교 대상이 아닌 "기능 수"를 끌어와 초점이 흐림 | "각 사례에서 어떤 정보가 어떤 경로로 오가고, 로컬에서 어디까지 실행되는지 비교했습니다." |
| 119 | "아래 실행기로 발전한 과정입니다." | "아래"가 다음 표 행을 가리킨다는 점이 불명확 | "이 협업을 바탕으로 Pickle Runner 실행기를 만들었습니다." |

- 점검자가 밝힌 범위 밖 의견 두 가지(오류는 아님)
  - 109·111·113줄이 "내 PC / 개인 컴퓨터"를 쓰는데 문서 전체가 macOS 전용이므로 "맥"으로 통일하는 편이 자연스럽습니다.
  - 문서 표(177–184)에 `docs/RELEASE.md`가 빠졌으나 본문에서 두 번 링크됩니다.

## 4. 남은 일 (우선순위 순)

1. **CI 배지 정상화.** `Tests` 워크플로 배지가 지금 `Tests - failing`입니다. 공개 API로 확인한 사실은 다음과 같습니다.
   - 이 저장소의 Actions 실행은 **2건이 전부**이고 둘 다 실패입니다. `43875039047`(2026-11-16 13:21:50 UTC, 커밋 `fac6653`)·`43871378139`(12:58:17 UTC, `b33d2be`)
   - 최신 실행 `43875039047`은 `tests (3.9)`·`tests (3.11)` **두 잡 모두 4번째 스텝 `python3 -m unittest discover -s runner -p 'test_*.py' -v`에서 실패**했고, 그 뒤 `python3 scripts/check_public.py` 스텝은 `skipped`
   - 워크플로: `runs-on: macos-latest`, `python: ['3.9', '3.11']` 매트릭스, `fail-fast: false`, `timeout-minutes: 10`
   - 같은 명령이 로컬 3.9.6에서는 64개 전부 통과하므로 **코드 회귀보다 실행 환경 차이로 보이나, 원인은 확인되지 않았습니다.** 잡 로그는 리포지토리 admin 권한이 있어야 받을 수 있어(공개 API는 403) 이번에는 읽지 못했습니다.
   - 다음 작업: 저장소 소유자 인증으로 `gh run view 43875039047 --log-failed`를 실행하거나 Actions 화면에서 실패 스텝 로그를 확인 → 원인 수정 또는 워크플로 조정 → 새 실행에서 배지가 `passing`이 되는지 확인
2. **README 미커밋 수정분 처리.** 워킹트리 변경은 "메일로 시작한 연결" 절 추가, 동작 다이어그램을 양방향(`<-->`)으로 바꾼 것, 비교표를 사례별 표로 개편한 것입니다. 3절의 문장 개선 제안 반영 여부를 정한 뒤 커밋·푸시해야 합니다. 지금 GitHub에 공개된 README는 커밋된 구버전이며 "다른 방법과 비교" 표 상태입니다.
3. **공개 전 점검.** `git ls-files`와 새 파일 목록을 확인하고, `python3 scripts/check_public.py`를 다시 실행합니다(AGENTS.md·docs/DEVELOPMENT.md 규칙).

## 5. 이 문서를 고칠 때 지키실 것

- 이 저장소는 공개 대상입니다. `scripts/check_public.py`는 `git ls-files`에 든 파일에서 개인 홈 절대 경로, 메일 주소, 토큰·키 패턴, 비공개 산출물 경로(`.runtime`, `workspace`, `.pem`, `.enc`, `.db` 등)를 검사합니다. 그래서 이 문서에는 절대 경로 대신 `~/Project/pickle-runner` 같은 표기를 썼습니다. 문서를 고칠 때도 같은 규칙을 지켜 주세요.
- 이번 작업에서는 `README.md`와 소스 파일을 수정하지 않았습니다. README 문장 개선은 제안으로만 남겼습니다.
