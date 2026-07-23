"""Tests for friendly FA integration error mapping (fa-session.md error UX).

FA / Radar integration failures must become a readable Chinese chat reply,
never a raw exception or HTTP 500. Each Radar failure mode maps to a distinct,
accurate message — and we never echo the raw exception text.
"""

from __future__ import annotations

from ee_wiki.common.errors import ConfigError, IntegrationError
from ee_wiki.integrations.fa_errors import format_fa_error, is_radar_timeout


def test_config_error_kerberos_is_friendly() -> None:
    """No Kerberos / radarclient not importable -> credentials hint, no raw text."""
    err = ConfigError(
        "Failed to construct RadarClient (SPNego). "
        "Ensure AppleConnect / Kerberos ticket is valid on this host"
    )
    msg = format_fa_error(err)
    assert msg.startswith("## FA 集成提示")
    assert "Kerberos" in msg or "AppleConnect" in msg
    assert "radarclient" in msg
    assert "EE-Wiki 知识库" in msg  # actionable continuation
    # Raw exception internals must not leak into the chat.
    assert "Failed to construct RadarClient" not in msg
    assert "SPNego" not in msg


def test_integration_error_acl_maps_to_permission_message() -> None:
    """Radar 403 / ACL rejection -> explicit permission message (not generic)."""
    err = IntegrationError("radar_for_id(101) failed: HTTPError('403 Forbidden')")
    msg = format_fa_error(err, radar_id="101")
    assert "ACL" in msg
    assert "rdar://101" in msg
    assert "HTTPError" not in msg  # no raw leak


def test_integration_error_not_found() -> None:
    """Wrong / unsynced ticket -> missing-ticket message."""
    err = IntegrationError("Attachment 'x.log' not found on stub rdar://101")
    msg = format_fa_error(err, radar_id="101")
    assert "不存在" in msg or "无法读取" in msg
    assert "rdar://101" in msg


def test_integration_error_generic() -> None:
    """Opaque Radar failure -> friendly fallback (details stay server-side)."""
    err = IntegrationError("radar_for_id(101) failed: some opaque error")
    msg = format_fa_error(err, radar_id="101")
    assert "Radar 操作失败" in msg
    assert "服务端日志" in msg


def test_integration_error_timeout_maps_to_timeout_message() -> None:
    """IdMS / urlopen Errno 60 -> explicit timeout guidance (not generic)."""
    err = IntegrationError(
        "radar_for_id(182787079) failed: "
        "<urlopen error [Errno 60] Operation timed out>"
    )
    msg = format_fa_error(err, radar_id="182787079")
    assert "超时" in msg
    assert "VPN" in msg or "AppleConnect" in msg
    assert "Radar 操作失败" not in msg
    assert "rdar://182787079" in msg
    assert "timed out" not in msg  # no raw leak
    assert "Errno 60" not in msg


def test_timeout_error_type_maps_to_timeout_message() -> None:
    """Bare TimeoutError (lab acquire_radar_access_token) -> timeout copy."""
    msg = format_fa_error(TimeoutError("Operation timed out"), radar_id="1")
    assert "超时" in msg
    assert "Radar 操作失败" not in msg


def test_is_radar_timeout_walks_cause_chain() -> None:
    """Wrapped URLError / TimeoutError still counts as retryable timeout."""
    from urllib.error import URLError

    inner = TimeoutError("timed out")
    wrapped = URLError(inner)
    outer = IntegrationError(f"radar_for_id(1) failed: {wrapped}")
    outer.__cause__ = wrapped
    assert is_radar_timeout(outer) is True
    assert is_radar_timeout(IntegrationError("403 Forbidden")) is False


def test_attachment_timeout_inline() -> None:
    line = format_fa_error(
        IntegrationError("download failed: timed out"),
        context="attachment",
        style="inline",
    )
    assert "超时" in line
    assert "##" not in line


def test_attachment_context_inline_style() -> None:
    """Per-attachment failure -> concise one-liner (no markdown header)."""
    err = IntegrationError("Failed to download 'a.log' from rdar://101: 403")
    line = format_fa_error(err, context="attachment", style="inline")
    assert "附件" in line
    assert "##" not in line  # inline has no header
    assert "rdar://" not in line  # inline is concise
    assert "403" not in line  # no raw leak


def test_attachment_context_not_found_inline() -> None:
    err = IntegrationError("Attachment 'a.log' not found on stub rdar://101")
    line = format_fa_error(err, context="attachment", style="inline")
    assert "附件未找到" in line


def test_not_logged_in_appleconnect_session_exception() -> None:
    """Real radarclient shape: bare Exception, NOT ConfigError.

    `Exception: No AppleConnect session established, please log in`
    must map to the credentials hint, not generic / ACL.
    """
    err = Exception("No AppleConnect session established, please log in")
    msg = format_fa_error(err, radar_id="101")
    assert "AppleConnect 会话未建立" in msg
    assert "rdar://101" in msg
    # Raw exception text must not leak into the chat.
    assert "No AppleConnect session established" not in msg
    assert "please log in" not in msg
    assert "Exception" not in msg


def test_no_permission_component_owner_message() -> None:
    """Real radarclient shape for ACL rejection.

    `You can contact the Component Owner - xxx xxx (f_xxx@apple.com)
    to get access to this problem.` must map to the permission message,
    not the generic fallback.
    """
    err = IntegrationError(
        "You can contact the Component Owner - xxx xxx (f_xxx@apple.com) "
        "to get access to this problem."
    )
    msg = format_fa_error(err, radar_id="101")
    assert "权限" in msg or "ACL" in msg
    assert "Component Owner" in msg  # guidance, not the email
    assert "rdar://101" in msg
    # Raw emails / names must not leak into the chat.
    assert "f_xxx@apple.com" not in msg
    assert "xxx xxx" not in msg
