from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

CHANNEL_ID_RE = re.compile(r"^UC[a-zA-Z0-9_-]{22}$")


class UnsupportedChannelReference(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def chunked(items: list[str], size: int = 50) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text))
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_header(text: str) -> str:
    text = strip_accents(text).lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_channel_locator(reference: str) -> tuple[str, str]:
    """Return one of: ('id', UC...), ('handle', @...), ('username', ...)."""
    raw = (reference or "").strip()
    if not raw:
        raise UnsupportedChannelReference("Dòng trống")

    if CHANNEL_ID_RE.match(raw):
        return "id", raw
    if raw.startswith("@") and len(raw) > 1:
        return "handle", raw

    candidate = raw
    if not re.match(r"^https?://", candidate, re.I):
        if "youtube.com/" in candidate or "youtu.be/" in candidate:
            candidate = "https://" + candidate
        else:
            # A handle without @ is accepted as a convenience.
            if re.match(r"^[a-zA-Z0-9._-]{3,}$", candidate):
                return "handle", "@" + candidate
            raise UnsupportedChannelReference(f"Không nhận diện được: {raw}")

    parsed = urlparse(candidate)
    host = parsed.netloc.lower().replace("www.", "").replace("m.", "")
    if host not in {"youtube.com", "music.youtube.com"}:
        raise UnsupportedChannelReference("Chỉ hỗ trợ đường dẫn kênh youtube.com")

    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        raise UnsupportedChannelReference("Đường dẫn chưa chứa kênh")

    first = parts[0]
    if first.startswith("@"):
        return "handle", first
    if first == "channel" and len(parts) >= 2 and CHANNEL_ID_RE.match(parts[1]):
        return "id", parts[1]
    if first == "user" and len(parts) >= 2:
        return "username", parts[1]
    if first == "c" and len(parts) >= 2:
        raise UnsupportedChannelReference(
            "URL /c/ cũ không thể xác định chính xác bằng API. Hãy dùng link @handle hoặc /channel/UC..."
        )

    raise UnsupportedChannelReference(
        "Không nhận diện được kênh. Hãy dùng @handle, channel ID hoặc link /channel/, /@, /user/."
    )


def canonical_channel_url(channel_id: str) -> str:
    return f"https://www.youtube.com/channel/{channel_id}"


def format_topic_categories(categories: list[str] | None) -> str:
    if not categories:
        return ""
    names: list[str] = []
    for url in categories:
        name = url.rstrip("/").split("/")[-1].replace("_", " ")
        if name and name not in names:
            names.append(name)
    return ", ".join(names)


def channel_activity_status(last_published_at: str | None, now: datetime | None = None) -> str:
    now = now or utc_now()
    published = parse_datetime(last_published_at)
    if not published:
        return "Chưa có dữ liệu"
    days = max(0, (now - published).days)
    if days <= 2:
        return "Mới đăng"
    if days <= 14:
        return "Đang hoạt động"
    if days <= 30:
        return "Chậm đăng"
    return "Ngừng đăng"
