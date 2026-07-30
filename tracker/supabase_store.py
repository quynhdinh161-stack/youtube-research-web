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

MARKET_KEYWORD_SELECT = (
    "id,keyword,normalized_keyword,subject,niche,region_code,language_code,video_type,"
    "period_days,result_limit,scan_cycle,is_active,last_scanned_at,last_result_count,"
    "created_at,updated_at"
)

MARKET_SCAN_SELECT = (
    "id,keyword_id,query,normalized_query,subject,niche,region_code,language_code,"
    "video_type,period_days,result_limit,search_order,deep_channel_limit,result_count,total_views,average_views_per_day,"
    "unique_channels,average_subscribers,api_units_estimated,deep_channels_analyzed,"
    "status,error_message,scanned_at"
)

MARKET_RESULT_SELECT = (
    "id,scan_id,keyword_id,source_keyword,subject,niche,region_code,language_code,"
    "video_type,video_id,channel_id,channel_title,title,published_at,view_count,"
    "like_count,comment_count,duration,duration_seconds,thumbnail_url,views_per_day,"
    "channel_subscriber_count,channel_total_view_count,channel_video_count,"
    "channel_country,channel_thumbnail_url,channel_published_at,"
    "channel_uploads_playlist_id,channel_baseline_views,baseline_video_count,"
    "outlier_score,discovered_at"
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

    def market_schema_ready(self) -> bool:
        """Return False only when the Stage 2 tables have not been created yet."""
        try:
            self._request(
                "GET",
                "market_keywords",
                params={"select": "id", "limit": "1"},
            )
            return True
        except StoreError as exc:
            message = str(exc).lower()
            if "market_keywords" in message and ("does not exist" in message or "pgrst205" in message or "42p01" in message):
                return False
            raise

    def list_market_keywords(
        self,
        *,
        active_only: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        filters = {"is_active": "eq.true"} if active_only else None
        return self._list_paginated(
            "market_keywords",
            select=MARKET_KEYWORD_SELECT,
            order="updated_at.desc",
            limit=limit,
            filters=filters,
        )

    def get_market_keyword(self, keyword_id: int) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            "market_keywords",
            params={
                "select": MARKET_KEYWORD_SELECT,
                "id": f"eq.{int(keyword_id)}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def upsert_market_keyword(self, keyword: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "id", "keyword", "normalized_keyword", "subject", "niche",
            "region_code", "language_code", "video_type", "period_days",
            "result_limit", "scan_cycle", "is_active", "last_scanned_at",
            "last_result_count", "created_at", "updated_at",
        }
        payload = {key: value for key, value in keyword.items() if key in allowed}
        rows = self._request(
            "POST",
            "market_keywords",
            params={
                "on_conflict": "normalized_keyword,region_code,language_code,video_type"
            },
            json=[payload],
            prefer="resolution=merge-duplicates,return=representation",
        )
        if not rows:
            raise StoreError("Supabase không trả lại từ khóa vừa lưu")
        return rows[0]

    def update_market_keyword(self, keyword_id: int, changes: dict[str, Any]) -> None:
        allowed = {
            "keyword", "normalized_keyword", "subject", "niche", "region_code",
            "language_code", "video_type", "period_days", "result_limit",
            "scan_cycle", "is_active", "last_scanned_at", "last_result_count",
            "updated_at",
        }
        payload = {key: value for key, value in changes.items() if key in allowed}
        if not payload:
            return
        self._request(
            "PATCH",
            "market_keywords",
            params={"id": f"eq.{int(keyword_id)}"},
            json=payload,
            prefer="return=minimal",
        )

    def delete_market_keyword(self, keyword_id: int) -> None:
        self._request(
            "DELETE",
            "market_keywords",
            params={"id": f"eq.{int(keyword_id)}"},
            prefer="return=minimal",
        )

    def insert_market_scan(self, scan: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "keyword_id", "query", "normalized_query", "subject", "niche",
            "region_code", "language_code", "video_type", "period_days",
            "result_limit", "search_order", "deep_channel_limit", "result_count", "total_views",
            "average_views_per_day", "unique_channels", "average_subscribers",
            "api_units_estimated", "deep_channels_analyzed", "status",
            "error_message", "scanned_at",
        }
        payload = {key: value for key, value in scan.items() if key in allowed}
        rows = self._request(
            "POST",
            "market_scans",
            json=[payload],
            prefer="return=representation",
        )
        if not rows:
            raise StoreError("Supabase không trả lại phiên quét vừa lưu")
        return rows[0]

    def update_market_scan(self, scan_id: int, changes: dict[str, Any]) -> None:
        allowed = {
            "result_count", "total_views", "average_views_per_day",
            "unique_channels", "average_subscribers", "api_units_estimated",
            "deep_channels_analyzed", "status", "error_message",
        }
        payload = {key: value for key, value in changes.items() if key in allowed}
        if not payload:
            return
        self._request(
            "PATCH",
            "market_scans",
            params={"id": f"eq.{int(scan_id)}"},
            json=payload,
            prefer="return=minimal",
        )

    def list_market_scans(
        self,
        *,
        keyword_id: int | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        filters = {"keyword_id": f"eq.{int(keyword_id)}"} if keyword_id is not None else None
        return self._list_paginated(
            "market_scans",
            select=MARKET_SCAN_SELECT,
            order="scanned_at.desc",
            limit=limit,
            filters=filters,
        )

    def get_recent_market_scan(
        self,
        *,
        normalized_query: str,
        region_code: str,
        language_code: str,
        video_type: str,
        period_days: int,
        result_limit: int,
        search_order: str,
        deep_channel_limit: int,
        scanned_after: str,
        keyword_id: int | None = None,
    ) -> dict[str, Any] | None:
        params: dict[str, Any] = {
            "select": MARKET_SCAN_SELECT,
            "normalized_query": f"eq.{normalized_query}",
            "region_code": f"eq.{region_code}",
            "language_code": f"eq.{language_code}",
            "video_type": f"eq.{video_type}",
            "period_days": f"eq.{int(period_days)}",
            "result_limit": f"eq.{int(result_limit)}",
            "search_order": f"eq.{search_order}",
            "deep_channel_limit": f"eq.{int(deep_channel_limit)}",
            "status": "eq.success",
            "scanned_at": f"gte.{scanned_after}",
            "order": "scanned_at.desc",
            "limit": "1",
        }
        if keyword_id is not None:
            params["keyword_id"] = f"eq.{int(keyword_id)}"
        rows = self._request(
            "GET",
            "market_scans",
            params=params,
        )
        return rows[0] if rows else None

    def insert_market_results(self, results: Iterable[dict[str, Any]]) -> None:
        allowed = {
            "scan_id", "keyword_id", "source_keyword", "subject", "niche",
            "region_code", "language_code", "video_type", "video_id",
            "channel_id", "channel_title", "title", "published_at",
            "view_count", "like_count", "comment_count", "duration",
            "duration_seconds", "thumbnail_url", "views_per_day",
            "channel_subscriber_count", "channel_total_view_count",
            "channel_video_count", "channel_country", "channel_thumbnail_url",
            "channel_published_at", "channel_uploads_playlist_id",
            "channel_baseline_views", "baseline_video_count", "outlier_score",
            "discovered_at",
        }
        rows = [
            {key: value for key, value in result.items() if key in allowed}
            for result in results
        ]
        if not rows:
            return
        for start in range(0, len(rows), 200):
            self._request(
                "POST",
                "market_results",
                params={"on_conflict": "scan_id,video_id"},
                json=rows[start : start + 200],
                prefer="resolution=merge-duplicates,return=minimal",
            )

    def list_market_results(
        self,
        *,
        scan_id: int | None = None,
        keyword_id: int | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        filters: dict[str, str] = {}
        if scan_id is not None:
            filters["scan_id"] = f"eq.{int(scan_id)}"
        if keyword_id is not None:
            filters["keyword_id"] = f"eq.{int(keyword_id)}"
        return self._list_paginated(
            "market_results",
            select=MARKET_RESULT_SELECT,
            order="discovered_at.desc",
            limit=limit,
            filters=filters or None,
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
