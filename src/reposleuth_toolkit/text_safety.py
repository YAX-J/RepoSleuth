"""文本出站过滤：遮蔽常见凭据赋值与 PEM 私钥，不修改仓库原文件。

规则用于减少仓库文本中的凭据暴露，不能识别任意格式、编码或动态拼接的秘密。
"""

from __future__ import annotations

import re

_SECRET_NAME = (
    r"[\w.-]*(?:api[_-]?key|apikey|secret|(?:access|auth|refresh)[_-]?token|"
    r"token|password|passwd|pwd|private[_-]?key)"
)
_TRIPLE_QUOTED_SECRET = re.compile(
    rf"(?P<prefix>\b{_SECRET_NAME}\b[\"']?\s*[:=]\s*)"
    r"(?P<quote>\"{3}|'{3}).*?(?:(?P=quote)|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_QUOTED_SECRET = re.compile(
    rf"(?P<prefix>\b{_SECRET_NAME}\b[\"']?\s*[:=]\s*)"
    r"(?P<quote>[\"'])(?:\\[^\r\n]|(?!(?P=quote))[^\\\r\n])*(?P=quote)",
    re.IGNORECASE,
)
_BARE_SECRET = re.compile(
    rf"^(?P<prefix>[ \t]*(?:export[ \t]+)?{_SECRET_NAME}[ \t]*[:=][ \t]*)"
    r"[^\s\"'#]+(?P<suffix>\s*(?:#.*)?)$",
    re.IGNORECASE | re.MULTILINE,
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?P<kind>(?:[A-Z0-9]+ )*PRIVATE KEY)-----.*?"
    r"(?:-----END (?P=kind)-----|\Z)",
    re.DOTALL,
)


def redact_sensitive_text(text: str) -> str:
    """遮蔽常见敏感字段的字面值与私钥块，保留字段名以供风险解释。"""
    def keep_lines(original: str, replacement: str) -> str:
        return replacement + "\n" * (original.count("\n") - replacement.count("\n"))

    text = _PRIVATE_KEY.sub(lambda m: keep_lines(m[0], "[REDACTED PRIVATE KEY]"), text)
    text = _TRIPLE_QUOTED_SECRET.sub(
        lambda m: keep_lines(m[0], f"{m['prefix']}{m['quote'][0]}[REDACTED]{m['quote'][0]}"), text,
    )
    text = _QUOTED_SECRET.sub(
        lambda m: f"{m['prefix']}{m['quote']}[REDACTED]{m['quote']}", text,
    )
    return _BARE_SECRET.sub(lambda m: f"{m['prefix']}[REDACTED]{m['suffix']}", text)
