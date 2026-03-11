# Codex Slack Approval Workflow Migration Guide

이 문서는 현재 구현한 Slack button approval workflow를 다른 서버에 그대로 이식하기 위한 운영 문서입니다.

문서 안의 placeholder 표기:

- `<user>`: target server의 실제 Linux username
- `<home>`: 보통 `/home/<user>`
- `<approval-app-dir>`: 보통 `/home/<user>/codex-slack-approvals`
- `<bin-dir>`: 보통 `/home/<user>/bin`
- `<codex-bin>`: target server에서 실제 `codex` binary path
- `<public-host>`: Slack이 접근 가능한 public HTTPS host
- `<bot-token>`: Slack Bot Token (`xoxb-...`)
- `<signing-secret>`: Slack Signing Secret
- `<team-id>`: Slack workspace team id (`T...`)
- `<approval-channel-id>`: approval message를 올릴 Slack channel id (`C...`)
- `<approver-user-ids>`: 승인 가능한 Slack user id comma-separated (`U...,U...`)

목표:

- 다른 서버에서도 `codex-slack` wrapper로 Codex를 실행
- side-effecting command는 Slack approval runner를 통해 승인
- Slack에서 `Approve` / `Reject` 버튼 클릭
- 승인 후 command 실행, thread status logging, parent message 상태 갱신

## 1. 구성 개요

현재 구성 요소:

- Approval service:
  - FastAPI + Slack Bolt
  - approval 상태 저장
  - Slack button callback 처리
  - thread reply / message update
- Approval runner:
  - approval 생성
  - approval poll
  - 승인 시 command 실행
  - 실행 결과 보고
- Codex wrapper:
  - `codex-slack`
  - approval service env 주입
  - service 미기동 시 자동 start
- Service manager:
  - `codex-slack-service`
  - start / stop / restart / status / logs
- Global Codex instruction:
  - Slack approval env가 있으면 built-in approval 대신 runner 우선 사용

핵심 경로:

- Approval app root:
  - `<approval-app-dir>`
- Approval runner:
  - `<approval-app-dir>/scripts/approval_runner.py`
- Wrapper:
  - `<bin-dir>/codex-slack`
- Service manager:
  - `<bin-dir>/codex-slack-service`
- Global Codex config:
  - `<home>/.codex/config.toml`

## 2. 다른 서버에 복사할 파일

최소 복사 대상:

- `<approval-app-dir>`
- `<bin-dir>/codex-slack`
- `<bin-dir>/codex-slack-service`

직접 복사하지 말고 target server에 맞게 수정이 필요한 파일:

- `~/.codex/config.toml`
- `~/.bashrc`
- `<approval-app-dir>/.env`

## 3. 서버 요구사항

필수:

- Python 3.8+
- Codex CLI 설치
- Slack App Bot Token
- Slack App Signing Secret
- Slack workspace/channel access

선택:

- Redis / Postgres
  - 없어도 동작 가능
  - 기본 fallback은 `SQLite + memory lock`
- public HTTPS endpoint
  - Slack Interactivity 실제 버튼 클릭용
  - reverse proxy, ngrok, pinggy, cloudflared 등 가능

## 4. 프로젝트 설치

target server 예시:

```bash
mkdir -p /home/<user>
cp -R codex-slack-approvals /home/<user>/codex-slack-approvals
mkdir -p /home/<user>/bin
cp codex-slack /home/<user>/bin/codex-slack
cp codex-slack-service /home/<user>/bin/codex-slack-service
chmod +x /home/<user>/bin/codex-slack
chmod +x /home/<user>/bin/codex-slack-service
```

venv 설치:

```bash
cd /home/<user>/codex-slack-approvals
python -m venv .venv
. .venv/bin/activate
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/pip install .
```

## 5. `.env` 설정

현재 구현은 `.env`를 사용합니다.

다른 서버 이식 시에는 [`.env.template`](.env.template)를 `.env`로 복사한 뒤 placeholder를 치환하는 방식을 권장합니다.

예시:

```env
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
BASE_URL=http://localhost:8000
INTERNAL_API_TOKEN=replace-with-random-secret

DATABASE_URL=sqlite+aiosqlite:///./approvals.db
REDIS_URL=memory://

SLACK_BOT_TOKEN=<bot-token>
SLACK_SIGNING_SECRET=<signing-secret>
SLACK_TEAM_ID=<team-id>
SLACK_ALLOWED_APPROVER_IDS=<approver-user-ids>
SLACK_DEFAULT_CHANNEL_ID=<approval-channel-id>

APPROVAL_TTL_SECONDS=600
REDIS_LOCK_TTL_SECONDS=10
EXPIRATION_SWEEP_SECONDS=15
```

권장:

- 초기 배포는 `SQLite + memory://`로 먼저 올리기
- 운영 안정화 후 Postgres / Redis로 전환

## 6. Slack App 설정

필수:

- `chat:write`
- `channels:read`
- `channels:history`
- `groups:read` 필요 시

필수 설정:

- `Interactivity & Shortcuts`
  - On
  - Request URL:
    - `https://<public-host>/slack/interactions`

선택 설정:

- `Event Subscriptions`
  - 현재 button workflow만 쓰면 필수 아님
  - 나중에 `app_mention`, `reaction_added` 등을 붙일 때 사용
  - Request URL:
    - `https://<public-host>/slack/events`

주의:

- Slack button은 반드시 public HTTPS callback URL이 필요함
- `SLACK_SIGNING_SECRET` 없으면 button callback verification 실패

## 7. Approval service 실행

직접 실행:

```bash
cd /home/<user>/codex-slack-approvals
. .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

service manager 사용:

```bash
/home/<user>/bin/codex-slack-service start
/home/<user>/bin/codex-slack-service status
/home/<user>/bin/codex-slack-service logs
```

health check:

```bash
curl http://127.0.0.1:8000/healthz
```

정상 응답:

```json
{"status":"ok"}
```

## 8. Codex 글로벌 설정 반영

`~/.codex/config.toml`의 `developer_instructions` 안에 아래 의미가 들어가야 합니다.

핵심 정책:

- `APPROVAL_BASE_URL`와 `INTERNAL_API_TOKEN`이 있으면
  - built-in approval prompt 대신
  - `approval_runner.py`를 우선 사용
- read-only command는 runner로 보내지 않음
- install, delete, restart, deploy, git push, db change, network write 같은 command는 runner 사용
- env가 없거나 approval service가 죽어 있으면 normal Codex approval fallback

target server에서는 아래 path를 정확히 바꿔야 합니다:

- `<approval-app-dir>/scripts/approval_runner.py`

## 9. Wrapper 스크립트 반영

### `codex-slack`

역할:

- `.env` load
- `APPROVAL_BASE_URL`, `INTERNAL_API_TOKEN` export
- service 자동 start
- 이후 `codex` 실행

수정 포인트:

- `APP_DIR`
- `ENV_FILE`
- `SERVICE_BIN`
- `CODEX_BIN`

target server 예시:

- `APP_DIR=<approval-app-dir>`
- `SERVICE_BIN=<bin-dir>/codex-slack-service`
- `CODEX_BIN=<codex-bin>`

### `codex-slack-service`

역할:

- approval service background start/stop/status
- log file 및 pid file 관리

수정 포인트:

- `APP_DIR`
- `ENV_FILE`
- `PID_FILE`
- `LOG_FILE`

## 10. Shell alias

`~/.bashrc`에 다음 추가:

```bash
export PATH=~/bin:$PATH
alias codex='codex-slack'
alias codex-plain='<codex-bin>'
alias cslack='codex-slack'
alias cslacksvc='codex-slack-service'
```

반영:

```bash
source ~/.bashrc
```

## 11. 실사용 방식

기존 plain Codex:

```bash
codex
```

Slack approval workflow 적용 Codex:

```bash
cslack
```

non-interactive 예시:

```bash
cslack exec --skip-git-repo-check -C /path/to/workspace "Do the requested task."
```

## 12. 승인 흐름

1. Codex가 side-effecting shell command를 계획
2. global instruction이 runner 사용을 유도
3. `approval_runner.py`가 approval API 호출
4. Slack에 pending approval message 생성
5. 사용자가 Slack에서 `Approve` 또는 `Reject`
6. parent message 상태 갱신
7. thread에 status reply 기록
8. 승인 시 runner가 실제 command 실행
9. `executing`, `completed` 또는 `failed` 상태 반영

## 13. 현재 구현된 UX

parent message:

- pending 상태에서 button 노출
- terminal 상태에서는 button 제거
- `Decision` section으로 대체

thread replies:

- approval recorded
- execution started
- execution completed / failed
- expired

runner stdout marker:

- `approval created: ...`
- `approval message: ...`
- `waiting for approval...`
- `approval status: ...`
- `execution status: executing`
- `execution status: completed|failed`
- `execution exit_code: ...`

이 marker 덕분에 Codex session이나 terminal에서 “완료 여부”를 자동 판단하기 쉬워짐

## 14. 검증 체크리스트

### A. 로컬 서비스 검증

```bash
cslacksvc status
curl http://127.0.0.1:8000/healthz
```

### B. Slack posting 검증

approval API 또는 runner 실행 후:

- approval channel에 message 생성되는지 확인

### C. Signed callback 검증

local signed request 또는 실제 button click으로:

- `POST /slack/interactions` 200 확인
- parent message 상태 변경 확인
- thread reply 생성 확인

### D. 실제 command 실행 검증

test command 예시:

```bash
printf %s probe_value > /tmp/probe_file.txt
```

확인:

```bash
cat /tmp/probe_file.txt
```

## 15. 실제 운영에서 확인된 working scenario

이미 검증된 흐름:

- `codex-slack exec`
- Slack pending approval message 생성
- 실제 Slack button click
- external public callback URL로 request 유입
- runner가 승인 상태 인식
- command 실행
- thread에 `approved`, `execution started`, `execution completed`
- target file 실제 생성

## 16. Known issues / 개선 권장

1. `codex-slack-service` PID 관리

- 아주 빠른 중복 start race가 있으면 pid file이 실패한 프로세스로 덮일 수 있음
- 현재는 healthcheck 기준으로 재확인 가능
- 운영용으로는 pid write 전에 port bind 상태 확인하거나 `flock` 추가 권장

2. Public URL 안정성

- `pinggy`, `ngrok`, `localtunnel` 같은 임시 tunnel은 URL이 바뀔 수 있음
- 운영에서는 reverse proxy + fixed domain 권장

3. Storage backend

- 초기엔 `SQLite + memory lock`로 충분
- multi-process / multi-host면 Postgres + Redis 권장

4. Codex built-in approval와의 관계

- 현재 설계는 plain `codex`를 완전히 대체하지 않음
- Slack workflow는 `codex-slack` 경로에서 우선 사용
- fallback safety를 위해 Codex의 normal approval flow는 남겨두는 편이 안전

## 17. 운영 추천값

권장 운영 형태:

- plain `codex`: 기존 용도 유지
- `codex-slack`: side-effecting 작업용
- fixed domain:
  - `https://codex-approval.<your-domain>/slack/interactions`
- backend:
  - Postgres
  - Redis
- process manager:
  - systemd 또는 supervisor

## 18. 이식 후 바로 해야 할 일

1. project copy
2. `.venv` 설치
3. `.env` 작성
4. placeholder 치환
5. `SLACK_SIGNING_SECRET` 확인
6. `cslacksvc start`
7. public HTTPS URL 연결
8. Slack App `Interactivity` Request URL 저장
9. test approval 생성
10. 실제 button click
11. target file 생성 확인

## 19. 파일별 역할 요약

- `app/main.py`
  - FastAPI entrypoint
- `app/slack_app.py`
  - Slack button action handler
- `app/services/approval_service.py`
  - approval 상태 전이
- `app/services/slack_service.py`
  - Slack post/update/thread reply
- `app/slack_ui.py`
  - Slack Block Kit UI
- `scripts/approval_runner.py`
  - approval create / wait / execute / report
- `scripts/bootstrap_codex_slack_env.py`
  - local Codex config 기반 `.env` bootstrap
- `~/bin/codex-slack`
  - wrapper
- `~/bin/codex-slack-service`
  - service control

## 20. 운영 인수인계 메모

이 구성은 “Codex built-in approval prompt를 외부에서 가로채는 방식”이 아닙니다.

대신:

- Codex에게 global instruction으로 runner 사용을 유도하고
- `codex-slack` wrapper가 approval env를 주입하고
- approval service가 Slack button approval을 처리하는 구조입니다

즉, 다른 서버로 이식할 때도 가장 중요한 것은:

- path 정리
- env 정리
- public callback URL 정리
- Slack App Interactivity 연결

위 4개입니다.

## 21. 가장 먼저 치환할 값

다른 서버에 문서를 넘길 때 아래 값부터 실제 환경 값으로 바꾸면 됩니다.

- `<user>`
- `<home>`
- `<approval-app-dir>`
- `<bin-dir>`
- `<codex-bin>`
- `<bot-token>`
- `<signing-secret>`
- `<team-id>`
- `<approval-channel-id>`
- `<approver-user-ids>`
- `<public-host>`
