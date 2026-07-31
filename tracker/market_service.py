from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
import html
import math
import re
from typing import Any

from .classifier import classify_channel
from .service_web import duration_to_seconds
from .supabase_store import SupabaseStore
from .utils import canonical_channel_url, parse_datetime, utc_now_iso
from .youtube_api import YouTubeDataAPI


def normalize_keyword(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def market_video_type(duration_seconds: int) -> str:
    return "shorts" if 0 < int(duration_seconds or 0) <= 180 else "long"


def estimate_market_scan_units(deep_channel_limit: int, result_limit: int = 50) -> int:
    # search.list = 100, videos.list = 1, channels.list = 1 for <=50 channels.
    # Every deep channel adds one playlistItems.list + one videos.list request.
    channel_batches = max(1, (min(max(1, result_limit), 50) + 49) // 50)
    return 101 + channel_batches + max(0, int(deep_channel_limit)) * 2


def build_keyword_payload(
    *,
    keyword: str,
    subject: str = "",
    niche: str = "",
    region_code: str = "US",
    language_code: str = "en",
    video_type: str = "all",
    period_days: int = 30,
    result_limit: int = 24,
    scan_cycle: str = "manual",
    is_active: bool = True,
) -> dict[str, Any]:
    cleaned = " ".join((keyword or "").strip().split())
    return {
        "keyword": cleaned,
        "normalized_keyword": normalize_keyword(cleaned),
        "subject": subject.strip(),
        "niche": niche.strip(),
        "region_code": region_code.upper().strip() or "US",
        "language_code": language_code.lower().strip() or "en",
        "video_type": video_type if video_type in {"all", "long", "shorts"} else "all",
        "period_days": max(1, int(period_days)),
        "result_limit": max(1, min(int(result_limit), 50)),
        "scan_cycle": scan_cycle or "manual",
        "is_active": bool(is_active),
        "updated_at": utc_now_iso(),
    }



# Các từ quá chung hoặc từ chức năng thường xuất hiện trong tiêu đề nhưng không tạo
# thành một truy vấn thị trường hữu ích. Danh sách cố ý ngắn để không làm mất các
# cụm ngách hiếm.
_DISCOVERY_STOPWORDS: dict[str, set[str]] = {
    "en": {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
        "how", "in", "is", "it", "its", "of", "on", "or", "that", "the", "their",
        "this", "to", "was", "were", "what", "when", "where", "who", "why", "with",
        "you", "your", "we", "our", "they", "them", "his", "her", "into", "after",
        "before", "over", "under", "than", "then", "now", "today",
    },
    "vi": {
        "và", "là", "của", "cho", "trong", "trên", "dưới", "với", "một", "những",
        "các", "đã", "đang", "sẽ", "khi", "sau", "trước", "từ", "đến", "về", "này",
        "đó", "tại", "như", "thì", "mà", "hay", "hoặc", "được", "bị", "có", "không",
    },
    "es": {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "y",
        "o", "en", "con", "por", "para", "que", "como", "cuando", "donde", "su",
        "sus", "este", "esta", "estos", "estas", "al", "se", "es", "son",
    },
    "pt": {
        "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos",
        "das", "e", "ou", "em", "com", "por", "para", "que", "como", "quando", "onde",
        "seu", "sua", "seus", "suas", "este", "esta", "ao", "é", "são",
    },
    "id": {
        "dan", "atau", "di", "ke", "dari", "untuk", "yang", "ini", "itu", "dengan",
        "pada", "oleh", "sebagai", "adalah", "akan", "sudah", "telah", "saat", "ketika",
    },
    "fr": {
        "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "en", "avec",
        "pour", "par", "que", "qui", "quoi", "quand", "où", "son", "sa", "ses", "ce",
        "cette", "ces", "est", "sont", "au", "aux",
    },
    "de": {
        "der", "die", "das", "ein", "eine", "einer", "eines", "und", "oder", "in", "im",
        "mit", "von", "für", "zu", "zum", "zur", "auf", "ist", "sind", "wie", "was",
        "wann", "wo", "dieser", "diese", "dieses",
    },
}

_DISCOVERY_GENERIC_WORDS = {
    "video", "videos", "official", "full", "episode", "episodes", "part", "shorts",
    "short", "live", "new", "latest", "today", "watch", "viral", "amazing", "shocking",
    "incredible", "unbelievable", "best", "top", "compilation", "moments", "moment",
    "youtube", "channel", "update", "news", "review", "reaction", "trailer", "clip", "clips",
    "tập", "phần", "mới", "hôm", "nay", "chính", "thức", "xem", "cực", "sốc",
    "nuevo", "nueva", "oficial", "completo", "completa", "episodio", "parte",
    "novo", "nova", "oficial", "completo", "completa", "episódio",
}

_COUNTRY_LANGUAGE = {
    "US": "en", "GB": "en", "CA": "en", "AU": "en", "NZ": "en",
    "VN": "vi", "ES": "es", "MX": "es", "AR": "es", "CO": "es",
    "BR": "pt", "PT": "pt", "ID": "id", "FR": "fr", "DE": "de",
    "AT": "de", "CH": "de", "TH": "th", "JP": "ja", "KR": "ko",
}


# YouTube video category IDs used for market-native discovery. These requests use
# videos.list(chart=mostPopular), so they do not depend on saved keywords or the
# tracked-channel list.
MARKET_DISCOVERY_CATEGORIES: dict[str, str] = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "19": "Travel & Events",
    "20": "Gaming",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
}


def _title_tokens(value: str) -> list[str]:
    cleaned = html.unescape(str(value or "")).lower().replace("&", " and ")
    return [
        token.strip("_-")
        for token in re.findall(r"[^\W_]+(?:['’-][^\W_]+)?", cleaned, flags=re.UNICODE)
        if token.strip("_-")
    ]


def _infer_language(text: str, country: str) -> str:
    tokens = _title_tokens(text)
    unique_tokens = set(tokens)
    scores = {
        language: len(unique_tokens & stopwords)
        for language, stopwords in _DISCOVERY_STOPWORDS.items()
    }
    best_language, best_score = max(scores.items(), key=lambda item: item[1]) if scores else ("en", 0)
    if best_score >= 2:
        return best_language
    return _COUNTRY_LANGUAGE.get(str(country or "").upper(), "en")


def _candidate_phrases(title: str) -> set[str]:
    tokens = _title_tokens(title)
    if len(tokens) < 2:
        return set()
    all_stopwords = set().union(*_DISCOVERY_STOPWORDS.values())
    candidates: set[str] = set()
    for size in (2, 3, 4):
        for start in range(0, len(tokens) - size + 1):
            phrase_tokens = tokens[start : start + size]
            if phrase_tokens[0] in all_stopwords or phrase_tokens[-1] in all_stopwords:
                continue
            meaningful = [
                token
                for token in phrase_tokens
                if token not in all_stopwords
                and token not in _DISCOVERY_GENERIC_WORDS
                and len(token) >= 3
                and not token.isdigit()
            ]
            if len(meaningful) < 2:
                continue
            if len(set(phrase_tokens)) < max(2, size - 1):
                continue
            if sum(token.isdigit() for token in phrase_tokens) > 1:
                continue
            phrase = " ".join(phrase_tokens).strip()
            if 6 <= len(phrase) <= 72:
                candidates.add(phrase)
    return candidates



def discover_keywords_from_youtube_market(
    api: YouTubeDataAPI,
    *,
    region_codes: list[str],
    language_codes: list[str] | None = None,
    category_ids: list[str] | None = None,
    top_n: int = 50,
    videos_per_category: int = 50,
) -> dict[str, Any]:
    """Discover keyword candidates directly from YouTube's current market charts.

    No saved keyword and no tracked channel is used as a seed. The function samples
    videos.list(chart=mostPopular) across the selected countries/categories, extracts
    repeated 2-4 word phrases from current titles, and ranks them by repetition,
    channel diversity, region/category diversity, recency and views/day.

    This is *not* YouTube search volume. It is a market-signal score derived from the
    current most-popular video sample returned by the YouTube Data API.
    """
    regions = [str(x).upper().strip() for x in (region_codes or ["US"]) if str(x).strip()]
    regions = list(dict.fromkeys(regions))[:6]
    languages = [str(x).lower().strip() for x in (language_codes or []) if str(x).strip()]
    categories = [str(x).strip() for x in (category_ids or list(MARKET_DISCOVERY_CATEGORIES)) if str(x).strip()]
    categories = list(dict.fromkeys(categories))[:20]
    if not regions:
        regions = ["US"]
    if not categories:
        categories = list(MARKET_DISCOVERY_CATEGORIES)

    started_units = int(getattr(api, "quota_units_estimated", 0))
    raw_by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for region in regions:
        for category_id in categories:
            try:
                rows = api.fetch_most_popular_videos(
                    region_code=region,
                    category_id=category_id,
                    max_results=max(1, min(int(videos_per_category), 50)),
                )
            except Exception as exc:
                errors.append(f"{region}/{category_id}: {exc}")
                continue
            for row in rows:
                video_id = str(row.get("video_id", ""))
                if not video_id:
                    continue
                inferred_language = _infer_language(str(row.get("title", "")), region)
                explicit_language = str(
                    row.get("default_audio_language") or row.get("default_language") or ""
                ).lower().split("-")[0]
                language = explicit_language or inferred_language
                if languages and language not in languages and inferred_language not in languages:
                    continue
                if video_id not in raw_by_id:
                    merged = dict(row)
                    merged["regions"] = {region}
                    merged["sampled_categories"] = {category_id}
                    merged["market_language"] = language
                    raw_by_id[video_id] = merged
                else:
                    raw_by_id[video_id]["regions"].add(region)
                    raw_by_id[video_id]["sampled_categories"].add(category_id)

    now = datetime.now(timezone.utc)
    stats: dict[str, dict[str, Any]] = {}
    for video in raw_by_id.values():
        title = str(video.get("title", "")).strip()
        video_id = str(video.get("video_id", ""))
        channel_id = str(video.get("channel_id", ""))
        if not title or not video_id or not channel_id:
            continue
        published = parse_datetime(video.get("published_at"))
        age_days = max(
            1 / 24,
            ((now - published).total_seconds() / 86400) if published else 1.0,
        )
        views = int(video.get("view_count", 0) or 0)
        views_per_day = int(views / age_days)
        # Popular chart is already a strong signal; logarithmic performance weight
        # prevents one giant music video from completely dominating the ranking.
        performance_weight = 1.0 + min(5.5, math.log10(max(views_per_day, 1) + 1))
        recency_weight = max(0.45, 1.25 - min(age_days, 60) / 75)
        base_weight = performance_weight * recency_weight
        for phrase in _candidate_phrases(title):
            row = stats.setdefault(
                phrase,
                {
                    "keyword": phrase,
                    "normalized_keyword": normalize_keyword(phrase),
                    "score": 0.0,
                    "video_ids": set(),
                    "channel_ids": set(),
                    "regions": set(),
                    "categories": set(),
                    "languages": Counter(),
                    "titles": [],
                    "total_views": 0,
                    "total_views_per_day": 0,
                },
            )
            if video_id in row["video_ids"]:
                continue
            phrase_size = len(phrase.split())
            length_factor = {2: 1.14, 3: 1.06, 4: 0.96}.get(phrase_size, 1.0)
            row["score"] += base_weight * length_factor
            row["video_ids"].add(video_id)
            row["channel_ids"].add(channel_id)
            row["regions"].update(video.get("regions") or set())
            row["categories"].update(video.get("sampled_categories") or set())
            row["languages"][str(video.get("market_language") or "en")] += 1
            if len(row["titles"]) < 4:
                row["titles"].append(title)
            row["total_views"] += views
            row["total_views_per_day"] += views_per_day

    candidates: list[dict[str, Any]] = []
    for row in stats.values():
        video_count = len(row["video_ids"])
        channel_count = len(row["channel_ids"])
        # Repetition across two different videos is the preferred market signal.
        if video_count < 2 and channel_count < 2:
            continue
        region_count = len(row["regions"])
        category_count = len(row["categories"])
        diversity_bonus = 1.0 + min(0.8, 0.12 * max(0, channel_count - 1))
        diversity_bonus += min(0.45, 0.08 * max(0, region_count - 1))
        diversity_bonus += min(0.35, 0.05 * max(0, category_count - 1))
        score = float(row["score"]) * diversity_bonus
        language = row["languages"].most_common(1)[0][0] if row["languages"] else "en"
        regions_sorted = sorted(row["regions"])
        categories_sorted = sorted(row["categories"])
        candidates.append(
            {
                "keyword": row["keyword"],
                "normalized_keyword": row["normalized_keyword"],
                "market_score": round(score, 2),
                "video_count": video_count,
                "channel_count": channel_count,
                "region_count": region_count,
                "category_count": category_count,
                "regions": ", ".join(regions_sorted),
                "category_names": ", ".join(
                    MARKET_DISCOVERY_CATEGORIES.get(x, x) for x in categories_sorted[:4]
                ),
                "language_code": language,
                "total_views": int(row["total_views"]),
                "average_views_per_day": int(row["total_views_per_day"] / max(1, video_count)),
                "sample_titles": list(row["titles"][:3]),
                "primary_region": regions_sorted[0] if regions_sorted else regions[0],
            }
        )

    candidates.sort(
        key=lambda row: (
            int(row["channel_count"]),
            int(row["video_count"]),
            int(row["region_count"]),
            float(row["market_score"]),
            int(row["average_views_per_day"]),
        ),
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    token_sets: list[set[str]] = []
    for row in candidates:
        tokens = set(_title_tokens(str(row["keyword"])))
        if any(
            len(tokens & prior) / max(1, min(len(tokens), len(prior))) >= 0.66
            for prior in token_sets
        ):
            continue
        selected.append(row)
        token_sets.append(tokens)
        if len(selected) >= max(1, min(int(top_n), 200)):
            break

    used_units = max(0, int(getattr(api, "quota_units_estimated", 0)) - started_units)
    return {
        "candidates": selected,
        "videos_analyzed": len(raw_by_id),
        "requests_attempted": len(regions) * len(categories),
        "api_units_estimated": used_units,
        "errors": errors,
        "regions": regions,
        "languages": languages,
        "categories": categories,
        "discovered_at": now.isoformat(),
    }

def discover_market_keywords(
    videos: list[dict[str, Any]],
    channels: list[dict[str, Any]],
    *,
    lookback_days: int = 30,
    top_n: int = 10,
    minimum_videos: int = 2,
    minimum_channels: int = 2,
) -> list[dict[str, Any]]:
    """Find useful market search phrases from tracked-channel video titles.

    This is not YouTube search volume. The ranking is based only on saved videos:
    phrase repetition, channel diversity, recency and views per day.
    """
    channel_map = {str(row.get("channel_id", "")): row for row in channels}
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, int(lookback_days)))
    recent: list[dict[str, Any]] = []
    for video in videos:
        published = parse_datetime(video.get("published_at"))
        if published and published >= cutoff:
            recent.append(video)
    # A newly installed tool may not yet have enough videos inside the requested
    # window. Fall back to the latest saved videos instead of returning nothing.
    if len(recent) < 20:
        recent = sorted(
            videos,
            key=lambda row: row.get("published_at") or "",
            reverse=True,
        )[:1000]
    else:
        # Balance high-volume and low-volume channels so one daily-upload channel
        # cannot dominate the candidate list. The cap also keeps Streamlit memory
        # stable when the videos table grows to tens of thousands of rows.
        recent = sorted(
            recent,
            key=lambda row: row.get("published_at") or "",
            reverse=True,
        )
        per_channel: Counter[str] = Counter()
        balanced: list[dict[str, Any]] = []
        for video in recent:
            channel_id = str(video.get("channel_id", ""))
            if per_channel[channel_id] >= 25:
                continue
            balanced.append(video)
            per_channel[channel_id] += 1
            if len(balanced) >= 4000:
                break
        recent = balanced

    stats: dict[str, dict[str, Any]] = {}
    for video in recent:
        title = str(video.get("title", "")).strip()
        video_id = str(video.get("video_id", ""))
        channel_id = str(video.get("channel_id", ""))
        if not title or not video_id or not channel_id:
            continue
        channel = channel_map.get(channel_id, {})
        published = parse_datetime(video.get("published_at"))
        age_days = max(
            1 / 24,
            ((now - published).total_seconds() / 86400) if published else 1.0,
        )
        views = int(video.get("view_count", 0) or 0)
        views_per_day = int(video.get("views_per_day", 0) or 0) or int(views / age_days)
        recency_factor = 1.0 if not published else max(0.35, 1.0 - min(age_days, 120) / 180)
        performance_weight = 1.0 + min(5.0, math.log10(max(views_per_day, 1) + 1))
        weight = performance_weight * recency_factor
        for phrase in _candidate_phrases(title):
            row = stats.setdefault(
                phrase,
                {
                    "keyword": phrase,
                    "normalized_keyword": normalize_keyword(phrase),
                    "score": 0.0,
                    "video_ids": set(),
                    "channel_ids": set(),
                    "titles": [],
                    "total_views": 0,
                    "total_views_per_day": 0,
                    "subjects": Counter(),
                    "niches": Counter(),
                    "countries": Counter(),
                },
            )
            if video_id in row["video_ids"]:
                continue
            phrase_size = len(phrase.split())
            length_factor = {2: 1.10, 3: 1.04, 4: 0.95}.get(phrase_size, 1.0)
            row["score"] += weight * length_factor
            row["video_ids"].add(video_id)
            row["channel_ids"].add(channel_id)
            if len(row["titles"]) < 5:
                row["titles"].append(title)
            row["total_views"] += views
            row["total_views_per_day"] += views_per_day
            subject = str(channel.get("auto_subject", "") or "").strip()
            niche = str(channel.get("auto_niche", "") or "").strip()
            country = str(channel.get("country", "") or "").upper().strip()
            if subject and subject != "Chưa phân loại":
                row["subjects"][subject] += 1
            if niche and niche != "Chưa phân loại":
                row["niches"][niche] += 1
            if country:
                row["countries"][country] += 1

    eligible: list[dict[str, Any]] = []
    for row in stats.values():
        video_count = len(row["video_ids"])
        channel_count = len(row["channel_ids"])
        if video_count < max(1, int(minimum_videos)) and channel_count < max(1, int(minimum_channels)):
            continue
        dominant_country = row["countries"].most_common(1)[0][0] if row["countries"] else "US"
        dominant_subject = row["subjects"].most_common(1)[0][0] if row["subjects"] else ""
        dominant_niche = row["niches"].most_common(1)[0][0] if row["niches"] else ""
        sample_text = " ".join(row["titles"][:3])
        phrase_tokens = set(_title_tokens(str(row["keyword"])))
        classification_tokens = set(
            _title_tokens(f"{dominant_subject} {dominant_niche}")
        )
        classification_overlap = len(phrase_tokens & classification_tokens)
        adjusted_score = float(row["score"]) * (1.0 + 0.22 * classification_overlap)
        eligible.append(
            {
                "keyword": row["keyword"],
                "normalized_keyword": row["normalized_keyword"],
                "score": round(adjusted_score, 2),
                "video_count": video_count,
                "channel_count": channel_count,
                "total_views": int(row["total_views"]),
                "average_views_per_day": int(row["total_views_per_day"] / max(1, video_count)),
                "subject": dominant_subject,
                "niche": dominant_niche,
                "region_code": dominant_country if len(dominant_country) == 2 else "US",
                "language_code": _infer_language(sample_text, dominant_country),
                "sample_titles": list(row["titles"][:3]),
                "_video_ids": set(row["video_ids"]),
            }
        )

    eligible.sort(
        key=lambda row: (
            int(row["channel_count"]),
            int(row["video_count"]),
            float(row["score"]),
            int(row["average_views_per_day"]),
        ),
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    selected_token_sets: list[set[str]] = []
    selected_video_sets: list[set[str]] = []
    for row in eligible:
        token_set = set(_title_tokens(str(row["keyword"])))
        video_set = set(row.get("_video_ids") or set())
        too_similar = False
        for prior_tokens, prior_videos in zip(selected_token_sets, selected_video_sets):
            shared = len(token_set & prior_tokens)
            overlap_coefficient = shared / max(1, min(len(token_set), len(prior_tokens)))
            source_overlap = len(video_set & prior_videos) / max(1, min(len(video_set), len(prior_videos)))
            if overlap_coefficient >= 0.50 or source_overlap >= 0.60:
                too_similar = True
                break
        if too_similar:
            continue
        cleaned_row = dict(row)
        cleaned_row.pop("_video_ids", None)
        selected.append(cleaned_row)
        selected_token_sets.append(token_set)
        selected_video_sets.append(video_set)
        if len(selected) >= max(1, int(top_n)):
            break
    return selected

def _views_per_day(video: dict[str, Any], now: datetime) -> int:
    published = parse_datetime(video.get("published_at"))
    if not published:
        age_days = 1.0
    else:
        age_hours = max(1.0, (now - published).total_seconds() / 3600)
        age_days = max(age_hours / 24, 1 / 24)
    return int(int(video.get("view_count", 0) or 0) / age_days)


def _deep_baselines(
    api: YouTubeDataAPI,
    channels: dict[str, dict[str, Any]],
    normalized_results: list[dict[str, Any]],
    deep_channel_limit: int,
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    if deep_channel_limit <= 0:
        return {}, 0

    best_vpd: dict[str, int] = defaultdict(int)
    for row in normalized_results:
        channel_id = str(row.get("channel_id", ""))
        best_vpd[channel_id] = max(best_vpd[channel_id], int(row.get("views_per_day", 0) or 0))
    selected_ids = [
        channel_id
        for channel_id, _ in sorted(best_vpd.items(), key=lambda item: item[1], reverse=True)
        if channel_id in channels
    ][: max(0, int(deep_channel_limit))]

    recent_by_channel: dict[str, list[dict[str, Any]]] = {}
    analyzed = 0
    for channel_id in selected_ids:
        channel = channels[channel_id]
        uploads = str(channel.get("uploads_playlist_id", ""))
        if not uploads:
            continue
        try:
            recent_by_channel[channel_id] = api.fetch_recent_videos(
                channel_id,
                uploads,
                lookback_days=365,
                max_pages=1,
            )
            analyzed += 1
        except Exception:
            # A single unavailable channel should not invalidate the whole market scan.
            recent_by_channel[channel_id] = []
    return recent_by_channel, analyzed


def _attach_market_outlier(
    row: dict[str, Any],
    recent_videos: list[dict[str, Any]],
    baseline_size: int = 20,
    minimum_baseline: int = 5,
) -> None:
    same_type: list[int] = []
    current_id = str(row.get("video_id", ""))
    current_type = str(row.get("video_type", "long"))
    for candidate in recent_videos:
        if str(candidate.get("video_id", "")) == current_id:
            continue
        seconds = duration_to_seconds(str(candidate.get("duration", "")))
        if market_video_type(seconds) != current_type:
            continue
        views = int(candidate.get("view_count", 0) or 0)
        if views > 0:
            same_type.append(views)
        if len(same_type) >= baseline_size:
            break

    if len(same_type) < minimum_baseline:
        row["channel_baseline_views"] = 0
        row["baseline_video_count"] = len(same_type)
        row["outlier_score"] = 0.0
        return
    baseline = int(median(same_type))
    row["channel_baseline_views"] = baseline
    row["baseline_video_count"] = len(same_type)
    row["outlier_score"] = round(int(row.get("view_count", 0) or 0) / max(baseline, 1), 2)


def run_market_scan(
    store: SupabaseStore,
    api: YouTubeDataAPI,
    *,
    query: str,
    region_code: str = "US",
    language_code: str = "en",
    video_type: str = "all",
    period_days: int = 30,
    result_limit: int = 24,
    subject: str = "",
    niche: str = "",
    keyword_id: int | None = None,
    deep_channel_limit: int = 10,
    order: str = "viewCount",
    force_refresh: bool = False,
    cache_minutes: int = 30,
) -> dict[str, Any]:
    cleaned_query = " ".join((query or "").strip().split())
    normalized_query = normalize_keyword(cleaned_query)
    if not normalized_query:
        raise ValueError("Từ khóa thị trường không được để trống")

    region_code = (region_code or "US").upper()
    language_code = (language_code or "en").lower()
    video_type = video_type if video_type in {"all", "long", "shorts"} else "all"
    period_days = max(1, int(period_days))
    result_limit = max(1, min(int(result_limit), 50))
    deep_channel_limit = max(0, min(int(deep_channel_limit), 20))

    if not force_refresh:
        scanned_after = (
            datetime.now(timezone.utc) - timedelta(minutes=max(1, cache_minutes))
        ).isoformat()
        recent_scan = store.get_recent_market_scan(
            normalized_query=normalized_query,
            region_code=region_code,
            language_code=language_code,
            video_type=video_type,
            period_days=period_days,
            result_limit=result_limit,
            search_order=order,
            deep_channel_limit=deep_channel_limit,
            scanned_after=scanned_after,
            keyword_id=keyword_id,
        )
        if recent_scan:
            cached_results = store.list_market_results(
                scan_id=int(recent_scan["id"]), limit=result_limit
            )
            return {"scan": recent_scan, "results": cached_results, "from_cache": True}

    started_units = int(getattr(api, "quota_units_estimated", 0))
    now = datetime.now(timezone.utc)
    published_after = (now - timedelta(days=period_days)).isoformat().replace("+00:00", "Z")
    fetch_limit = 50 if video_type != "all" else result_limit

    search_results = api.search_videos(
        cleaned_query,
        max_results=fetch_limit,
        region_code=region_code,
        published_after=published_after,
        order=order,
        relevance_language=language_code,
    )
    channel_ids = sorted({str(row.get("channel_id", "")) for row in search_results if row.get("channel_id")})
    channel_map = api.fetch_channels_by_ids(channel_ids) if channel_ids else {}

    normalized_results: list[dict[str, Any]] = []
    for search_rank, item in enumerate(search_results):
        seconds = duration_to_seconds(str(item.get("duration", "")))
        kind = market_video_type(seconds)
        if video_type != "all" and kind != video_type:
            continue
        channel = channel_map.get(str(item.get("channel_id", "")), {})
        row = {
            "keyword_id": keyword_id,
            "source_keyword": cleaned_query,
            "subject": subject.strip(),
            "niche": niche.strip(),
            "region_code": region_code,
            "language_code": language_code,
            "video_type": kind,
            "video_id": item.get("video_id", ""),
            "channel_id": item.get("channel_id", ""),
            "channel_title": item.get("channel_title", "") or channel.get("title", ""),
            "title": item.get("title", ""),
            "published_at": item.get("published_at"),
            "view_count": int(item.get("view_count", 0) or 0),
            "like_count": int(item.get("like_count", 0) or 0),
            "comment_count": int(item.get("comment_count", 0) or 0),
            "duration": item.get("duration", ""),
            "duration_seconds": seconds,
            "thumbnail_url": item.get("thumbnail_url", ""),
            "views_per_day": _views_per_day(item, now),
            "channel_subscriber_count": int(channel.get("subscriber_count", 0) or 0),
            "channel_total_view_count": int(channel.get("total_view_count", 0) or 0),
            "channel_video_count": int(channel.get("video_count", 0) or 0),
            "channel_country": channel.get("country", "") or region_code,
            "channel_thumbnail_url": channel.get("thumbnail_url", ""),
            "channel_published_at": channel.get("published_at"),
            "channel_uploads_playlist_id": channel.get("uploads_playlist_id", ""),
            "channel_baseline_views": 0,
            "baseline_video_count": 0,
            "outlier_score": 0.0,
            "discovered_at": now.isoformat(),
            "_search_rank": search_rank,
        }
        normalized_results.append(row)

    if order == "date":
        normalized_results.sort(key=lambda row: row.get("published_at") or "", reverse=True)
    elif order == "relevance":
        normalized_results.sort(key=lambda row: int(row.get("_search_rank", 0) or 0))
    else:
        normalized_results.sort(key=lambda row: int(row.get("view_count", 0) or 0), reverse=True)
    normalized_results = normalized_results[:result_limit]
    for row in normalized_results:
        row.pop("_search_rank", None)

    recent_by_channel, analyzed_channels = _deep_baselines(
        api, channel_map, normalized_results, deep_channel_limit
    )
    for row in normalized_results:
        _attach_market_outlier(
            row,
            recent_by_channel.get(str(row.get("channel_id", "")), []),
        )

    total_views = sum(int(row.get("view_count", 0) or 0) for row in normalized_results)
    average_vpd = int(
        sum(int(row.get("views_per_day", 0) or 0) for row in normalized_results)
        / max(1, len(normalized_results))
    )
    subscribers = [
        int(row.get("channel_subscriber_count", 0) or 0)
        for row in normalized_results
        if int(row.get("channel_subscriber_count", 0) or 0) > 0
    ]
    used_units = max(0, int(getattr(api, "quota_units_estimated", 0)) - started_units)
    scan_payload = {
        "keyword_id": keyword_id,
        "query": cleaned_query,
        "normalized_query": normalized_query,
        "subject": subject.strip(),
        "niche": niche.strip(),
        "region_code": region_code,
        "language_code": language_code,
        "video_type": video_type,
        "period_days": period_days,
        "result_limit": result_limit,
        "search_order": order,
        "deep_channel_limit": deep_channel_limit,
        "result_count": len(normalized_results),
        "total_views": total_views,
        "average_views_per_day": average_vpd,
        "unique_channels": len({str(row.get("channel_id", "")) for row in normalized_results}),
        "average_subscribers": int(sum(subscribers) / max(1, len(subscribers))) if subscribers else 0,
        "api_units_estimated": used_units,
        "deep_channels_analyzed": analyzed_channels,
        "status": "success",
        "error_message": "",
        "scanned_at": now.isoformat(),
    }
    scan = store.insert_market_scan(scan_payload)
    scan_id = int(scan["id"])
    for row in normalized_results:
        row["scan_id"] = scan_id
    store.insert_market_results(normalized_results)

    if keyword_id is not None:
        store.update_market_keyword(
            keyword_id,
            {
                "last_scanned_at": now.isoformat(),
                "last_result_count": len(normalized_results),
                "updated_at": now.isoformat(),
            },
        )
    return {"scan": scan, "results": normalized_results, "from_cache": False}


def latest_results_by_video(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(results, key=lambda row: row.get("discovered_at") or "", reverse=True)
    output: dict[str, dict[str, Any]] = {}
    for row in ordered:
        video_id = str(row.get("video_id", ""))
        if video_id and video_id not in output:
            output[video_id] = dict(row)
    return list(output.values())


def market_result_to_tracked_channel(result: dict[str, Any]) -> dict[str, Any]:
    channel_id = str(result.get("channel_id", ""))
    channel = {
        "channel_id": channel_id,
        "source_ref": canonical_channel_url(channel_id),
        "canonical_url": canonical_channel_url(channel_id),
        "handle": "",
        "title": result.get("channel_title", "") or channel_id,
        "description": "",
        "country": result.get("channel_country", ""),
        "published_at": result.get("channel_published_at"),
        "subscriber_count": int(result.get("channel_subscriber_count", 0) or 0),
        "hidden_subscriber_count": 0,
        "total_view_count": int(result.get("channel_total_view_count", 0) or 0),
        "video_count": int(result.get("channel_video_count", 0) or 0),
        "uploads_playlist_id": result.get("channel_uploads_playlist_id", ""),
        "channel_keywords": "",
        "topic_categories": "",
        "thumbnail_url": result.get("channel_thumbnail_url", ""),
        "last_video_id": result.get("video_id", ""),
        "last_video_title": result.get("title", ""),
        "last_video_published_at": result.get("published_at"),
        "last_video_views": int(result.get("view_count", 0) or 0),
        "videos_30d_count": 0,
        "views_of_videos_published_30d": 0,
        "frequency_per_week": 0,
        "updated_at": utc_now_iso(),
        "last_error": "",
    }
    classification = classify_channel(channel, [result])
    channel.update(classification)
    return channel


def growth_rate(current: int | float, previous: int | float) -> float:
    return (float(current or 0) - float(previous or 0)) / max(float(previous or 0), 1.0)


def keyword_growth_rows(
    keywords: list[dict[str, Any]],
    scans: list[dict[str, Any]],
    results: list[dict[str, Any]],
    window_days: int,
) -> list[dict[str, Any]]:
    keyword_map = {int(row["id"]): row for row in keywords if row.get("id") is not None}
    scans_by_keyword: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for scan in scans:
        if scan.get("keyword_id") is None or scan.get("status") != "success":
            continue
        scans_by_keyword[int(scan["keyword_id"])].append(scan)

    results_by_scan: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        if result.get("scan_id") is not None:
            results_by_scan[int(result["scan_id"])].append(result)

    now = datetime.now(timezone.utc)
    output: list[dict[str, Any]] = []
    for keyword_id, keyword in keyword_map.items():
        ordered = sorted(
            scans_by_keyword.get(keyword_id, []),
            key=lambda row: row.get("scanned_at") or "",
            reverse=True,
        )
        if len(ordered) < 2:
            continue
        latest = ordered[0]
        latest_dt = parse_datetime(latest.get("scanned_at")) or now
        target = latest_dt - timedelta(days=max(1, int(window_days)))
        older = [
            scan
            for scan in ordered[1:]
            if (parse_datetime(scan.get("scanned_at")) or now) < latest_dt
        ]
        if not older:
            continue
        reference = min(
            older,
            key=lambda scan: abs(
                ((parse_datetime(scan.get("scanned_at")) or target) - target).total_seconds()
            ),
        )

        result_growth = growth_rate(latest.get("result_count", 0), reference.get("result_count", 0))
        views_growth = growth_rate(latest.get("total_views", 0), reference.get("total_views", 0))
        vpd_growth = growth_rate(
            latest.get("average_views_per_day", 0), reference.get("average_views_per_day", 0)
        )
        channels_growth = growth_rate(
            latest.get("unique_channels", 0), reference.get("unique_channels", 0)
        )
        score = (
            result_growth * 0.20
            + views_growth * 0.30
            + vpd_growth * 0.30
            + channels_growth * 0.20
        )
        unique_channels = int(latest.get("unique_channels", 0) or 0)
        average_subscribers = int(latest.get("average_subscribers", 0) or 0)
        if unique_channels <= 10 and average_subscribers <= 100_000:
            competition = "Thấp"
        elif unique_channels <= 25 and average_subscribers <= 500_000:
            competition = "Trung bình"
        else:
            competition = "Cao"

        latest_results = sorted(
            results_by_scan.get(int(latest["id"]), []),
            key=lambda row: int(row.get("views_per_day", 0) or 0),
            reverse=True,
        )
        reference_results = results_by_scan.get(int(reference["id"]), [])
        latest_video_ids = {str(row.get("video_id", "")) for row in latest_results if row.get("video_id")}
        reference_video_ids = {str(row.get("video_id", "")) for row in reference_results if row.get("video_id")}
        new_video_count = len(latest_video_ids - reference_video_ids)
        top_titles = " | ".join(str(row.get("title", "")) for row in latest_results[:3])
        output.append(
            {
                "keyword_id": keyword_id,
                "Từ khóa": keyword.get("keyword", ""),
                "Chủ đề": keyword.get("subject", ""),
                "Ngách": keyword.get("niche", ""),
                "Quốc gia": keyword.get("region_code", ""),
                "Ngôn ngữ": keyword.get("language_code", ""),
                "Mức tăng": score,
                "Video mới": new_video_count,
                "Số video mẫu": int(latest.get("result_count", 0) or 0),
                "Thay đổi video": result_growth,
                "Tổng view mẫu": int(latest.get("total_views", 0) or 0),
                "Thay đổi view": views_growth,
                "View/ngày TB": int(latest.get("average_views_per_day", 0) or 0),
                "Thay đổi view/ngày": vpd_growth,
                "Số kênh": unique_channels,
                "Thay đổi số kênh": channels_growth,
                "Cạnh tranh": competition,
                "Video đang kéo từ khóa": top_titles,
                "Quét gần nhất": latest.get("scanned_at"),
                "Mốc so sánh": reference.get("scanned_at"),
            }
        )
    return sorted(output, key=lambda row: float(row.get("Mức tăng", 0) or 0), reverse=True)


def aggregate_market_channels(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        channel_id = str(row.get("channel_id", ""))
        if channel_id:
            grouped[channel_id].append(row)

    output: list[dict[str, Any]] = []
    for channel_id, rows in grouped.items():
        ordered = sorted(rows, key=lambda row: row.get("discovered_at") or "", reverse=True)
        latest = ordered[0]
        keywords = sorted({str(row.get("source_keyword", "")) for row in rows if row.get("source_keyword")})
        videos = {str(row.get("video_id", "")): row for row in rows if row.get("video_id")}
        best = max(
            videos.values(),
            key=lambda row: (int(row.get("views_per_day", 0) or 0), int(row.get("view_count", 0) or 0)),
            default=latest,
        )
        subscribers = int(latest.get("channel_subscriber_count", 0) or 0)
        best_views = int(best.get("view_count", 0) or 0)
        output.append(
            {
                "channel_id": channel_id,
                "Kênh": latest.get("channel_title", ""),
                "Subscriber": subscribers,
                "Số video phát hiện": len(videos),
                "Từ khóa phát hiện": ", ".join(keywords[:5]),
                "Video mạnh nhất": best.get("title", ""),
                "View video mạnh nhất": best_views,
                "View/ngày mạnh nhất": int(best.get("views_per_day", 0) or 0),
                "Outlier cao nhất": max(float(row.get("outlier_score", 0) or 0) for row in rows),
                "View/Subscriber": round(best_views / max(subscribers, 1), 2),
                "Chủ đề": latest.get("subject", ""),
                "Ngách": latest.get("niche", ""),
                "Quốc gia": latest.get("channel_country", ""),
                "Phát hiện gần nhất": latest.get("discovered_at"),
                "Link": canonical_channel_url(channel_id),
                "_result": latest,
            }
        )
    return sorted(
        output,
        key=lambda row: (
            float(row.get("Outlier cao nhất", 0) or 0),
            float(row.get("View/Subscriber", 0) or 0),
            int(row.get("View/ngày mạnh nhất", 0) or 0),
        ),
        reverse=True,
    )
