"""Friendly Chinese error mapping for FA / Radar integration failures.

The Radar backend (``radarclient`` / SPNego) can fail for several distinct
reasons that the end user should understand *in chat*, not as a raw HTTP 5xx
or a silent skip:

* no Kerberos / AppleConnect ticket on the host  -> ConfigError
* the ticket exists but Radar rejects the read    -> IntegrationError (ACL / 403)
* the ticket id is wrong / not synced             -> IntegrationError (not found)
* a single attachment download fails              -> IntegrationError (per file)

This module converts :class:`~ee_wiki.common.errors.ConfigError` /
:class:`~ee_wiki.common.errors.IntegrationError` into a readable Chinese reply
so the exception never has to reach the HTTP layer. Raw exception text is
deliberately NOT echoed — details stay in the server log (the caller logs
``exc_info=True``).
"""

from __future__ import annotations

from ee_wiki.common.errors import ConfigError

# Keywords that indicate a permission / ACL rejection from Radar.
# Covers both generic HTTP forms (403/forbidden) *and* the real
# `radarclient` phrasing ("Component Owner ... to get access to this problem").
_ACL_HINTS = (
    "403",
    "forbidden",
    "access denied",
    "acl",
    "permission",
    "unauthorized",
    "not authorized",
    "component owner",
    "get access to this problem",
    "access to this problem",
    "no access",
)
# Keywords that indicate the user is simply not logged in to AppleConnect
# (a bare Exception from radarclient, NOT a ConfigError). Real shape:
# "No AppleConnect session established, please log in".
_SESSION_HINTS = (
    "appleconnect",
    "session established",
    "please log in",
    "not logged in",
    "no session",
)
# Keywords that indicate the ticket / attachment cannot be located.
_NOTFOUND_HINTS = (
    "not found",
    "不存在",
    "no such",
    "404",
    "does not exist",
    "unknown radar",
)


def _has_hint(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _credentials_message(*, appleconnect_session: bool = False) -> str:
    """Friendly message for missing / invalid Radar credentials."""
    if appleconnect_session:
        return (
            "AppleConnect 会话未建立或未登录，当前无法访问 Radar。"
            "请先在本机登录 AppleConnect（确保拿到有效票据）后重试。"
        )
    return (
        "Radar 集成未能初始化（通常是本机 Kerberos / AppleConnect 票据缺失或过期，"
        "或 `radarclient` 包未安装）。请确认凭据有效并检查 `fa.radar.backend` "
        "配置后重试。"
    )


def _core_message(exc: Exception, *, context: str = "session") -> str:
    """Return the core friendly Chinese sentence for an FA error.

    Args:
        exc: The caught exception (ConfigError / IntegrationError expected).
        context: ``"session"`` for a whole-ticket / check-in failure, or
            ``"attachment"`` for a single attachment download failure.

    Returns:
        A user-facing Chinese sentence. No raw exception text is included.
    """
    text = str(exc).lower()

    if isinstance(exc, ConfigError):
        return _credentials_message()

    # Not logged in (bare Exception, not ConfigError) — must be checked
    # before the generic ACL branch because it carries no 403 keyword.
    if _has_hint(text, _SESSION_HINTS):
        return _credentials_message(appleconnect_session=True)

    if _has_hint(text, _ACL_HINTS):
        if context == "attachment":
            return "附件下载被 Radar 权限 / ACL 拒绝（可能无该附件的读取权限）。"
        return (
            "无法读取该 Radar 票：Radar 返回权限 / ACL 拒绝，可能该票不在你的可见范围。"
            "可联系该 Radar 票的 Component Owner 申请访问权限；"
            "若确认有权限，请检查 AppleConnect 票据是否有效后重试。"
        )

    if _has_hint(text, _NOTFOUND_HINTS):
        if context == "attachment":
            return "附件未找到（文件名与票上记录不匹配，或票号有误）。"
        return (
            "Radar 票号无法读取或不存在。请确认 `radar://<id>` 正确，"
            "且已同步到当前集成账号。"
        )

    if context == "attachment":
        return "附件下载失败（错误已记入服务端日志，可稍后重试）。"
    return (
        "Radar 操作失败。错误详情已记入服务端日志；可稍后重试，"
        "或把相关测试 log / 失败项贴到对话里继续排查。"
    )


def format_fa_error(
    exc: Exception,
    *,
    radar_id: str | None = None,
    context: str = "session",
    style: str = "block",
) -> str:
    """Return a friendly Chinese message for an FA integration error.

    Args:
        exc: The caught exception (ConfigError / IntegrationError expected).
        radar_id: Optional Radar id to include in the header / context.
        context: ``"session"`` for a whole-ticket failure, ``"attachment"``
            for a single attachment download failure.
        style: ``"block"`` returns a markdown reply with header + next step;
            ``"inline"`` returns a single concise sentence (for list items).

    Returns:
        Markdown text safe to show in the Open WebUI chat.
    """
    core = _core_message(exc, context=context)
    if style == "inline":
        return core
    rid = f" rdar://{radar_id}" if radar_id else ""
    return (
        f"## FA 集成提示{rid}\n\n"
        f"{core}\n\n"
        "---\n"
        "如需继续，可把相关测试 log / 失败项直接贴到对话里，"
        "我用 EE-Wiki 知识库先帮你做初步排查。"
    )
