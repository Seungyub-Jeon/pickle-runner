# 운영 안내

`client.py health`, `state`, `events --since CURSOR`, `get --job-id ID`로 기록된 실행 상태를 조회한다. 클라이언트의 기본 대기는 130초이며 대기 종료는 작업 취소가 아니다. `cancel --job-id ID --wait`는 취소 요청 후 상태를 조회한다. 분리된 자식 프로세스까지 종료된다고 보장하지 않는다.

사용자 LaunchAgent는 로그인 후 실행된다. FileVault 잠금 해제 전에는 동작하지 않는다. 잠자기·네트워크 단절은 원격 접근을 중단시킨다. 이 설치기는 전원 설정을 변경하지 않는다.

## 긴급 중지

해당 체크아웃에서 실행한다.

```bash
launchctl disable "gui/$(id -u)/io.picklerunner.agent"
launchctl disable "gui/$(id -u)/io.picklerunner.tunnel"
python3 runner/manage.py stop
launchctl bootout "gui/$(id -u)/io.picklerunner.tunnel"
```

두 서비스가 launchctl print에서 사라지는지 확인한다. disable은 다음 로그인에도 유지되고 bootout만으로는 유지되지 않는다. 이미 없는 서비스와 실제 오류를 구분한다. 로컬 연결 실패와 정상 인증을 포함한 외부 health 실패를 확인한다. 무인증 401만으로 실행기 중지를 증명할 수 없다. 다른 사용자 작업을 종료하지 말고 이 작업에서 남은 프로세스만 식별해 확인한다.

## 복구

기존 plist를 보존한 상태라면:

```bash
launchctl enable "gui/$(id -u)/io.picklerunner.agent"
launchctl enable "gui/$(id -u)/io.picklerunner.tunnel"
python3 runner/manage.py install
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/io.picklerunner.tunnel.plist"
python3 runner/client.py health
python3 runner/check_remote.py --config .runtime/pickle-runner/client-remote.json
```

이미 등록된 터널을 다시 bootstrap하지 않는다. 재시작 시 미완료 작업은 재실행하지 않고 interrupted로 기록한다. 새 ID로 재시도하기 전에 원본 파일을 확인한다.

## 자격증명과 갱신

클라이언트 설정은 실제 비밀값이므로 권한 0600으로 비공개 보관·전달한다. Access 서비스 토큰은 720시간(30일)으로 발급되며 자동 갱신은 없다. health의 만료 상태는 저장된 정보이며 제공자 실시간 조회가 아니다.

관리 API 토큰을 숨김 입력한 뒤 `python3 runner/cloudflare_connect.py renew`로 기간을 갱신한다. 외부 인증을 확인하고 `python3 runner/credentials.py forget-setup-token`으로 로컬 관리 토큰을 지운다. 기간 갱신은 유출된 비밀값 교체가 아니다.

유출이 의심되면 다음 절차를 별도로 수행한다.

1. 긴급 중지 후 Cloudflare Zero Trust의 서비스 토큰 관리 화면에서 이 설치의 Access 토큰을 폐기한다. 전용 자원 ID는 비공개 resources.json을 따른다.
2. 실행기를 내린 상태에서 `.runtime/pickle-runner/agent-token`을 새 무작위 값으로 바꾸고 client-local.json·client-remote.json의 token도 함께 바꾼다. 값을 출력하지 않고 파일 권한 0600을 유지한다.
3. 새 Access 자격증명과 실행기 토큰을 담은 접속 설정을 수신자 공개키로 암호화해 비공개로 다시 전달한다. 기존 암호문은 더 이상 사용하지 않는다.
4. 실제 노출 범위에 따라 터널 토큰·관리 API 토큰·CLI 세션과 SSH 키를 폐기·교체한다. 다른 기기에 등록된 authorized_keys도 확인한다. 원격 관리 키를 지우기 전에 대체 접속을 확보한다.
5. 복구 후 이전 자격증명이 거절되고 새 자격증명의 인증 네 조합이 의도대로 동작하는지 확인한다.

## 기록 보관

전체 결과는 최대 7일·2,000건, 중복 방지 기록은 30일·100,000건, 사건은 30일·20,000건이다. 실패 로그는 256KiB와 백업 두 개로 순환하며 본문·명령·쿼리·토큰을 기록하지 않는다. 알 수 없는 경로나 action은 unrecognized로 기록한다. 프로젝트 실행 복사본과 백업은 자동 정리되지 않으므로 별도로 관리한다.

실패 작업을 복구하려고 실행 중인 DB를 지우지 않는다. SQLite 일관성을 지키는 비공개 백업과 이미 파일을 변경했을 수 있는 작업 기록을 보존한다.

## 연결을 영구 제거하기

긴급 중지 후 실행기·터널이 내려간 것을 확인한다. `python3 runner/manage.py uninstall`을 실행하고, ProgramArguments가 이 체크아웃을 가리키는지 확인한 터널 plist만 제거한다: `$HOME/Library/LaunchAgents/io.picklerunner.tunnel.plist`. 의도적으로 다시 설치하기 전까지 두 라벨을 비활성 상태로 둔다.

Cloudflare에서는 `.runtime/cloudflare-setup/resources.json`의 ID로 이 설치의 자원만 확인한다. 선택한 호스트의 dns_record_id를 먼저 제거하고, 전용 access_app_id·policy_id를 삭제한 뒤 service_token_id를 폐기하고 tunnel_id를 삭제한다. 기록이 없는 중간 생성 자원은 대시보드에서 별도로 확인하며 비슷한 표시 이름만으로 삭제하지 않는다. 관리 API 토큰도 발급 계정에서 별도로 폐기한다.

호스트가 더 이상 실행기로 연결되지 않는지 확인한다. 수신자 설정 사본을 폐기하고 이 체크아웃의 비공개 기록은 백업 필요에 맞춰 보관·제거한다. 로컬 uninstall은 Cloudflare 자원과 수신자 자격증명을 삭제하지 않는다.

## 레거시 프로젝트 도구

`project.*`와 `summarize_workspace.py`는 호환용으로 유지한다. 새 설치에서는 해당 프로젝트·도구 설정을 활성화하지 않는다. 이전 프로젝트 CLI 어댑터에는 고정 Codex 모델과 priority 설정이 있다. 설치된 Claude Code·Codex·AGY 등과 선택한 모델·계정을 쓰려면 `terminal.run`을 사용한다. README의 모델 비종속 설명은 이 직접 실행 경로를 뜻한다.
