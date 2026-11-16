# 에이전트와 함께 설치하기

## 구성 요소

GitHub는 소스와 업데이트를 배포한다. 맥에서는 셸·설치된 CLI·로컬 HTTP 서버·cloudflared가 실행된다. Cloudflare는 HTTPS를 전달하고 Access 자격증명을 확인한다. 원격 에이전트는 실행기 토큰도 제시해야 한다. 맥은 켜져 있고 인터넷에 연결돼 있어야 한다. [Cloudflare Tunnel 안내](https://developers.cloudflare.com/tunnel/)

## 1. 로컬 설치

`python3 runner/setup.py status`로 시작한다. macOS와 Python 3.9 이상을 확인한다. launchd가 절대 경로를 참조하므로 계속 유지할 체크아웃을 선택한다.

```bash
python3 runner/setup.py init --port 8796
python3 runner/manage.py install
python3 runner/client.py health
```

새 설정에는 terminal_enabled=true가 포함된다. init은 기존 설정·비밀값을 보존하며 예전 설정을 자동 변경하지 않는다. 서버는 127.0.0.1에 바인딩한다.

공개판 서비스 이름은 `io.picklerunner.agent`다. 다른 체크아웃의 같은 이름 서비스를 덮어쓰지 않는다. 다른 포트를 지정해도 독립된 두 번째 서비스가 되는 것은 아니다. 이전 설치를 옮길 때는 중단 시간과 기록 보존을 계획한다.

## 2. Cloudflare 연결 대상

활성 DNS 영역이 있는 본인 계정과 사용하지 않는 하위 도메인을 준비한다. 계정 가입·도메인 구매·위임·요금제는 사용자가 정한다. 로컬 사용에는 필요하지 않다.

[공식 배포처](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)나 패키지 관리자로 cloudflared를 설치한다. 예: `brew install cloudflared`. 서비스 설정 때 PATH에서 찾아 절대 경로를 저장한다. 저장소는 바이너리를 포함하지 않는다.

```bash
python3 runner/setup.py cloudflare --zone example.com --hostname runner.example.com \
  --preserve-host app.example.com
```

선택 옵션 `--preserve-host`는 반복할 수 있다. 해당 기존 DNS 레코드를 기록해 이후 바뀌면 진행을 멈추며, 그 레코드를 수정하지 않는다. 새 호스트와 보존 호스트는 달라야 한다. 관리 토큰 검증 후 plan.json이 생기면 호스트·영역 변경을 막아 서로 다른 설치의 자원이 섞이지 않게 한다. DNS 공개 전에 선택한 호스트의 소유 기록을 확인한다.

## 3. 관리 토큰

Cloudflare에서 선택한 계정·영역으로 한정한 사용자 API 토큰을 발행한다. 필요한 권한은 Zone Read, DNS Edit, Cloudflare Tunnel Edit, Access Apps and Policies Edit, Access Service Tokens Edit다. 화면의 이름은 [현재 권한 안내](https://developers.cloudflare.com/fundamentals/api/reference/permissions/)를 따른다. 이 검증 경로는 사용자 토큰용이며 계정 소유 API 토큰은 지원하지 않는다.

`python3 runner/cloudflare_token.py prompt`는 macOS 숨김 입력창을 연다. `save`는 사용자의 대화형 터미널에서 숨김 입력을 받는다. 토큰을 명령 인자·환경 덤프·채팅·공개 이슈에 넣지 않는다. 검증된 토큰과 계획은 .runtime 안에 비공개로 저장된다.

## 4. 연결과 검증

`python3 runner/setup.py connect`는 다음을 수행한다.

1. 로컬 health와 cloudflared를 확인한다.
2. 호스트별 Access 서비스 토큰(720시간), Service Auth 정책, self-hosted Access 앱을 만든다.
3. 전용 터널을 만들고 선택한 호스트만 루프백 포트로 전달한다. 나머지는 404다.
4. 사용자 터널 서비스를 시작하고 정상 연결을 기다린다.
5. 선택한 호스트에 프록시 CNAME을 만든다. 다른 DNS를 덮어쓰지 않는다.
6. 무인증·실행기 인증만 있는 요청은 상위 계층에서 거절되고, Access 인증만 있으면 실행기에서 거절되며, 두 인증을 갖추면 health 200인지 확인한다.
7. 만료 정보를 저장하고 로컬 관리 API 토큰 사본을 지운다. 파일 삭제로 제공자의 토큰 자체가 폐기되지는 않는다.

중간 실패 뒤에는 생성된 자원이 남을 수 있다. `.runtime/cloudflare-setup`의 비공개 진행 기록을 비밀값을 출력하지 않는 방법으로 확인하고 같은 설정으로 재시도한다. 원격 자원이 남을 수 있으므로 기록을 무작정 지우고 재실행하지 않는다. 자동 롤백은 없다. DNS 전파 지연이면 `check_remote.py`로 자원 생성 없이 재확인할 수 있다.

새 계정의 전체 연결은 아직 실검증하지 않았다. 참고: [터널 API 설정](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel-api/), [서비스 토큰](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/).

## 5. 피클에 전달하기

`.runtime/pickle-runner/client-remote.json`은 실제 자격증명이다. 권한 0600으로 보관하고 사용자가 정한 비공개 경로로만 전달한다. RSA4096·OAEP-SHA256 암호화와 첫 시험은 [피클 연결 안내](PICKLE-CONNECTION.md)를 따른다. 자동 업로드·메일 발신은 하지 않는다.

피클에게 runner/PICKLE.md를 읽히고 capabilities 조회와 임시 폴더 시험을 맡긴다. 실제 맥 파일과 결과를 대조한다. API 성공만으로 모든 간접 지시 공격을 막는다고 결론 내리지 않는다.

## 중간 실패 확인

connect의 `stage`로 실패 위치를 확인한다. 원문 예외에는 비밀값이 포함될 수 있어 출력하지 않는다.

| stage | 확인할 내용 |
|---|---|
| prerequisites | macOS와 cloudflared 설치 |
| local_health | manage.py install과 로컬 health |
| load_checkpoint | 저장한 계획과 숨김 입력한 관리 토큰 |
| provision | 계정 권한과 같은 이름의 기존 자원 |
| start_tunnel / tunnel_health | cloudflared와 이 설치의 LaunchAgent |
| publish_dns | 선택한 호스트의 기존 레코드와 소유 기록 |
| remote_auth | 함께 출력된 인증 조합별 HTTP 상태·통과 여부, DNS·Access 전파 |
| credential_metadata | 서비스 토큰 ID와 만료 조회 |
| remove_setup_token | 검증 후 로컬 관리 토큰 삭제 권한 |

원인을 해결한 뒤 같은 설정으로 connect를 재실행한다. 검증·만료 조회가 성공할 때까지 관리 토큰을 보존한다.

**connect/provision을 한 번도 시도하지 않은 상태**에서 호스트 오타를 발견했다면 plan.json과 api-token만 제거하고 cloudflare 설정·토큰 입력을 다시 한다. 프로비저닝을 시도했다면 resources.json이 없어도 원격 자원부터 확인한다. 생성 직후 기록 전에 중단됐을 수 있으므로 다른 호스트로 덮어쓰지 않는다.
