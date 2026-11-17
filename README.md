<div align="center">

# Pickle Runner

**피클에게 부탁하고, 내 맥의 AI 도구로 일을 처리하세요.**

피클(Pickle)을 내 맥에 연결하는 비공식 도구입니다.
밖에서 피클에게 요청하면 맥의 파일·터미널과 설치된 **Claude Code·Codex·AGY** 등을 활용할 수 있습니다.
특정 LLM에 고정되지 않고, 각 CLI가 지원하는 모델을 선택해 사용합니다.

[![테스트](https://github.com/Seungyub-Jeon/pickle-runner/actions/workflows/tests.yml/badge.svg)](https://github.com/Seungyub-Jeon/pickle-runner/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![macOS](https://img.shields.io/badge/platform-macOS-lightgrey)
[![MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[빠른 시작](#빠른-시작) · [동작 방식](#어떻게-동작하나) · [보안](#보안) · [질문과 답변](#자주-묻는-질문)

</div>

> [!WARNING]
> **신뢰하는 한 사람이 사용하는 원격 셸이며, 샌드박스가 아닙니다.**
> Access 인증정보와 실행기 토큰을 모두 가진 호출자는 맥 로그인 사용자의 권한으로 작업합니다.
> 연결된 에이전트가 외부 글의 지시에 속으면 그 권한이 사용될 수 있습니다. 실행기는 지시의 출처를 판별하지 못합니다.

> [!NOTE]
> Pickle, Inc.와 관계가 없으며 그 회사가 제작하거나 보증한 도구가 아닙니다. Pickle은 해당 회사의 상표입니다.

## 메일로 시작한 연결

처음에는 피클 속 개인 비서 **민서**와 맥의 개발 에이전트가 메일로 이야기를 나눴습니다. 요청과 수정 의견을 전달하고, 핸드오프로 작업 맥락을 이어 가며, 테스트 결과를 회신받아 실제 실행 기록과 대조했습니다. 민서의 의견을 검토해 구현에 반영하는 방식으로 함께 개발했습니다.

그 과정에서 피클이 내 맥의 파일과 도구를 직접 사용할 수 있도록 실행기를 만들었습니다. **메일로 요청·결과를 주고받던 협업에, 작업 실행과 결과 조회 경로를 더한 것**이 Pickle Runner입니다.

메일은 협의와 피드백에 계속 사용할 수 있습니다. 실행기가 받은 메일을 자동으로 명령으로 바꾸는 구조는 아닙니다.

만든 과정과 실제 사용 기록: [피클, 민서가 내 맥북에 들어왔다](https://soyoyu.cc/blog/connecting-pickle-to-my-mac)

## 할 수 있는 일

| 기능 | 설명 |
|---|---|
| 밖에서 작업 맡기기 | 피클을 통해 맥의 프로젝트 파일을 읽고 수정하거나 명령을 실행합니다. |
| 설치된 AI 도구 활용 | 설치·인증한 Claude Code, Codex, AGY 등 CLI를 비대화형으로 호출합니다. 전용 어댑터를 추가할 필요가 없습니다. |
| 상태와 결과 확인 | 작업 ID로 실행 상태, 종료코드와 보관된 출력을 조회합니다. 긴 출력은 앞·뒷부분만 남습니다. |
| 취소와 긴급 중지 | 작업 취소와 연결 전체 중지 절차를 제공합니다. 분리된 백그라운드 프로세스는 별도 확인이 필요합니다. |
| 간단한 Python 구성 | 실행기는 Python 표준 라이브러리를 사용합니다. 외부 연결에는 별도로 cloudflared가 필요합니다. |

## 어떻게 동작하나

```mermaid
flowchart LR
    P["피클 앱"] <-->|"HTTPS · 작업 요청 / 결과 조회"| C["Cloudflare Access + Tunnel"]
    C <--> R["내 맥의 Pickle Runner · 127.0.0.1"]
    R --> T["파일 · 터미널 zsh"]
    R --> A["Claude Code · Codex · AGY 등 설치된 CLI"]
    R --> L[("작업 원장 SQLite")]
```

Cloudflare가 Access 인증정보를 확인하고, 맥의 실행기가 실행기 토큰을 확인합니다. 통과한 작업은 지정한 원본 폴더에서 한 번에 하나씩 실행됩니다. 피클은 작업 ID로 결과를 조회합니다. 실행기는 루프백에만 바인딩하며 공유기의 인바운드 포트를 열 필요가 없습니다.

## 빠른 시작

macOS, Python 3.9 이상, zsh가 필요합니다. 기존 실행기가 있다면 설치 위치와 사용 포트를 먼저 확인하세요.

```bash
git clone https://github.com/Seungyub-Jeon/pickle-runner.git
cd pickle-runner
python3 runner/setup.py status
python3 runner/setup.py init
python3 runner/manage.py install
python3 runner/client.py health
python3 runner/client.py capabilities
```

여기까지는 맥 내부 연결입니다. 새로운 설정에서는 `terminal.run`이 켜지며, 기존 설정은 유지합니다.

<details>
<summary><b>Cloudflare 연결하기</b></summary>

본인 Cloudflare 계정, 관리하는 도메인, 사용하지 않는 하위 도메인이 필요합니다. 먼저 [설치 안내](docs/SETUP.md)에 따라 `cloudflared`를 설치하세요.

```bash
python3 runner/setup.py cloudflare --zone example.com --hostname runner.example.com
python3 runner/cloudflare_token.py prompt
python3 runner/setup.py connect
```

관리 토큰은 숨김 입력창에서 받습니다. 연결 명령은 Access·Tunnel·DNS를 설정하고 외부 인증을 검사합니다. Access 서비스 토큰은 30일 후 만료되며 [운영 안내](docs/OPERATIONS.md)에 따라 갱신합니다.

</details>

<details>
<summary><b>도메인이 없을 때 (시험용)</b></summary>

이 저장소가 안내하는 정식 연결(Cloudflare Tunnel + Access)에는 Cloudflare에 올린 본인 도메인이 하나 필요합니다. 터널 주소와 Access를 그 도메인 아래에 만들기 때문입니다. 도메인 없이 동작만 확인하고 싶다면 Cloudflare의 [Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)로 임시 주소를 만들 수 있습니다. Cloudflare 계정도 필요 없습니다.

먼저 [설치 안내](docs/SETUP.md)에 따라 `cloudflared`를 설치하고, 로컬 실행기가 동작하는 상태에서 실행합니다.

```bash
cloudflared tunnel --url http://127.0.0.1:8796   # 설치 시 포트를 바꿨다면 그 값
```

출력된 `https://….trycloudflare.com` 주소로 접속 설정을 만듭니다. 별도의 비공개 JSON 파일에 `url`은 그 주소, `token`은 `.runtime/pickle-runner/client-local.json`의 값으로 넣고 권한을 0600으로 둡니다. Access 항목은 넣지 않습니다. [피클 연결 안내](docs/PICKLE-CONNECTION.md)의 암호화 명령에서 입력 파일만 이 파일로 바꿔 전달합니다.

| | 내 도메인 + Tunnel (정식) | Quick Tunnel (시험) |
|---|---|---|
| 주소 | 고정 | 실행할 때마다 바뀜. 바뀌면 접속 설정을 다시 전달 |
| 유지 조건 | 서비스로 상시 실행 | 그 `cloudflared` 프로세스가 살아 있는 동안만 |
| 인증 | Access + 실행기 토큰 두 층 | **실행기 토큰 한 층** |
| 가용성 | 일반 Tunnel | 보장 없음. 동시 요청 200건 초과 시 429 |
| 비용 | 도메인 비용 (이미 있으면 하위 주소는 무료) | 무료 |

새 주소는 출력된 뒤 바로 열리지 않을 수 있습니다. 시험에서는 처음 1분 남짓 연결 오류가 나다가 이후 정상 응답했습니다. 접속 오류가 나면 잠시 뒤 다시 시도하세요.

> [!WARNING]
> 이 절차에서는 정식 연결의 Access 서비스 토큰 인증이 구성되지 않습니다. Quick Tunnel의 `--allowed-mail` 옵션은 브라우저 로그인이 필요해 피클 같은 비대화형 클라이언트에는 쓸 수 없습니다. 이 실행기에는 명령 허용 목록도 없으므로, **주소와 실행기 토큰이 함께 새면 누구나 맥에서 명령을 실행할 수 있습니다.** 짧게 시험하고 끝나면 `cloudflared` 프로세스를 끄세요. 그러면 그 주소로는 더 이상 접속되지 않지만, 이미 실행 중인 작업과 실행기 토큰은 자동으로 취소·폐기되지 않습니다. 유출이 의심되면 [긴급 중지](docs/OPERATIONS.md#긴급-중지) 후 [유출 대응 절차](docs/OPERATIONS.md#자격증명과-갱신)에 따라 실행기 토큰도 바꾸세요.

상시 운영에는 도메인을 쓰세요. Cloudflare에 이미 올린 도메인이 있으면 하위 주소를 하나 더 쓰는 데 추가 비용이 없고, 새로 산다면 Cloudflare Registrar에서 살 수 있습니다. 무료 DDNS와 공유기 포트포워딩으로 직접 여는 방식은 집 IP가 드러나므로 권하지 않습니다. 다른 연결 방식은 별도 구성과 검증이 필요합니다.

</details>

<details>
<summary><b>코딩 에이전트에게 설치 맡기기</b></summary>

이 저장소를 로컬 코딩 에이전트에서 열고 요청하세요.

> AGENTS.md와 docs/SETUP.md를 읽고 이 맥에 Pickle Runner를 설치해 줘. 로컬 실행을 확인한 다음 내 Cloudflare 도메인 연결을 도와줘. 계정과 도메인은 나에게 확인하고, 토큰은 채팅 대신 로컬 숨김 입력으로 받아 줘. 실제 연결을 검증한 뒤 결과를 알려줘.

</details>

<details>
<summary><b>피클에 연결하기</b></summary>

피클 측에서 인증된 HTTPS 요청을 보내거나 제공된 Python 클라이언트를 실행할 수 있어야 합니다. 접속 설정을 암호화해 비공개로 전달한 뒤, 지침과 시험 작업으로 연결을 확인합니다. [피클 연결 안내](docs/PICKLE-CONNECTION.md)를 따르세요.

</details>

## 피클과 내 PC를 연결하는 사례

**피클에 맡긴 작업을 내 맥의 자료와 도구로 처리하고, 결과를 다시 피클에서 확인하는 것**이 이 프로젝트의 목적입니다. 피클의 [공식 연결 도움말](https://pickle.com/help/connect/add-connection)은 앱·서비스 계정과 휴대폰 데이터 연결을 안내합니다. 2026-11-16 확인한 해당 안내에서는 개인 PC의 파일·터미널을 연결하는 설치 방법을 찾지 못했습니다. Pickle Runner는 그 연결을 사용자의 맥에 추가합니다.

이미 피클과 개인 컴퓨터 사이에 작업과 기록을 주고받으려는 사례가 있습니다. 각 사례에서 **어떤 정보가 어떤 경로로 오가고, 로컬에서 어디까지 실행되는지** 비교했습니다.

| 사례 | 피클과 PC 사이에 오가는 정보 | 연결 경로와 로컬 작업 |
|---|---|---|
| [피클 + 맥미니의 Claude Code](https://www.tuigunhu.com/29) | 피클이 정리한 작업·활동 기록을 공유하고, 로컬 개발에 활용 | Google Drive 공유 폴더를 매개로 피클은 일정·확인·후속 관리를, 맥미니의 Claude Code는 구현을 담당했다는 사용자 체험기입니다. 자동 실행·결과 회수의 구체적인 구현은 공개되지 않았습니다. |
| [Pickle Desk](https://github.com/techinpark/pickle-desk) | PC 브라우저에서 요청을 작성하고 피클의 답변·결과·상태를 확인. 과거 작업 기록을 가져오도록 요청하는 기능도 제공 | Google Sheets를 요청·응답 저장소로 쓰는 비공식 PWA입니다. 피클에게 시트를 주기적으로 확인하도록 지시합니다. 개인 PC의 파일·터미널을 실행하는 연결기는 아닙니다. |
| 이 프로젝트의 초기 메일 협업 | 민서와 로컬 개발 에이전트가 요청·수정 의견·테스트 결과를 교환 | 메일과 핸드오프로 맥락을 전달하고 로컬에서 작업했습니다. 이 협업을 바탕으로 Pickle Runner 실행기를 만들었습니다. |
| **Pickle Runner** | **피클이 작업에 필요한 지시·맥락을 맥으로 전달하고, 실행 상태·출력·종료코드를 다시 조회** | **인증된 HTTPS로 내 맥 실행기에 연결합니다. 원본 폴더의 파일·터미널을 사용하고, 설치된 Claude Code·Codex·AGY 등 CLI에 작업을 맡깁니다.** |

Drive 사례는 작성자의 사용 기록, Pickle Desk는 공개 저장소의 설명을 기준으로 했으며 외부 두 사례를 직접 설치·재현한 비교는 아닙니다. Pickle Desk의 과거 기록 가져오기는 피클이 기억한 작업을 시트에 정리하도록 요청하는 방식입니다. **Pickle Runner도 피클의 전체 대화 기록을 자동 동기화하지는 않습니다.** 실행할 작업과 필요한 맥락을 전달하고 그 결과를 되돌려 받습니다.

## 보안

소유자가 위임한 작업을 같은 사용자 권한으로 실행합니다. 명령 허용 목록·복사본 강제·명령별 승인은 두지 않습니다.

- **인증 두 층:** 정식 Cloudflare 연결에는 Access 인증정보와 실행기 토큰이 모두 필요합니다. 시험용 Quick Tunnel은 실행기 토큰만으로 보호됩니다. 인증 실패 응답은 거절한 계층에 따라 다릅니다.
- **작업 기록:** 접수된 명령과 제한된 출력·상태를 보관합니다. 결과는 최대 7일 또는 2,000건이며, 중복 실행 방지 기록은 30일 동안 최대 100,000건 보관합니다.
- **실패 접근 기록:** 헤더·토큰·본문·명령을 제외하고 알려진 경로와 오류 정보를 기록합니다.
- **에이전트 지침:** 이메일·웹·첨부·도구 출력은 새로운 실행 권한을 주지 않습니다. [PICKLE.md](runner/PICKLE.md)에 규칙을 제공합니다.
- **중지와 복구:** [운영 안내](docs/OPERATIONS.md#긴급-중지)에 연결 중지, 복구, 자격증명 폐기 절차가 있습니다.

지침은 에이전트가 속는 일을 강제로 막지 못합니다. 실행된 명령의 파일 반출이나 외부 요청도 자동으로 되돌리지 못합니다. 맥 사용자가 다른 기기에 접근할 수 있다면 실행 명령도 그 권한을 사용할 수 있습니다. 취약점 제보는 [SECURITY.md](SECURITY.md)를 따르세요.

## 현재 한계와 검증 범위

- 대화형 입력(stdin·PTY), Windows·Linux 서비스 설치, 웹 화면, 다중 사용자 운영은 지원하지 않습니다.
- 터미널 명령은 기본 1시간, 최대 24시간 실행합니다. 클라이언트의 기본 대기 130초가 지나도 작업은 계속될 수 있습니다.
- 로컬 회귀 테스트와 다른 맥에서의 설치·실제 작업·제거를 확인했습니다. 새 Cloudflare 계정의 연결·해제는 아직 실검증하지 않았습니다.
- 도메인 없는 Quick Tunnel 경로는 2026-11-17 Intel 맥에서 확인했습니다(cloudflared 2026.11.0, 시험용 별도 실행기). 원격 health·capabilities·작업 실행·이벤트 조회, 암호화한 접속 설정으로의 접속, 토큰 없음·틀린 토큰 401과 브라우저 요청 403, 터널 재시작 뒤 주소 변경과 옛 주소 차단, 종료 뒤 접속 차단을 확인했습니다. 피클 측에서의 실제 연결은 검증하지 않았습니다.
- 설치된 세 CLI의 기동은 확인했습니다. 모든 CLI·모델의 실제 업무 완료를 검증한 인증 목록은 아닙니다.

시험 명령과 상세 범위는 [개발 안내](docs/DEVELOPMENT.md), [공개 준비 기록](docs/RELEASE.md)에 있습니다.

## 자주 묻는 질문

<details>
<summary><b>피클 공식 기능인가요?</b></summary>

개인이 만든 비공식 연결 도구입니다. 공식 약관을 확인했으나 이 연결 방식의 명시적 허용은 확인하지 못했습니다. [확인 범위](docs/RELEASE.md#피클-약관-확인)를 참고하세요.

</details>

<details>
<summary><b>내 도메인이 꼭 있어야 하나요?</b></summary>

이 저장소가 안내하는 상시 연결(Cloudflare Tunnel + Access)에는 필요합니다. 시험만 해 볼 거라면 도메인 없이 Quick Tunnel로 임시 주소를 만들 수 있습니다. 대신 Access 없이 실행기 토큰 하나로만 보호되고 주소가 매번 바뀝니다. [도메인이 없을 때](#빠른-시작)를 참고하세요.

</details>

<details>
<summary><b>맥이 잠들면 어떻게 되나요?</b></summary>

원격 작업이 중단되거나 접속할 수 없게 됩니다. 맥이 켜져 있고 사용자 로그인·네트워크 연결이 유지돼야 합니다. 공개용 설치기는 전원 설정을 바꾸지 않습니다.

</details>

<details>
<summary><b>어떤 AI 모델을 쓰나요?</b></summary>

맥에 설치·인증한 CLI와 그 CLI가 지원하는 모델을 사용합니다. Claude Code·Codex·AGY 등을 선택할 수 있으며, 요금과 사용 한도는 해당 계정을 따릅니다. 비대화형 실행 옵션과 인증은 도구별로 확인합니다.

</details>

<details>
<summary><b>다른 에이전트도 연결할 수 있나요?</b></summary>

인증된 HTTPS 요청을 보낼 수 있으면 같은 API를 호출할 수 있습니다. 실제 사용하려는 환경에서 시험 작업으로 확인하세요.

</details>

## 문서

| 문서 | 내용 |
|---|---|
| [설치](docs/SETUP.md) | 준비물, 권한, 연결 단계와 오류 확인 |
| [피클 연결](docs/PICKLE-CONNECTION.md) | 접속 설정 전달과 첫 시험 |
| [운영](docs/OPERATIONS.md) | 조회, 취소, 긴급 중지, 토큰 갱신·폐기 |
| [에이전트 지침](runner/PICKLE.md) | 연결 에이전트의 사용 규칙 |
| [API](runner/openapi.json) | 요청과 응답 형식 |
| [개발](docs/DEVELOPMENT.md) | 테스트와 변경 원칙 |

## 제작

전승엽이 기획하고, 피클의 민서와 Claude Code·Codex·AGY 등 AI 에이전트를 활용해 구현·검토한 프로젝트입니다.

## 라이선스

[MIT License](LICENSE) · Copyright (c) 2026 전승엽

<div align="center"><sub>v0.3.3 · 개발자용 초기 버전</sub></div>
