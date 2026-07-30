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

    match = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def enrich_channel(channel: dict[str, Any], videos: list[dict[str, Any]]) -> dict[str, Any]:
    now = utc_now()
    cutoff = now - timedelta(days=30)
    for video in videos:
        video["duration_seconds"] = duration_to_seconds(video.get("duration", ""))
    recent = [
        video
        for video in videos
        if (parse_datetime(video.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc))
        >= cutoff
    ]
    latest = videos[0] if videos else {}
    classification = classify_channel(channel, videos)
    channel.update(
        {
            "last_video_id": latest.get("video_id", ""),
            "last_video_title": latest.get("title", ""),
            "last_video_published_at": latest.get("published_at"),
            "last_video_views": int(latest.get("view_count", 0) or 0),
            "videos_30d_count": len(recent),
            "views_of_videos_published_30d": sum(
                int(video.get("view_count", 0) or 0) for video in recent
            ),
            "frequency_per_week": round(len(recent) * 7 / 30, 2),
            **classification,
            "updated_at": utc_now_iso(),
            "last_error": "",
        }
    )
    return channel


def sync_reference(
    store: SupabaseStore,
    api: YouTubeDataAPI,
    reference: str,
    lookback_days: int = 60,
    max_pages: int = 4,
) -> dict[str, Any]:
    channel = api.resolve_channel(reference)
    videos = api.fetch_recent_videos(
        channel["channel_id"],
        channel.get("uploads_playlist_id", ""),
        lookback_days,
        max_pages,
    )
    channel = enrich_channel(channel, videos)
    store.upsert_channel(channel)
    store.upsert_videos(videos)
    store.save_snapshot(channel)
    return channel


def sync_channel(
    store: SupabaseStore,
    api: YouTubeDataAPI,
    channel_id: str,
    lookback_days: int = 60,
    max_pages: int = 4,
) -> dict[str, Any]:
    current = store.get_channel(channel_id)
    data = api.fetch_channels_by_ids([channel_id])
    if channel_id not in data:
        raise RuntimeError("Không tìm thấy kênh")
    channel = data[channel_id]
    if current:
        channel["source_ref"] = current.get("source_ref") or channel["canonical_url"]
    videos = api.fetch_recent_videos(
        channel_id,
        channel.get("uploads_playlist_id", ""),
        lookback_days,
        max_pages,
    )
    channel = enrich_channel(channel, videos)
    store.upsert_channel(channel)
    store.upsert_videos(videos)
    store.save_snapshot(channel)
    return channel


def growth_for_channel(store: SupabaseStore, channel: dict[str, Any], days: int) -> int | None:
    """Compatibility helper for single-channel views. Dashboard uses the bulk function below."""
    snapshots = store.list_snapshots(channel["channel_id"], limit=120)
    return growth_from_snapshots(channel, snapshots, days)


def growth_from_snapshots(
    channel: dict[str, Any],
    snapshots: list[dict[str, Any]],
    days: int,
) -> int | None:
    now = datetime.now(timezone.utc).date()
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for snapshot in snapshots:
        try:
            captured = datetime.fromisoformat(str(snapshot["captured_date"])).date()
            age = (now - captured).days
            if age > 0:
                candidates.append((abs(age - days), age, snapshot))
        except (KeyError, TypeError, ValueError):
            continue
    if not candidates:
        return None
    _, age, snapshot = min(candidates, key=lambda item: item[0])
    tolerance = 3 if days == 7 else 7
    if abs(age - days) > tolerance:
        return None
    return max(
        0,
        int(channel.get("total_view_count", 0) or 0)
        - int(snapshot.get("total_view_count", 0) or 0),
    )


def bulk_growth_by_channel(
    channels: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    days: int,
) -> dict[str, int | None]:
    """Calculate growth from one snapshot query, avoiding one request per channel."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for snapshot in snapshots:
        grouped.setdefault(str(snapshot.get("channel_id", "")), []).append(snapshot)
    return {
        str(channel.get("channel_id", "")): growth_from_snapshots(
            channel,
            grouped.get(str(channel.get("channel_id", "")), []),
            days,
        )
        for channel in channels
    }


def add_outlier_scores(
    videos: list[dict[str, Any]],
    baseline_size: int = 20,
    minimum_baseline_videos: int = 5,
) -> list[dict[str, Any]]:
    """
    Compare a video with the median of older videos from the same channel *and type*.

    Shorts are compared only with Shorts and long videos only with long videos. A score is
    returned only when at least ``minimum_baseline_videos`` valid baseline videos exist;
    this prevents one or two tiny videos from creating misleading ratios in the thousands.
    """
    baseline_size = max(10, min(int(baseline_size), 30))
    minimum_baseline_videos = max(3, min(int(minimum_baseline_videos), baseline_size))

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for video in videos:
        seconds = int(video.get("duration_seconds", 0) or 0)
        if not seconds:
            seconds = duration_to_seconds(str(video.get("duration", "")))
        kind = "shorts" if 0 < seconds <= 180 else "long"
        key = (str(video.get("channel_id", "")), kind)
        row = dict(video)
        row["video_type"] = kind
        grouped.setdefault(key, []).append(row)

    now = datetime.now(timezone.utc)
    output: list[dict[str, Any]] = []
    for channel_videos in grouped.values():
        ordered = sorted(
            channel_videos,
            key=lambda row: row.get("published_at") or "",
            reverse=True,
        )
        all_views = [int(row.get("view_count", 0) or 0) for row in ordered]
        for index, video in enumerate(ordered):
            older_views = [
                value for value in all_views[index + 1 : index + 1 + baseline_size] if value > 0
            ]
            if len(older_views) < minimum_baseline_videos:
                fallback = [
                    value
                    for position, value in enumerate(all_views)
                    if position != index and value > 0
                ]
                older_views = fallback[:baseline_size]

            reliable = len(older_views) >= minimum_baseline_videos
            baseline = median(older_views) if reliable else 0
            row = dict(video)
            row["channel_median_views"] = int(baseline or 0)
            row["baseline_video_count"] = len(older_views)
            row["outlier_reliable"] = reliable
            views = int(video.get("view_count", 0) or 0)
            row["outlier_score"] = round(views / baseline, 2) if baseline else 0
            published = parse_datetime(video.get("published_at"))
            age_hours = max(1.0, (now - published).total_seconds() / 3600) if published else 24.0
            row["views_per_day"] = int(views / max(age_hours / 24, 1 / 24))
            output.append(row)

    return sorted(output, key=lambda row: row.get("published_at") or "", reverse=True)
