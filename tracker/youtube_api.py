from __future__ import annotations

from datetime import timedelta
from typing import Any

import requests

from .config import REQUEST_TIMEOUT_SECONDS
from .utils import (
    canonical_channel_url,
    chunked,
    extract_channel_locator,
    format_topic_categories,
    parse_datetime,
    to_int,
    utc_now,
)


class YouTubeApiError(RuntimeError):
    pass


class YouTubeDataAPI:
    BASE_URL = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key: str, timeout: int = REQUEST_TIMEOUT_SECONDS):
        if not api_key.strip():
            raise ValueError("Chưa có YouTube API key")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.calls = 0
        self.quota_units_estimated = 0
        self.session = requests.Session()

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "key": self.api_key}
        self.calls += 1
        self.quota_units_estimated += 100 if endpoint == "search" else 1
        try:
            response = self.session.get(
                f"{self.BASE_URL}/{endpoint}", params=params, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise YouTubeApiError(f"Không kết nối được YouTube API: {exc}") from exc

        if not response.ok:
            try:
                body = response.json()
                message = body.get("error", {}).get("message", response.text)
            except ValueError:
                message = response.text
            raise YouTubeApiError(f"YouTube API {response.status_code}: {message}")
        return response.json()

    def test_connection(self, region_code: str = "US") -> bool:
        """Make one inexpensive API request to verify that the configured key works."""
        self._get(
            "videos",
            {
                "part": "id",
                "chart": "mostPopular",
                "regionCode": region_code,
                "maxResults": 1,
            },
        )
        return True

    def resolve_channel(self, reference: str) -> dict[str, Any]:
        kind, value = extract_channel_locator(reference)
        params: dict[str, Any] = {
            "part": "snippet,statistics,contentDetails,brandingSettings,topicDetails",
            "maxResults": 1,
        }
        if kind == "id":
            params["id"] = value
        elif kind == "handle":
            params["forHandle"] = value
        elif kind == "username":
            params["forUsername"] = value
        else:
            raise YouTubeApiError("Loại đường dẫn chưa được hỗ trợ")

        data = self._get("channels", params)
        items = data.get("items", [])
        if not items:
            raise YouTubeApiError(f"Không tìm thấy kênh: {reference}")
        return self._normalize_channel(items[0], source_ref=reference)

    def fetch_channels_by_ids(self, channel_ids: list[str]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for batch in chunked(channel_ids, 50):
            data = self._get(
                "channels",
                {
                    "part": "snippet,statistics,contentDetails,brandingSettings,topicDetails",
                    "id": ",".join(batch),
                    "maxResults": 50,
                },
            )
            for item in data.get("items", []):
                normalized = self._normalize_channel(item)
                result[normalized["channel_id"]] = normalized
        return result

    def fetch_recent_videos(
        self,
        channel_id: str,
        uploads_playlist_id: str,
        lookback_days: int = 60,
        max_pages: int = 6,
    ) -> list[dict[str, Any]]:
        if not uploads_playlist_id:
            return []

        cutoff = utc_now() - timedelta(days=max(30, lookback_days))
        page_token: str | None = None
        videos: list[dict[str, Any]] = []

        for _ in range(max(1, max_pages)):
            params: dict[str, Any] = {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            playlist_data = self._get("playlistItems", params)
            ids = [
                item.get("contentDetails", {}).get("videoId")
                for item in playlist_data.get("items", [])
            ]
            ids = [video_id for video_id in ids if video_id]
            if not ids:
                break

            video_data = self._get(
                "videos",
                {
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(ids),
                },
            )
            page_videos = [
                self._normalize_video(item, channel_id)
                for item in video_data.get("items", [])
            ]
            page_videos.sort(key=lambda x: x.get("published_at") or "", reverse=True)
            videos.extend(page_videos)

            published_dates = [
                parsed
                for parsed in (parse_datetime(v.get("published_at")) for v in page_videos)
                if parsed is not None
            ]
            oldest = min(published_dates) if published_dates else None
            page_token = playlist_data.get("nextPageToken")
            if not page_token or (oldest and oldest < cutoff):
                break

        unique = {video["video_id"]: video for video in videos}
        return sorted(
            unique.values(), key=lambda x: x.get("published_at") or "", reverse=True
        )


    def search_videos(
        self,
        query: str,
        max_results: int = 24,
        region_code: str | None = None,
        published_after: str | None = None,
        order: str = "viewCount",
        relevance_language: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max(1, min(max_results, 50)),
            "order": order,
        }
        if region_code:
            params["regionCode"] = region_code
        if published_after:
            params["publishedAfter"] = published_after
        if relevance_language:
            params["relevanceLanguage"] = relevance_language
        data = self._get("search", params)
        ids = [item.get("id", {}).get("videoId") for item in data.get("items", [])]
        ids = [x for x in ids if x]
        if not ids:
            return []
        details = self._get("videos", {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(ids),
        })
        rows = []
        for item in details.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            rows.append({
                "video_id": item["id"],
                "channel_id": snippet.get("channelId", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt"),
                "view_count": to_int(stats.get("viewCount")),
                "like_count": to_int(stats.get("likeCount")),
                "comment_count": to_int(stats.get("commentCount")),
                "duration": item.get("contentDetails", {}).get("duration", ""),
                "thumbnail_url": self._best_thumbnail(snippet.get("thumbnails", {})),
                "default_language": snippet.get("defaultLanguage", ""),
                "default_audio_language": snippet.get("defaultAudioLanguage", ""),
                "category_id": snippet.get("categoryId", ""),
            })
        order_map = {v: i for i, v in enumerate(ids)}
        return sorted(rows, key=lambda x: order_map.get(x["video_id"], 9999))

    @staticmethod
    def _best_thumbnail(thumbnails: dict[str, Any]) -> str:
        for key in ("maxres", "standard", "high", "medium", "default"):
            url = thumbnails.get(key, {}).get("url")
            if url:
                return url
        return ""

    def _normalize_channel(
        self, item: dict[str, Any], source_ref: str | None = None
    ) -> dict[str, Any]:
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content = item.get("contentDetails", {})
        branding = item.get("brandingSettings", {}).get("channel", {})
        channel_id = item["id"]
        custom_url = snippet.get("customUrl", "")
        return {
            "channel_id": channel_id,
            "source_ref": source_ref or canonical_channel_url(channel_id),
            "canonical_url": canonical_channel_url(channel_id),
            "handle": custom_url if custom_url.startswith("@") else "",
            "title": snippet.get("title", channel_id),
            "description": snippet.get("description", ""),
            "country": snippet.get("country", ""),
            "published_at": snippet.get("publishedAt"),
            "subscriber_count": to_int(statistics.get("subscriberCount")),
            "hidden_subscriber_count": int(bool(statistics.get("hiddenSubscriberCount"))),
            "total_view_count": to_int(statistics.get("viewCount")),
            "video_count": to_int(statistics.get("videoCount")),
            "uploads_playlist_id": content.get("relatedPlaylists", {}).get("uploads", ""),
            "channel_keywords": branding.get("keywords", ""),
            "topic_categories": format_topic_categories(
                item.get("topicDetails", {}).get("topicCategories", [])
            ),
            "thumbnail_url": self._best_thumbnail(snippet.get("thumbnails", {})),
        }

    def _normalize_video(self, item: dict[str, Any], channel_id: str) -> dict[str, Any]:
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        return {
            "video_id": item["id"],
            "channel_id": channel_id,
            "title": snippet.get("title", ""),
            "published_at": snippet.get("publishedAt"),
            "view_count": to_int(statistics.get("viewCount")),
            "like_count": to_int(statistics.get("likeCount")),
            "comment_count": to_int(statistics.get("commentCount")),
            "duration": item.get("contentDetails", {}).get("duration", ""),
            "thumbnail_url": self._best_thumbnail(snippet.get("thumbnails", {})),
        }
