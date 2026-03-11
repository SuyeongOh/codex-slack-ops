# Codex Slack Approvals

`FastAPI + Slack Bolt + Postgres + Redis` 기반의 승인 오케스트레이터입니다. Codex 또는 별도 실행기가 제안한 명령을 즉시 실행하지 않고, Slack 버튼 승인 후에만 진행하도록 앞단에서 제어합니다.

## 구성 요소

- `FastAPI`: 내부 승인 API, 상태 조회, Slack 요청 진입점
- `Slack Bolt`: 버튼 액션, 상세 보기 모달, Slack 요청 서명 검증
- `Postgres`: 승인 요청과 상태 전이의 영속 저장소
- `Redis`: 버튼 중복 클릭과 경쟁 조건을 줄이기 위한 짧은 락
- `scripts/approval_runner.py`: 실제 명령을 승인 후 실행하고 실행 상태를 보고하는 CLI runner

## Placeholder Values

이 저장소를 다른 서버나 다른 Slack workspace로 옮길 때는 아래 값을 직접 채워야 합니다.

- `SLACK_BOT_TOKEN=<xoxb-your-bot-token>`
- `SLACK_SIGNING_SECRET=<your-slack-signing-secret>`
- `SLACK_TEAM_ID=<your-slack-team-id>`
- `SLACK_ALLOWED_APPROVER_IDS=<comma-separated-slack-user-ids>`
- `SLACK_DEFAULT_CHANNEL_ID=<approval-channel-id>`
- `INTERNAL_API_TOKEN=<generate-a-random-secret>`

## 지원 흐름

1. 외부 실행기나 runner가 `POST /api/v1/approvals` 호출
2. 서비스가 `pending` 승인 요청을 저장하고 Slack에 버튼 메시지 게시
3. 승인자가 `Approve` 또는 `Reject` 클릭
4. 상태가 `approved` 또는 `rejected`로 전이
5. runner가 승인 상태를 poll 하고, 승인 시 실제 명령 실행
6. runner가 `executing`, `completed`, `failed` 상태를 다시 보고

## 1. 설정 파일 생성

현재 로컬 Codex Slack MCP 설정을 이용해 `.env`를 생성하려면:

```bash
cd <approval-app-dir>
python scripts/bootstrap_codex_slack_env.py
```

이 스크립트는 다음을 자동 반영합니다.

- `~/.codex/config.toml`의 `SLACK_BOT_TOKEN`
- `~/.codex/config.toml`의 `SLACK_TEAM_ID`
- `INTERNAL_API_TOKEN`
- 랜덤 `INTERNAL_API_TOKEN`

직접 채워야 하는 값:

- `SLACK_SIGNING_SECRET`
- `SLACK_DEFAULT_CHANNEL_ID`
- `SLACK_ALLOWED_APPROVER_IDS`

Slack App 설정 화면의 `Basic Information > App Credentials`에서 `SLACK_SIGNING_SECRET`를 복사한 뒤 `.env`에 넣으면 됩니다.

다른 서버나 다른 Slack workspace로 옮길 때는 [`.env.template`](.env.template)를 복사해서 placeholder를 직접 채우는 방식이 더 적합합니다.

## 2. 로컬 실행

기본 bootstrap은 `SQLite + in-memory lock` 조합으로 `.env`를 만들기 때문에 Docker 없이 바로 띄울 수 있습니다.

```bash
cd <approval-app-dir>
python -m venv .venv
. .venv/bin/activate
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/pip install .
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Docker를 쓰는 경우에는 `.env`의 `DATABASE_URL`, `REDIS_URL`만 Postgres/Redis 값으로 바꾸면 됩니다.

```bash
docker compose up --build
```

## 3. Slack App 설정

- Interactivity Request URL: `https://<your-host>/slack/interactions`
- Event Subscriptions Request URL: `https://<your-host>/slack/events`

필수 scope:

- `chat:write`
- `channels:read`
- `channels:history`
- `groups:read` 필요 시

현재 MCP bot token은 `users:read` 없이도 동작하도록 설계되어 있습니다. 승인자 검증은 버튼 payload의 `user.id`와 `SLACK_ALLOWED_APPROVER_IDS` 비교로 처리합니다.

## 4. 실제 명령 실행 runner

서비스가 뜬 뒤에는 `scripts/approval_runner.py`를 바로 사용할 수 있습니다.

```bash
cd <approval-app-dir>
python scripts/approval_runner.py \
  --title "Run sample command" \
  --command "pwd && ls -la" \
  --rationale "manual approval test" \
  --risk-level medium \
  --requested-by codex-runner
```

동작:

- 승인 요청을 `SLACK_DEFAULT_CHANNEL_ID`에 게시
- Slack 버튼 승인을 기다림
- 승인되면 명령 실행
- 실행 결과를 서비스에 다시 보고
- runner stdout에는 `approval created`, `approval status`, `execution status`, `execution exit_code` 같은 lifecycle marker가 출력됩니다

## 승인 API 예시

```bash
curl -X POST http://localhost:8000/api/v1/approvals \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: replace-me" \
  -d '{
    "title": "Deploy main to production",
    "command": "git push origin main && ./deploy-prod.sh",
    "rationale": "production write detected",
    "risk_level": "high",
    "requested_by": "codex-runner",
    "channel_id": "<approval-channel-id>",
    "context": {
      "repo": "acme/api",
      "environment": "production"
    }
  }'
```

## 상태 전이

- `pending -> approved`
- `pending -> rejected`
- `pending -> expired`
- `approved -> executing`
- `executing -> completed`
- `executing -> failed`

## 운영 메모

- `SLACK_ALLOWED_APPROVER_IDS`로 승인 가능 사용자를 제한합니다.
- 모든 상태 전이는 Postgres에서 조건부 업데이트로 처리합니다.
- Redis가 없으면 `memory://` 기반 단일 프로세스 락으로 동작합니다.
- 현재 버전은 `create_all()` 기반 초기화입니다. 운영 전환 시 Alembic migration 추가를 권장합니다.
- `SLACK_SIGNING_SECRET`이 placeholder 상태면 Slack 버튼 클릭은 검증에 실패합니다.
