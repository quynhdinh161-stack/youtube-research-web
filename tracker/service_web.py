from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from .classifier import classify_channel
from .utils import parse_datetime, utc_now, utc_now_iso
from .youtube_api import YouTubeDataAPI
from .supabase_store import SupabaseStore


def duration_to_seconds(value: str) -> int:
    # ISO 8601 duration subset used by YouTube, e.g. PT1H2M3S.
    import re
    m = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def enrich_channel(channel: dict[str, Any], videos: list[dict[str, Any]]) -> dict[str, Any]:
    now = utc_now()
    cutoff = now - timedelta(days=30)
    for v in videos:
        v["duration_seconds"] = duration_to_seconds(v.get("duration", ""))
    recent = [v for v in videos if (parse_datetime(v.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    latest = videos[0] if videos else {}
    classification = classify_channel(channel, videos)
    channel.update({
        "last_video_id": latest.get("video_id", ""),
        "last_video_title": latest.get("title", ""),
        "last_video_published_at": latest.get("published_at"),
        "last_video_views": int(latest.get("view_count", 0) or 0),
        "videos_30d_count": len(recent),
        "views_of_videos_published_30d": sum(int(v.get("view_count", 0) or 0) for v in recent),
        "frequency_per_week": round(len(recent) * 7 / 30, 2),
        **classification,
        "updated_at": utc_now_iso(),
        "last_error": "",
    })
    return channel


def sync_reference(store: SupabaseStore, api: YouTubeDataAPI, reference: str, lookback_days: int = 60, max_pages: int = 4) -> dict[str, Any]:
    channel = api.resolve_channel(reference)
    videos = api.fetch_recent_videos(channel["channel_id"], channel.get("uploads_playlist_id", ""), lookback_days, max_pages)
    channel = enrich_channel(channel, videos)
    store.upsert_channel(channel)
    store.upsert_videos(videos)
    store.save_snapshot(channel)
    return channel


def sync_channel(store: SupabaseStore, api: YouTubeDataAPI, channel_id: str, lookback_days: int = 60, max_pages: int = 4) -> dict[str, Any]:
    current = store.get_channel(channel_id)
    data = api.fetch_channels_by_ids([channel_id])
    if channel_id not in data:
        raise RuntimeError("Không tìm thấy kênh")
    channel = data[channel_id]
    if current:
        channel["source_ref"] = current.get("source_ref") or channel["canonical_url"]
    videos = api.fetch_recent_videos(channel_id, channel.get("uploads_playlist_id", ""), lookback_days, max_pages)
    channel = enrich_channel(channel, videos)
    store.upsert_channel(channel)
    store.upsert_videos(videos)
    store.save_snapshot(channel)
    return channel


def growth_for_channel(store: SupabaseStore, channel: dict[str, Any], days: int) -> int | None:
    snaps = store.list_snapshots(channel["channel_id"], limit=120)
    if not snaps:
        return None
    now = datetime.now(timezone.utc).date()
    candidates = []
    for s in snaps:
        try:
            d = datetime.fromisoformat(s["captured_date"]).date()
            age = (now - d).days
            if age > 0:
                candidates.append((abs(age-days), age, s))
        except Exception:
            pass
    if not candidates:
        return None
    _, age, snap = min(candidates, key=lambda x: x[0])
    tolerance = 3 if days == 7 else 7
    if abs(age-days) > tolerance:
        return None
    return max(0, int(channel.get("total_view_count", 0) or 0) - int(snap.get("total_view_count", 0) or 0))


def add_outlier_scores(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_channel: dict[str, list[int]] = {}
    for v in videos:
        by_channel.setdefault(v.get("channel_id", ""), []).append(int(v.get("view_count", 0) or 0))
    medians = {cid: median(vals) if vals else 0 for cid, vals in by_channel.items()}
    now = datetime.now(timezone.utc)
    out = []
    for v in videos:
        row = dict(v)
        base = medians.get(v.get("channel_id", ""), 0) or 0
        row["outlier_score"] = round((int(v.get("view_count", 0) or 0) / base), 2) if base else 0
        dt = parse_datetime(v.get("published_at"))
        age_days = max(1, (now - dt).days) if dt else 1
        row["views_per_day"] = int(int(v.get("view_count", 0) or 0) / age_days)
        out.append(row)
    return out
