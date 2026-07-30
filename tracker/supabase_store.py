from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import requests


class StoreError(RuntimeError):
    pass


CHANNEL_SELECT = (
    "channel_id,source_ref,canonical_url,handle,title,description,country,published_at,"
    "subscriber_count,hidden_subscriber_count,total_view_count,video_count,"
    "uploads_playlist_id,channel_keywords,topic_categories,thumbnail_url,"
    "auto_subject,auto_niche,classification_confidence,classification_reason,"
    "last_video_id,last_video_title,last_video_published_at,last_video_views,"
    "videos_30d_count,views_of_videos_published_30d,frequency_per_week,updated_at,last_error"
)

VIDEO_SELECT = (
    "video_id,channel_id,title,published_at,view_count,like_count,comment_count,"
    "duration,duration_seconds,thumbnail_url,last_seen_at"
)

SNAPSHOT_SELECT = (
    "channel_id,captured_date,subscriber_count,total_view_count,video_count,"
    "last_video_id,last_video_views"
)


class SupabaseStore:
    def __init__(self, url: str, key: str, timeout: int = 30):
        self.url = url.rstrip("/")
        self.key = key.strip()
        self.timeout = timeout
        if not self.url or not self.key:
            raise ValueError("Thiếu SUPABASE_URL hoặc SUPABASE_KEY")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
            }
        )

    def _request(
        self,
        method: str,
        table: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        prefer: str | None = None,
    ) -> list[dict[str, Any]]:
        headers: dict[str, str] = {}
        if prefer:
            headers["Prefer"] = prefer
        try:
            response = self.session.request(
                method,
                f"{self.url}/rest/v1/{table}",
                params=params,
                json=json,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise StoreError(f"Không kết nối được Supabase: {exc}") from exc
        if not response.ok:
            raise StoreError(f"Supabase {response.status_code}: {response.text[:500]}")
        if not response.text:
            return []
        try:
            data = response.json()
        except ValueError:
            return []
        return data if isinstance(data, list) else []

    def _list_paginated(
        self,
        table: str,
        *,
        select: str,
        order: str,
        limit: int,
        page_size: int = 1000,
        filters: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read large tables in database pages instead of one oversized response."""
        maximum = max(0, int(limit))
        if maximum == 0:
            return []
        page_size = max(1, min(int(page_size), 1000))
        rows: list[dict[str, Any]] = []
        offset = 0
        while len(rows) < maximum:
            current_limit = min(page_size, maximum - len(rows))
            params: dict[str, Any] = {
                "select": select,
                "order": order,
                "limit": str(current_limit),
                "offset": str(offset),
            }
            if filters:
                params.update(filters)
            page = self._request("GET", table, params=params)
            rows.extend(page)
            if len(page) < current_limit:
                break
            offset += len(page)
        return rows

    def ping(self) -> bool:
        self._request(
            "GET",
            "channels",
            params={"select": "channel_id", "limit": "1"},
        )
        return True

    def list_channels(self, limit: int = 5000) -> list[dict[str, Any]]:
        return self._list_paginated(
            "channels",
            select=CHANNEL_SELECT,
            order="title.asc",
            limit=limit,
        )

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            "channels",
            params={
                "select": CHANNEL_SELECT,
                "channel_id": f"eq.{channel_id}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def upsert_channel(self, channel: dict[str, Any]) -> None:
        payload = {key: value for key, value in channel.items() if key in CHANNEL_COLUMNS}
        self._request(
            "POST",
            "channels",
            params={"on_conflict": "channel_id"},
            json=[payload],
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def delete_channel(self, channel_id: str) -> None:
        self._request(
            "DELETE",
            "channels",
            params={"channel_id": f"eq.{channel_id}"},
            prefer="return=minimal",
        )

    def upsert_videos(self, videos: Iterable[dict[str, Any]]) -> None:
        rows: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat()
        for video in videos:
            row = {key: value for key, value in video.items() if key in VIDEO_COLUMNS}
            row["last_seen_at"] = now
            rows.append(row)
        if not rows:
            return
        for start in range(0, len(rows), 200):
            self._request(
                "POST",
                "videos",
                params={"on_conflict": "video_id"},
                json=rows[start : start + 200],
                prefer="resolution=merge-duplicates,return=minimal",
            )

    def list_videos(self, limit: int = 10000) -> list[dict[str, Any]]:
        return self._list_paginated(
            "videos",
            select=VIDEO_SELECT,
            order="published_at.desc",
            limit=limit,
        )

    def list_channel_videos(self, channel_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self._list_paginated(
            "videos",
            select=VIDEO_SELECT,
            order="published_at.desc",
            limit=limit,
            filters={"channel_id": f"eq.{channel_id}"},
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

    def list_snapshots(
        self,
        channel_id: str | None = None,
        limit: int = 25000,
    ) -> list[dict[str, Any]]:
        filters = {"channel_id": f"eq.{channel_id}"} if channel_id else None
        return self._list_paginated(
            "snapshots",
            select=SNAPSHOT_SELECT,
            order="captured_date.desc",
            limit=limit,
            filters=filters,
        )


CHANNEL_COLUMNS = {
    "channel_id",
    "source_ref",
    "canonical_url",
    "handle",
    "title",
    "description",
    "country",
    "published_at",
    "subscriber_count",
    "hidden_subscriber_count",
    "total_view_count",
    "video_count",
    "uploads_playlist_id",
    "channel_keywords",
    "topic_categories",
    "thumbnail_url",
    "auto_subject",
    "auto_niche",
    "classification_confidence",
    "classification_reason",
    "last_video_id",
    "last_video_title",
    "last_video_published_at",
    "last_video_views",
    "videos_30d_count",
    "views_of_videos_published_30d",
    "frequency_per_week",
    "updated_at",
    "last_error",
}

VIDEO_COLUMNS = {
    "video_id",
    "channel_id",
    "title",
    "published_at",
    "view_count",
    "like_count",
    "comment_count",
    "duration",
    "duration_seconds",
    "thumbnail_url",
    "last_seen_at",
}
