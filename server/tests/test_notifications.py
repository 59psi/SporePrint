import time
from unittest.mock import AsyncMock, patch

from app.notifications.service import notify, _last_sent


async def test_notify_sends_request(monkeypatch):
    monkeypatch.setattr("app.config.settings.ntfy_url", "http://test:80")
    monkeypatch.setattr("app.config.settings.ntfy_topic", "test")

    with patch("app.notifications.service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await notify("Title", "Message")
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert "http://test:80/test" in call_kwargs.args or call_kwargs.args[0] == "http://test:80/test"


async def test_dedup_same_key_within_window(monkeypatch):
    monkeypatch.setattr("app.config.settings.ntfy_url", "http://test:80")
    monkeypatch.setattr("app.config.settings.ntfy_topic", "test")

    with patch("app.notifications.service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await notify("Title", "Msg", dedup_key="key1", dedup_seconds=300)
        await notify("Title", "Msg", dedup_key="key1", dedup_seconds=300)
        assert mock_client.post.call_count == 1


async def test_dedup_different_keys_pass(monkeypatch):
    monkeypatch.setattr("app.config.settings.ntfy_url", "http://test:80")
    monkeypatch.setattr("app.config.settings.ntfy_topic", "test")

    with patch("app.notifications.service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await notify("Title", "Msg", dedup_key="key1", dedup_seconds=300)
        await notify("Title", "Msg", dedup_key="key2", dedup_seconds=300)
        assert mock_client.post.call_count == 2


async def test_dedup_expired_window_passes(monkeypatch):
    monkeypatch.setattr("app.config.settings.ntfy_url", "http://test:80")
    monkeypatch.setattr("app.config.settings.ntfy_topic", "test")

    with patch("app.notifications.service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await notify("Title", "Msg", dedup_key="key1", dedup_seconds=1)
        # Manually expire the entry
        _last_sent["key1"] = time.time() - 10
        await notify("Title", "Msg", dedup_key="key1", dedup_seconds=1)
        assert mock_client.post.call_count == 2


async def test_priority_mapping(monkeypatch):
    monkeypatch.setattr("app.config.settings.ntfy_url", "http://test:80")
    monkeypatch.setattr("app.config.settings.ntfy_topic", "test")

    for priority, expected_header in [("critical", "5"), ("warning", "4"), ("info", "3")]:
        _last_sent.clear()
        with patch("app.notifications.service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await notify("Title", "Msg", priority=priority)
            headers = mock_client.post.call_args.kwargs.get("headers", {})
            assert headers.get("Priority") == expected_header, f"priority={priority}"


async def test_notify_no_url_noop(monkeypatch):
    monkeypatch.setattr("app.config.settings.ntfy_url", "")

    with patch("app.notifications.service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await notify("Title", "Msg")
        mock_client.post.assert_not_called()
