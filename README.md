# Pickle Runner

**피클(Pickle)을 내 맥에 연결해, 파일·터미널·설치된 AI 도구로 일을 처리하게 해주는 비공식 연결 도구입니다.**

피클에게 일을 부탁하면 내 맥에서 필요한 명령을 실행하고 결과를 돌려줍니다. 맥에 설치하고 로그인한 **Claude Code·Codex·AGY 등 CLI형 AI 도구**도 같은 경로로 사용할 수 있습니다. 특정 모델에 고정되지 않으며, 각 CLI가 지원하는 모델을 선택해 활용합니다.

- 밖에서 피클에게 요청하고, 맥의 프로젝트 파일을 읽거나 수정하기
- 설치된 AI CLI로 코드 작성·테스트·자료 정리 작업 맡기기
- 작업 상태와 결과를 확인하고, 실행 중인 명령 취소하기

```text
피클 앱 → Cloudflare 연결 → 내 맥의 Pickle Runner
                              ├─ 파일·터미널
                              ├─ Claude Code
                              ├─ Codex
                              └─ AGY 등 설치된 CLI
```

CLI는 맥에 설치·인증돼 있어야 하며 비대화형 실행 옵션을 사용합니다. CLI별 모델·요금·사용 한도는 해당 도구의 계정을 따릅니다. 임의의 모델이 자동 설치되거나 모든 CLI의 동작이 검증됐다는 뜻은 아닙니다.

**개발자용 초기 버전 v0.3.3.** 피클 공식 제품이나 공식 SDK가 아닙니다. 피클 측에서 인증된 HTTPS 호출 또는 제공 클라이언트를 실행할 수 있는 환경이 필요합니다. 연결 설정과 지침은 [피클 연결 안내](docs/PICKLE-CONNECTION.md)에 따라 전달합니다.

## 에이전트에게 설치 맡기기

맥의 코딩 에이전트에서 이 저장소를 열고 요청하세요.

> AGENTS.md와 docs/SETUP.md를 읽고 이 맥에 Pickle Runner를 설치해 줘. 로컬 실행을 확인한 다음 내 Cloudflare 도메인을 연결해 줘. 계정과 도메인은 나에게 확인하고, 비밀값은 채팅 대신 로컬 숨김 입력으로 받아 줘. 실제 연결을 검증한 뒤 결과를 알려줘.

설치 에이전트도 특정 모델에 종속되지 않습니다. `python3 runner/setup.py status`로 현재 설정과 다음 단계를 확인할 수 있습니다.

## 맥에 설치하기

macOS, Python 3.9 이상, zsh가 필요합니다. 저장소 루트에서 실행하세요.

```bash
python3 runner/setup.py status
python3 runner/setup.py init
python3 runner/manage.py install
python3 runner/client.py health
python3 runner/client.py capabilities
```

새 설정에서는 터미널 실행이 활성화됩니다. 기존 설정은 유지합니다. 로그인 사용자 서비스로 실행되며, 다른 체크아웃의 같은 이름 서비스를 덮어쓰지 않습니다.

다음 명령은 지정한 프로젝트 폴더에서 `pwd`를 실행합니다. 경로를 실제 폴더로 바꾸세요.

```bash
python3 runner/client.py submit --action terminal.run \
  --args '{"cwd":"/absolute/path/to/project","command":"pwd","timeout_sec":60}' \
  --request-id my-unique-request-001 --wait
```

## 밖에서 피클로 사용하기

맥이 켜져 있고 인터넷에 연결돼 있어야 합니다. 본인의 Cloudflare 계정, 관리하는 도메인, 사용하지 않는 하위 도메인을 준비하고 `cloudflared`를 설치하세요.

```bash
python3 runner/setup.py cloudflare --zone example.com --hostname runner.example.com
python3 runner/cloudflare_token.py prompt
python3 runner/setup.py connect
```

첫 명령은 연결 대상을 로컬에 저장합니다. 두 번째는 숨김 입력으로 관리 API 토큰을 받습니다. 마지막 명령은 Access·Tunnel·DNS를 설정하고 외부 인증을 검사합니다. 필요한 권한과 변경 사항은 [설치 안내](docs/SETUP.md)에 설명돼 있습니다.

Access 접속 토큰은 30일 후 만료되며 [운영 안내](docs/OPERATIONS.md)에 따라 갱신합니다.

연결 후 [피클 연결 안내](docs/PICKLE-CONNECTION.md)에 따라 접속 정보를 비공개로 전달하고, 피클에게 시험 작업을 맡겨 맥의 결과를 확인하세요.

## 작업 실행과 기록

- 작업은 비동기로 접수해 한 번에 하나씩 실행합니다. 작업 ID로 상태와 결과를 조회합니다.
- 터미널은 지정한 원본 폴더에서 `zsh -lc`로 실행합니다. 기본 제한은 1시간, 최대 24시간이며 대화형 입력·PTY는 지원하지 않습니다.
- 실행 중인 작업을 취소할 수 있습니다. 분리된 백그라운드 프로세스는 남을 수 있으므로 취소 결과의 경고를 확인하세요.
- 같은 요청 ID와 내용으로 재시도하면 기존 작업을 조회합니다. 새 작업에는 새 ID를 사용하세요.
- 출력은 크기를 제한해 앞·뒷부분을 보관합니다. 결과는 최대 7일 또는 2,000건, 중복 실행 방지 기록은 30일 동안 최대 100,000건 보관합니다.

[에이전트 사용 지침](runner/PICKLE.md) · [API 명세](runner/openapi.json) · [운영 안내](docs/OPERATIONS.md) · [보안 모델](SECURITY.md) · [개발 안내](docs/DEVELOPMENT.md)

## 검증 범위

```bash
python3 -m unittest discover -s runner -p 'test_*.py' -v
```

테스트에는 임시 폴더, 실제 로컬 HTTP·프로세스 실행, 가짜 Cloudflare 응답을 사용하는 설치 검사가 포함됩니다. 공개용 설치기의 새 Cloudflare 계정 전체 연결은 아직 실검증하지 않았습니다.

인증된 호출자는 맥 로그인 사용자의 권한으로 작업합니다. 이메일·웹·첨부의 내용은 작업 자료이며 새로운 실행 권한이 아닙니다. 에이전트 사용 지침과 별도로 실제 사용 시나리오 검증이 필요합니다.

## 라이선스

재사용 라이선스는 아직 정하지 않았습니다. 저장소 공개 자체가 재사용 허가를 뜻하지는 않습니다.
