from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import quote

import requests


class StoreError(RuntimeError):
    pass


class SupabaseStore:
    def __init__(self, url: str, key: str, timeout: int = 30):
        self.url = url.rstrip("/")
        self.key = key.strip()
        self.timeout = timeout
        if not self.url or not self.key:
            raise ValueError("Thiếu SUPABASE_URL hoặc SUPABASE_KEY")
        self.session = requests.Session()
        self.session.headers.update({
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        })

    def _request(self, method: str, table: str, *, params=None, json=None, prefer: str | None = None):
        headers = {}
        if prefer:
            headers["Prefer"] = prefer
        r = self.session.request(
            method,
            f"{self.url}/rest/v1/{table}",
            params=params,
            json=json,
            headers=headers,
            timeout=self.timeout,
        )
        if not r.ok:
            raise StoreError(f"Supabase {r.status_code}: {r.text[:500]}")
        if not r.text:
            return []
        try:
            return r.json()
        except ValueError:
            return []

    def list_channels(self) -> list[dict[str, Any]]:
        return self._request("GET", "channels", params={"select": "*", "order": "title.asc"})

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        rows = self._request("GET", "channels", params={"select": "*", "channel_id": f"eq.{channel_id}", "limit": 1})
        return rows[0] if rows else None

    def upsert_channel(self, channel: dict[str, Any]) -> None:
        payload = {k: v for k, v in channel.items() if k in CHANNEL_COLUMNS}
        self._request(
            "POST",
            "channels",
            params={"on_conflict": "channel_id"},
            json=[payload],
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def delete_channel(self, channel_id: str) -> None:
        self._request("DELETE", "channels", params={"channel_id": f"eq.{channel_id}"}, prefer="return=minimal")

    def upsert_videos(self, videos: Iterable[dict[str, Any]]) -> None:
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        for v in videos:
            row = {k: v for k, v in v.items() if k in VIDEO_COLUMNS}
            row["last_seen_at"] = now
            rows.append(row)
        if not rows:
            return
        for i in range(0, len(rows), 200):
            self._request(
                "POST",
                "videos",
                params={"on_conflict": "video_id"},
                json=rows[i:i+200],
                prefer="resolution=merge-duplicates,return=minimal",
            )

    def list_videos(self, limit: int = 2000) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "videos",
            params={"select": "*", "order": "published_at.desc", "limit": str(limit)},
        )

    def list_channel_videos(self, channel_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "videos",
            params={
                "select": "*",
                "channel_id": f"eq.{channel_id}",
                "order": "published_at.desc",
                "limit": str(limit),
            },
        )

    def save_snapshot(self, channel: dict[str, Any]) -> None:
        captured_date = datetime.now(timezone.utc).date().isoformat()
        payload = {
            "channel_id": channel["channel_id"],
            "captured_date": captured_date,
            "subscriber_count": int(channel.get("subscriber_count", 0) or 0),
            "total_view_count": int(channel.get("total_view_count", 0) or 0),
            "video_count": int(channel.get("video_count", 0) or 0),
            "last_video_id": channel.get("last_video_id") or "",
            "last_video_views": int(channel.get("last_video_views", 0) or 0),
        }
        self._request(
            "POST",
            "snapshots",
            params={"on_conflict": "channel_id,captured_date"},
            json=[payload],
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def list_snapshots(self, channel_id: str | None = None, limit: int = 10000) -> list[dict[str, Any]]:
        params = {"select": "*", "order": "captured_date.desc", "limit": str(limit)}
        if channel_id:
            params["channel_id"] = f"eq.{channel_id}"
        return self._request("GET", "snapshots", params=params)


CHANNEL_COLUMNS = {
    "channel_id", "source_ref", "canonical_url", "handle", "title", "description",
    "country", "published_at", "subscriber_count", "hidden_subscriber_count",
    "total_view_count", "video_count", "uploads_playlist_id", "channel_keywords",
    "topic_categories", "thumbnail_url", "auto_subject", "auto_niche",
    "classification_confidence", "classification_reason", "last_video_id",
    "last_video_title", "last_video_published_at", "last_video_views",
    "videos_30d_count", "views_of_videos_published_30d", "frequency_per_week",
    "updated_at", "last_error"
}

VIDEO_COLUMNS = {
    "video_id", "channel_id", "title", "published_at", "view_count", "like_count",
    "comment_count", "duration", "duration_seconds", "thumbnail_url", "last_seen_at"
}
