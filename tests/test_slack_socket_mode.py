from types import SimpleNamespace

import pytest

from app.slack_app import build_slack_app, build_socket_mode_handler


@pytest.fixture
def anyio_backend():
    return "asyncio"


class DummySlackService:
    async def post_ephemeral_feedback(self, **kwargs):
        return kwargs

    async def open_details_modal(self, **kwargs):
        return kwargs


def make_approval_service():
    return SimpleNamespace(
        slack_service=DummySlackService(),
        approve_request=None,
        reject_request=None,
        get_request=None,
    )


def test_build_slack_app_supports_socket_mode_without_signing_secret():
    approval_service = make_approval_service()

    app = build_slack_app(
        bot_token="xoxb-test-token",
        signing_secret="",
        approval_service=approval_service,
        socket_mode=True,
    )

    assert app is not None


@pytest.mark.anyio
async def test_build_socket_mode_handler_uses_explicit_app_token():
    approval_service = make_approval_service()
    app = build_slack_app(
        bot_token="xoxb-test-token",
        signing_secret="",
        approval_service=approval_service,
        socket_mode=True,
    )

    handler = build_socket_mode_handler(slack_app=app, app_token="xapp-test-token")

    assert handler.app_token == "xapp-test-token"
    await handler.close_async()
