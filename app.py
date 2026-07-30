from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import html
import math
from typing import Any

import pandas as pd
import streamlit as st

from tracker.service_web import (
    add_outlier_scores,
    bulk_growth_by_channel,
    duration_to_seconds,
    sync_channel,
    sync_reference,
)
from tracker.market_service import (
    aggregate_market_channels,
    build_keyword_payload,
    estimate_market_scan_units,
    keyword_growth_rows,
    latest_results_by_video,
    market_result_to_tracked_channel,
    run_market_scan,
)
from tracker.supabase_store import SupabaseStore
from tracker.youtube_api import YouTubeDataAPI

st.set_page_config(
    page_title="YouTube Research",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = r"""
<style>
:root{
  --bg:#f6f8fb;
  --panel:#ffffff;
  --panel-soft:#f1f5f9;
  --line:#d9e1ec;
  --text:#172033;
  --muted:#667085;
  --accent:#4f46e5;
  --accent-soft:#eef2ff;
}
html,body,[class*="css"]{color:var(--text)}
.stApp{background:var(--bg);color:var(--text)}
[data-testid="stSidebar"]{background:#ffffff;border-right:1px solid var(--line)}
[data-testid="stSidebar"] *{color:var(--text)}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:var(--muted)!important}
[data-testid="stHeader"]{background:rgba(246,248,251,.94);border-bottom:1px solid rgba(217,225,236,.75)}
.block-container{padding-top:1.25rem;max-width:1500px}
h1,h2,h3{letter-spacing:-.02em;color:var(--text)}
p,li,label{color:var(--text)}
.muted,.meta{color:var(--muted)}
.card,.video-card,.kpi{background:var(--panel);border:1px solid var(--line);box-shadow:0 5px 18px rgba(15,23,42,.06)}
.card{border-radius:16px;padding:14px;height:100%}
.video-card{border-radius:14px;overflow:hidden;height:100%}
.video-card img{width:100%;aspect-ratio:16/9;object-fit:cover;display:block;background:#e5e7eb}
.video-body{padding:10px 11px 12px}
.video-title{font-weight:700;line-height:1.25;font-size:.94rem;min-height:2.35rem;color:var(--text)}
.meta{font-size:.78rem;margin-top:6px;line-height:1.35}
.badge{display:inline-block;background:var(--accent);color:white;border-radius:999px;padding:3px 8px;font-weight:700;font-size:.75rem;margin-bottom:7px}
.kpi{border-radius:16px;padding:18px}
.kpi-label{color:var(--muted);font-size:.82rem}
.kpi-value{font-size:1.75rem;font-weight:800;margin-top:4px;color:var(--text)}
.stButton>button{border-radius:10px;border:1px solid #cbd5e1;background:#ffffff;color:var(--text)}
.stButton>button:hover{border-color:var(--accent);color:var(--accent)}
.stButton>button[kind="primary"]{background:var(--accent);border-color:var(--accent);color:#ffffff}
.stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"],.stNumberInput input{
  background:#ffffff!important;color:var(--text)!important;border-color:#cbd5e1!important
}
.stTextInput input::placeholder,.stTextArea textarea::placeholder{color:#98a2b3!important}
/* Fix màu Selectbox/Multiselect trên Streamlit Community Cloud.
   BaseWeb render menu trong một portal ngoài .stApp nên phải đặt màu trực tiếp
   cho từng phần tử và toàn bộ phần tử con. */
[data-testid="stSelectbox"] div[data-baseweb="select"],
[data-testid="stMultiSelect"] div[data-baseweb="select"]{
  background:#ffffff!important;
  color:#172033!important;
  border-color:#cbd5e1!important;
}
[data-testid="stSelectbox"] div[data-baseweb="select"] *,
[data-testid="stMultiSelect"] div[data-baseweb="select"] *{
  color:#172033!important;
  -webkit-text-fill-color:#172033!important;
}
[data-baseweb="popover"],
[data-baseweb="popover"] > div,
[data-baseweb="menu"],
ul[role="listbox"],
[role="listbox"]{
  background:#ffffff!important;
  color:#172033!important;
}
[role="option"],
[role="option"] *,
[data-baseweb="menu"] li,
[data-baseweb="menu"] li *{
  color:#172033!important;
  -webkit-text-fill-color:#172033!important;
  opacity:1!important;
}
[role="option"]{background:#ffffff!important}
[role="option"]:hover,
[role="option"][aria-selected="true"]{background:#eef2ff!important}
[data-testid="stDataFrame"]{background:#ffffff;border:1px solid var(--line);border-radius:12px;overflow:hidden}
[data-testid="stMetric"]{background:#ffffff;border:1px solid var(--line);border-radius:12px;padding:12px}
[data-testid="stAlert"]{border-radius:12px}
hr{border-color:var(--line)!important}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

NAV_OPTIONS = [
    "Tổng quan",
    "Từ khóa tăng trong tuần",
    "Video vượt trội",
    "Toàn thị trường",
    "Kênh mới nổi",
    "Kênh theo dõi",
    "Từ khóa đã lưu",
    "Shorts",
    "Cài đặt",
]
VIDEO_DATA_PAGES = {"Tổng quan", "Video vượt trội", "Kênh mới nổi", "Shorts"}
MAX_SAVED_VIDEOS = 20_000


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default)).strip()
    except Exception:
        return default


def fmt_int(value: Any) -> str:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return "—"
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return f"{number:,}".replace(",", ".")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def age_text(value: str | None) -> str:
    published = parse_dt(value)
    if not published:
        return ""
    delta = datetime.now(timezone.utc) - published
    hours = max(0, int(delta.total_seconds() // 3600))
    if hours < 24:
        return "hôm nay" if hours == 0 else f"{hours} giờ trước"
    days = hours // 24
    if days < 30:
        return f"{days} ngày trước"
    if days < 365:
        return f"{days // 30} tháng trước"
    return f"{days // 365} năm trước"


def human_datetime(value: str | None) -> str:
    parsed = parse_dt(value)
    if not parsed:
        return "—"
    return parsed.astimezone().strftime("%d/%m/%Y %H:%M")


def is_short(video: dict[str, Any]) -> bool:
    seconds = int(video.get("duration_seconds") or 0)
    if not seconds:
        seconds = duration_to_seconds(str(video.get("duration", "")))
    return 0 < seconds <= 180


def video_card(video: dict[str, Any], show_channel: bool = True) -> str:
    title = html.escape(str(video.get("title", "")))
    thumbnail = html.escape(str(video.get("thumbnail_url", "")))
    channel = html.escape(
        str(video.get("channel_title") or video.get("channel_name") or "")
    )
    score = float(video.get("outlier_score") or 0)
    badge = f'<span class="badge">{score:.1f}×</span>' if score > 0 else ""
    meta: list[str] = []
    if show_channel and channel:
        meta.append(channel)
    if video.get("source"):
        meta.append(str(video.get("source")))
    meta.append(f'{fmt_int(video.get("view_count"))} views')
    if int(video.get("subscriber_count", 0) or 0) > 0:
        meta.append(f'{fmt_int(video.get("subscriber_count"))} subs')
    if video.get("views_per_day"):
        meta.append(f'{fmt_int(video.get("views_per_day"))}/ngày')
    if video.get("source_keyword"):
        meta.append(f'Key: {str(video.get("source_keyword"))[:38]}')
    if video.get("published_at"):
        meta.append(age_text(video.get("published_at")))
    video_id = html.escape(str(video.get("video_id", "")))
    url = f"https://www.youtube.com/watch?v={video_id}"
    image = (
        f'<a href="{url}" target="_blank"><img src="{thumbnail}" loading="lazy"></a>'
        if thumbnail
        else '<div style="aspect-ratio:16/9;background:#e5e7eb"></div>'
    )
    return (
        f'<div class="video-card">{image}<div class="video-body">{badge}'
        f'<div class="video-title"><a href="{url}" target="_blank" style="color:inherit;text-decoration:none">{title}</a></div>'
        f'<div class="meta">{" · ".join(meta)}</div></div></div>'
    )


def render_video_grid(videos: list[dict[str, Any]], columns_count: int = 4) -> None:
    for start in range(0, len(videos), columns_count):
        columns = st.columns(columns_count)
        for column, video in zip(columns, videos[start : start + columns_count]):
            with column:
                st.markdown(video_card(video), unsafe_allow_html=True)


def get_credentials() -> tuple[str, str, str]:
    return (
        secret("SUPABASE_URL"),
        secret("SUPABASE_KEY"),
        secret("YOUTUBE_API_KEY"),
    )


def get_clients() -> tuple[SupabaseStore, YouTubeDataAPI | None, str, str]:
    supabase_url, supabase_key, youtube_key = get_credentials()
    if not supabase_url or not supabase_key:
        st.error(
            "Chưa cấu hình Supabase. Hãy thêm SUPABASE_URL và SUPABASE_KEY vào Streamlit Secrets."
        )
        st.stop()
    store = SupabaseStore(supabase_url, supabase_key)
    api = YouTubeDataAPI(youtube_key) if youtube_key else None
    return store, api, supabase_url, supabase_key


@st.cache_data(ttl=300, show_spinner=False)
def load_saved_channels(supabase_url: str, _supabase_key: str) -> list[dict[str, Any]]:
    return SupabaseStore(supabase_url, _supabase_key).list_channels()


@st.cache_data(ttl=300, show_spinner=False)
def load_saved_videos(
    supabase_url: str,
    _supabase_key: str,
    limit: int = MAX_SAVED_VIDEOS,
) -> list[dict[str, Any]]:
    return SupabaseStore(supabase_url, _supabase_key).list_videos(limit=limit)


@st.cache_data(ttl=300, show_spinner=False)
def load_saved_snapshots(
    supabase_url: str,
    _supabase_key: str,
    limit: int = 25_000,
) -> list[dict[str, Any]]:
    return SupabaseStore(supabase_url, _supabase_key).list_snapshots(limit=limit)


@st.cache_data(ttl=300, show_spinner=False)
def market_schema_ready(supabase_url: str, _supabase_key: str) -> bool:
    return SupabaseStore(supabase_url, _supabase_key).market_schema_ready()


@st.cache_data(ttl=300, show_spinner=False)
def load_market_keywords(
    supabase_url: str,
    _supabase_key: str,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    return SupabaseStore(supabase_url, _supabase_key).list_market_keywords(
        active_only=active_only
    )


@st.cache_data(ttl=300, show_spinner=False)
def load_market_scans(
    supabase_url: str,
    _supabase_key: str,
    limit: int = 2_000,
) -> list[dict[str, Any]]:
    return SupabaseStore(supabase_url, _supabase_key).list_market_scans(limit=limit)


@st.cache_data(ttl=300, show_spinner=False)
def load_market_results(
    supabase_url: str,
    _supabase_key: str,
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    return SupabaseStore(supabase_url, _supabase_key).list_market_results(limit=limit)


def clear_saved_data_cache() -> None:
    load_saved_channels.clear()
    load_saved_videos.clear()
    load_saved_snapshots.clear()
    market_schema_ready.clear()
    load_market_keywords.clear()
    load_market_scans.clear()
    load_market_results.clear()


def attach_channel_context(
    videos: list[dict[str, Any]],
    channels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    channel_map = {str(channel.get("channel_id")): channel for channel in channels}
    rows: list[dict[str, Any]] = []
    for video in videos:
        row = dict(video)
        channel = channel_map.get(str(video.get("channel_id")), {})
        row["channel_name"] = channel.get("title", "")
        row["channel_title"] = channel.get("title", "")
        row["subscriber_count"] = int(channel.get("subscriber_count", 0) or 0)
        row["country"] = channel.get("country", "") or "Không rõ"
        row["auto_subject"] = channel.get("auto_subject", "") or "Chưa phân loại"
        row["auto_niche"] = channel.get("auto_niche", "") or "Chưa phân loại"
        rows.append(row)
    return rows


def market_tables_or_notice(
    supabase_url: str,
    supabase_key: str,
) -> bool:
    try:
        ready = market_schema_ready(supabase_url, supabase_key)
    except Exception as exc:
        st.error(f"Không kiểm tra được schema nghiên cứu thị trường: {exc}")
        return False
    if not ready:
        st.warning(
            "Chưa có 3 bảng nghiên cứu thị trường trong Supabase. "
            "Hãy chạy file `supabase_market_migration.sql` trong SQL Editor rồi Reboot app."
        )
        return False
    return True


def market_result_as_video(row: dict[str, Any]) -> dict[str, Any]:
    video = dict(row)
    video["channel_name"] = row.get("channel_title", "")
    video["subscriber_count"] = int(row.get("channel_subscriber_count", 0) or 0)
    video["country"] = row.get("channel_country", "") or row.get("region_code", "") or "Không rõ"
    video["auto_subject"] = row.get("subject", "") or "Chưa phân loại"
    video["auto_niche"] = row.get("niche", "") or "Chưa phân loại"
    video["source"] = "Toàn thị trường"
    return video


def combine_video_sources(
    tracked_rows: list[dict[str, Any]],
    market_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    for market in latest_results_by_video(market_rows):
        video = market_result_as_video(market)
        video_id = str(video.get("video_id", ""))
        if video_id:
            combined[video_id] = video
    for tracked in tracked_rows:
        video = dict(tracked)
        video_id = str(video.get("video_id", ""))
        video["source"] = "Kênh theo dõi"
        if video_id in combined:
            market = combined[video_id]
            video["source"] = "Cả hai"
            video["source_keyword"] = market.get("source_keyword", "")
            if float(video.get("outlier_score", 0) or 0) <= 0:
                video["outlier_score"] = float(market.get("outlier_score", 0) or 0)
                video["channel_median_views"] = int(market.get("channel_baseline_views", 0) or 0)
                video["baseline_video_count"] = int(market.get("baseline_video_count", 0) or 0)
        if video_id:
            combined[video_id] = video
    return list(combined.values())


def render_market_video_grid(
    rows: list[dict[str, Any]],
    *,
    store: SupabaseStore,
    tracked_channel_ids: set[str],
    columns_count: int = 4,
) -> None:
    for start in range(0, len(rows), columns_count):
        columns = st.columns(columns_count)
        for column, row in zip(columns, rows[start : start + columns_count]):
            with column:
                video = market_result_as_video(row)
                st.markdown(video_card(video), unsafe_allow_html=True)
                channel_id = str(row.get("channel_id", ""))
                if channel_id in tracked_channel_ids:
                    st.caption("✓ Kênh này đã nằm trong danh sách theo dõi")
                elif st.button(
                    "＋ Theo dõi kênh",
                    key=f"track_market_{row.get('scan_id')}_{row.get('video_id')}",
                    use_container_width=True,
                ):
                    try:
                        store.upsert_channel(market_result_to_tracked_channel(row))
                        clear_saved_data_cache()
                        st.session_state["flash_message"] = (
                            f"Đã thêm kênh {row.get('channel_title') or channel_id} vào danh sách theo dõi. "
                            "Bạn có thể sang trang Kênh theo dõi để quét dữ liệu đầy đủ."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Không thêm được kênh: {exc}")


def load_market_bundle(
    supabase_url: str,
    supabase_key: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        load_market_keywords(supabase_url, supabase_key),
        load_market_scans(supabase_url, supabase_key),
        load_market_results(supabase_url, supabase_key),
    )


def execute_market_scan_ui(
    *,
    store: SupabaseStore,
    api: YouTubeDataAPI | None,
    query: str,
    region_code: str,
    language_code: str,
    video_type: str,
    period_days: int,
    result_limit: int,
    subject: str,
    niche: str,
    keyword_id: int | None,
    deep_channel_limit: int,
    order: str,
    force_refresh: bool,
) -> dict[str, Any] | None:
    if not api:
        st.error("Chưa cấu hình YOUTUBE_API_KEY trong Streamlit Secrets.")
        return None
    try:
        with st.spinner("Đang tìm video, lấy dữ liệu kênh và lưu lịch sử vào Supabase..."):
            outcome = run_market_scan(
                store,
                api,
                query=query,
                region_code=region_code,
                language_code=language_code,
                video_type=video_type,
                period_days=int(period_days),
                result_limit=int(result_limit),
                subject=subject,
                niche=niche,
                keyword_id=keyword_id,
                deep_channel_limit=int(deep_channel_limit),
                order=order,
                force_refresh=force_refresh,
            )
        clear_saved_data_cache()
        st.session_state["market_active_scan_id"] = int(outcome["scan"]["id"])
        st.session_state["market_active_keyword_id"] = keyword_id
        st.session_state["market_results"] = outcome["results"]
        if outcome.get("from_cache"):
            st.info("Đã dùng kết quả quét gần đây trong Supabase, không gọi lại YouTube API.")
        else:
            st.success(
                f"Đã lưu {len(outcome['results'])} video. "
                f"Ước tính dùng {int(outcome['scan'].get('api_units_estimated', 0) or 0)} quota units."
            )
        return outcome
    except Exception as exc:
        st.error(f"Không thể quét toàn thị trường: {exc}")
        return None


def filter_by_period(
    videos: list[dict[str, Any]],
    period_label: str,
) -> list[dict[str, Any]]:
    periods = {
        "24 giờ": timedelta(hours=24),
        "3 ngày": timedelta(days=3),
        "7 ngày": timedelta(days=7),
        "30 ngày": timedelta(days=30),
        "Tất cả": None,
    }
    delta = periods.get(period_label)
    if delta is None:
        return list(videos)
    cutoff = datetime.now(timezone.utc) - delta
    return [
        video
        for video in videos
        if (parse_dt(video.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc))
        >= cutoff
    ]


def show_paged_videos(
    videos: list[dict[str, Any]],
    *,
    result_limit: int,
    page_key: str,
    columns_count: int = 4,
    items_per_page: int = 24,
) -> None:
    total_matches = len(videos)
    limited = videos[:result_limit]
    total_pages = max(1, math.ceil(len(limited) / items_per_page))
    top_left, top_right = st.columns([4, 1])
    top_left.caption(
        f"Tìm thấy {total_matches} kết quả · đang cho phép hiển thị tối đa {result_limit}."
    )
    with top_right:
        page = st.selectbox(
            "Trang",
            list(range(1, total_pages + 1)),
            key=page_key,
            disabled=total_pages <= 1,
        )
    start = (int(page) - 1) * items_per_page
    page_rows = limited[start : start + items_per_page]
    if not page_rows:
        st.info("Không có video phù hợp với bộ lọc hiện tại.")
        return
    render_video_grid(page_rows, columns_count=columns_count)


def scan_channels_ui(
    store: SupabaseStore,
    api: YouTubeDataAPI | None,
    channels_to_scan: list[dict[str, Any]],
    lookback_days: int,
    max_pages: int,
    action_label: str,
) -> None:
    if not api:
        st.error("Chưa cấu hình YOUTUBE_API_KEY trong Streamlit Secrets.")
        return
    if not channels_to_scan:
        st.warning("Chưa có kênh nào được chọn.")
        return

    progress = st.progress(0.0)
    status = st.empty()
    errors: list[str] = []
    success_count = 0
    total = len(channels_to_scan)
    batch_size = 10
    processed = 0
    for batch_start in range(0, total, batch_size):
        batch = channels_to_scan[batch_start : batch_start + batch_size]
        batch_number = batch_start // batch_size + 1
        total_batches = math.ceil(total / batch_size)
        for channel in batch:
            processed += 1
            title = str(channel.get("title") or channel.get("channel_id"))
            try:
                sync_channel(
                    store,
                    api,
                    str(channel["channel_id"]),
                    lookback_days,
                    max_pages,
                )
                success_count += 1
                status.info(
                    f"Batch {batch_number}/{total_batches} · {processed}/{total} · Đã cập nhật {title}"
                )
            except Exception as exc:  # One broken channel must not stop the batch.
                errors.append(f"{title}: {exc}")
                status.warning(
                    f"Batch {batch_number}/{total_batches} · {processed}/{total} · Lỗi {title}"
                )
            progress.progress(processed / max(1, total))

    clear_saved_data_cache()
    st.session_state["flash_message"] = (
        f"{action_label}: cập nhật thành công {success_count}/{total} kênh"
        + (f", có {len(errors)} lỗi." if errors else ".")
    )
    if errors:
        st.session_state["flash_errors"] = errors
    st.rerun()


def latest_timestamp(channels: list[dict[str, Any]], videos: list[dict[str, Any]]) -> str:
    candidates: list[datetime] = []
    for row, field in [
        *((channel, "updated_at") for channel in channels),
        *((video, "last_seen_at") for video in videos),
    ]:
        parsed = parse_dt(row.get(field))
        if parsed:
            candidates.append(parsed)
    if not candidates:
        return "—"
    return human_datetime(max(candidates).isoformat())


with st.sidebar:
    st.markdown("## 🔎 YouTube Research")
    st.caption("Dashboard 2-in-1 nghiên cứu YouTube")
    st.caption("📌 Tool 1: Kênh theo dõi · 🌍 Tool 2: Toàn thị trường")
    nav = st.radio(
        "Điều hướng",
        NAV_OPTIONS,
        key="main_navigation",
    )
    st.divider()
    with st.expander("Thiết lập quét", expanded=False):
        lookback_days = st.slider(
            "Số ngày quét video",
            min_value=30,
            max_value=180,
            value=60,
            step=10,
            key="scan_lookback_days",
        )
        max_pages = st.slider(
            "Số trang mỗi kênh",
            min_value=1,
            max_value=10,
            value=4,
            step=1,
            key="scan_max_pages",
        )
    st.caption(
        "API key chỉ đọc từ Streamlit Secrets và không được hiển thị trên giao diện."
    )

store, api, supabase_url, supabase_key = get_clients()

if flash_message := st.session_state.pop("flash_message", None):
    st.success(flash_message)
if flash_errors := st.session_state.pop("flash_errors", None):
    with st.expander(f"Xem {len(flash_errors)} lỗi quét"):
        for flash_error in flash_errors:
            st.write(flash_error)

try:
    with st.spinner("Đang đọc dữ liệu đã lưu từ Supabase..."):
        channels = load_saved_channels(supabase_url, supabase_key)
        videos: list[dict[str, Any]] = []
        if nav in VIDEO_DATA_PAGES:
            videos = load_saved_videos(supabase_url, supabase_key, MAX_SAVED_VIDEOS)
except Exception as exc:
    st.error(f"Không thể tải dữ liệu đã lưu: {exc}")
    st.stop()

st.markdown(f"# {nav}")

if nav == "Tổng quan":
    st.caption(
        "Một web, hai nguồn dữ liệu: ① các kênh bạn chủ động theo dõi và "
        "② toàn thị trường được khám phá theo từ khóa đã lưu. Không nguồn nào tự quét khi mở trang."
    )
    try:
        snapshots = load_saved_snapshots(supabase_url, supabase_key)
    except Exception as exc:
        snapshots = []
        st.warning(f"Không tải được snapshot tăng trưởng kênh: {exc}")

    contextual = attach_channel_context(videos, channels)
    tracked_scored = add_outlier_scores(contextual)
    growth7 = bulk_growth_by_channel(channels, snapshots, 7) if snapshots else {}
    growth_values = [value for value in growth7.values() if value is not None]
    now = datetime.now(timezone.utc)
    tracked_outlier_7d = sum(
        1
        for video in tracked_scored
        if float(video.get("outlier_score") or 0) >= 2
        and (parse_dt(video.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc))
        >= now - timedelta(days=7)
    )

    market_ready = False
    market_keywords: list[dict[str, Any]] = []
    market_scans: list[dict[str, Any]] = []
    market_results: list[dict[str, Any]] = []
    try:
        market_ready = market_schema_ready(supabase_url, supabase_key)
        if market_ready:
            market_keywords, market_scans, market_results = load_market_bundle(
                supabase_url, supabase_key
            )
    except Exception as exc:
        st.warning(f"Chưa đọc được dữ liệu toàn thị trường: {exc}")
    latest_market = latest_results_by_video(market_results)
    active_keywords = sum(1 for row in market_keywords if bool(row.get("is_active")))
    market_channels = {str(row.get("channel_id", "")) for row in latest_market if row.get("channel_id")}
    latest_scan_time = market_scans[0].get("scanned_at") if market_scans else None

    st.markdown("### ① Tool theo dõi kênh đã nhập")
    tracked_kpis = st.columns(4)
    tracked_values = [
        ("Kênh theo dõi", len(channels)),
        ("Video đã lưu", len(videos)),
        ("Outlier ≥2× trong 7 ngày", tracked_outlier_7d),
        ("View kênh tăng 7 ngày", sum(growth_values) if growth_values else None),
    ]
    for column, (label, value) in zip(tracked_kpis, tracked_values):
        with column:
            display = fmt_int(value) if value is not None else "—"
            st.markdown(
                f'<div class="kpi"><div class="kpi-label">{label}</div>'
                f'<div class="kpi-value">{display}</div></div>',
                unsafe_allow_html=True,
            )
    tracked_actions = st.columns([3, 1, 1])
    tracked_actions[0].caption(
        f"Dữ liệu kênh cập nhật gần nhất: {latest_timestamp(channels, videos)}"
    )
    tracked_actions[1].button(
        "Mở Kênh theo dõi",
        use_container_width=True,
        on_click=lambda: st.session_state.update({"main_navigation": "Kênh theo dõi"}),
        key="overview_open_channels",
    )
    tracked_actions[2].button(
        "Mở Video vượt trội",
        use_container_width=True,
        on_click=lambda: st.session_state.update({"main_navigation": "Video vượt trội"}),
        key="overview_open_outliers",
    )

    with st.expander("Quét dữ liệu mới cho các kênh theo dõi", expanded=False):
        st.warning(
            f"Thao tác này gọi YouTube API cho {len(channels)} kênh. "
            "Web không tự chạy thao tác này khi mở trang."
        )
        confirm_scan = st.checkbox(
            "Tôi xác nhận quét toàn bộ kênh",
            key="overview_confirm_full_scan",
        )
        if st.button(
            "Quét dữ liệu kênh",
            type="primary",
            disabled=not confirm_scan or not channels,
            key="overview_scan_button",
        ):
            scan_channels_ui(
                store,
                api,
                channels,
                lookback_days,
                max_pages,
                "Quét dữ liệu kênh",
            )

    st.markdown("### ② Tool nghiên cứu toàn thị trường")
    market_kpis = st.columns(4)
    market_values = [
        ("Từ khóa đang hoạt động", active_keywords),
        ("Video thị trường gần nhất", len(latest_market)),
        ("Kênh mới phát hiện", len(market_channels)),
        ("Lần quét thị trường gần nhất", human_datetime(latest_scan_time)),
    ]
    for column, (label, value) in zip(market_kpis, market_values):
        with column:
            display = fmt_int(value) if isinstance(value, int) else str(value or "—")
            st.markdown(
                f'<div class="kpi"><div class="kpi-label">{label}</div>'
                f'<div class="kpi-value" style="font-size:1.35rem">{display}</div></div>',
                unsafe_allow_html=True,
            )
    market_actions = st.columns([3, 1, 1])
    if market_ready:
        market_actions[0].caption(
            "Kết quả thị trường được lưu theo từng lần quét để so sánh 24 giờ, 3 ngày, 7 ngày và 30 ngày."
        )
    else:
        market_actions[0].warning(
            "Chưa chạy `supabase_market_migration.sql`, nên Tool ② chưa thể lưu dữ liệu."
        )
    market_actions[1].button(
        "Mở Toàn thị trường",
        use_container_width=True,
        on_click=lambda: st.session_state.update({"main_navigation": "Toàn thị trường"}),
        key="overview_open_market",
    )
    market_actions[2].button(
        "Mở Từ khóa đã lưu",
        use_container_width=True,
        on_click=lambda: st.session_state.update({"main_navigation": "Từ khóa đã lưu"}),
        key="overview_open_keywords",
    )

    preview_columns = st.columns(2)
    with preview_columns[0]:
        st.markdown("#### Nổi bật từ kênh theo dõi")
        tracked_preview = sorted(
            [row for row in tracked_scored if float(row.get("outlier_score") or 0) >= 1.2],
            key=lambda row: (
                float(row.get("outlier_score") or 0),
                int(row.get("views_per_day") or 0),
            ),
            reverse=True,
        )[:4]
        if tracked_preview:
            render_video_grid(tracked_preview, columns_count=2)
        else:
            st.info("Chưa có video theo dõi đạt ngưỡng 1.2×.")
    with preview_columns[1]:
        st.markdown("#### Nổi bật từ toàn thị trường")
        market_preview = sorted(
            latest_market,
            key=lambda row: int(row.get("views_per_day", 0) or 0),
            reverse=True,
        )[:4]
        if market_preview:
            render_video_grid(
                [market_result_as_video(row) for row in market_preview],
                columns_count=2,
            )
        elif market_ready:
            st.info("Chưa có dữ liệu. Hãy lưu từ khóa rồi bấm quét thị trường.")
        else:
            st.info("Chạy migration Supabase để kích hoạt Tool ②.")
elif nav == "Video vượt trội":
    st.caption(
        "Trang này gộp cả hai nguồn. Video từ kênh theo dõi dùng median video cũ của chính kênh; "
        "video toàn thị trường chỉ có outlier khi kênh đó đã được phân tích sâu trong lúc quét."
    )
    tracked_contextual = attach_channel_context(videos, channels)
    tracked_scored = add_outlier_scores(tracked_contextual, baseline_size=20)

    market_rows: list[dict[str, Any]] = []
    market_ready = False
    try:
        market_ready = market_schema_ready(supabase_url, supabase_key)
        if market_ready:
            market_rows = load_market_results(supabase_url, supabase_key)
    except Exception as exc:
        st.warning(f"Không đọc được video toàn thị trường: {exc}")
    scored = combine_video_sources(tracked_scored, market_rows)

    threshold_mode = st.radio(
        "Ngưỡng vượt trội",
        ["Tất cả", "≥1.2x", "≥2x", "≥5x", "≥10x", "≥20x", "Kênh nhỏ bùng nổ"],
        horizontal=True,
        key="outlier_threshold_mode",
    )

    countries = ["Tất cả"] + sorted(
        {str(video.get("country")) for video in scored if video.get("country")}
    )
    subjects = ["Tất cả"] + sorted(
        {str(video.get("auto_subject")) for video in scored if video.get("auto_subject")}
    )
    niches = ["Tất cả"] + sorted(
        {str(video.get("auto_niche")) for video in scored if video.get("auto_niche")}
    )
    source_options = ["Tất cả", "Kênh theo dõi"]
    if market_ready:
        source_options.insert(2, "Toàn thị trường")

    with st.expander("Bộ lọc", expanded=True):
        row1 = st.columns(5)
        with row1[0]:
            result_limit = st.selectbox(
                "Số lượng hiển thị",
                [20, 50, 100, 200],
                index=1,
                key="outlier_result_limit",
            )
        with row1[1]:
            period = st.selectbox(
                "Thời gian",
                ["24 giờ", "3 ngày", "7 ngày", "30 ngày", "Tất cả"],
                index=3,
                key="outlier_period",
            )
        with row1[2]:
            video_type = st.selectbox(
                "Loại video",
                ["Tất cả", "Video dài", "Shorts"],
                key="outlier_video_type",
            )
        with row1[3]:
            source_filter = st.selectbox(
                "Nguồn",
                source_options,
                key="outlier_source",
            )
        with row1[4]:
            country = st.selectbox("Quốc gia", countries, key="outlier_country")

        row2 = st.columns(5)
        with row2[0]:
            minimum_views = st.number_input(
                "View tối thiểu",
                min_value=0,
                value=0,
                step=1_000,
                key="outlier_min_views",
            )
        with row2[1]:
            maximum_subscribers = st.number_input(
                "Subscriber tối đa",
                min_value=0,
                value=10_000_000,
                step=10_000,
                key="outlier_max_subscribers",
            )
        with row2[2]:
            subject = st.selectbox("Chủ đề", subjects, key="outlier_subject")
        with row2[3]:
            niche = st.selectbox("Ngách", niches, key="outlier_niche")
        with row2[4]:
            sort_by = st.selectbox(
                "Sắp xếp theo",
                ["Hệ số vượt trội", "View/ngày", "Lượt xem", "Mới nhất"],
                key="outlier_sort",
            )
        keyword = st.text_input(
            "Lọc tiêu đề hoặc từ khóa nguồn",
            placeholder="Nhập một phần tiêu đề hoặc từ khóa thị trường",
            key="outlier_keyword",
        ).strip().lower()

    filtered = filter_by_period(scored, period)
    if source_filter == "Kênh theo dõi":
        filtered = [
            row for row in filtered if row.get("source") in {"Kênh theo dõi", "Cả hai"}
        ]
    elif source_filter == "Toàn thị trường":
        filtered = [
            row for row in filtered if row.get("source") in {"Toàn thị trường", "Cả hai"}
        ]

    thresholds = {"≥1.2x": 1.2, "≥2x": 2.0, "≥5x": 5.0, "≥10x": 10.0, "≥20x": 20.0}
    if threshold_mode in thresholds:
        filtered = [
            video
            for video in filtered
            if float(video.get("outlier_score") or 0) >= thresholds[threshold_mode]
        ]
    elif threshold_mode == "Kênh nhỏ bùng nổ":
        filtered = [
            video
            for video in filtered
            if int(video.get("subscriber_count") or 0) <= int(maximum_subscribers)
            and int(video.get("view_count") or 0)
            > max(1, int(video.get("subscriber_count") or 0))
            and (
                float(video.get("outlier_score") or 0) >= 2
                or int(video.get("views_per_day") or 0) >= 10_000
            )
            and (parse_dt(video.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc))
            >= datetime.now(timezone.utc) - timedelta(days=30)
        ]

    if video_type == "Video dài":
        filtered = [video for video in filtered if not is_short(video)]
    elif video_type == "Shorts":
        filtered = [video for video in filtered if is_short(video)]
    if country != "Tất cả":
        filtered = [video for video in filtered if video.get("country") == country]
    if subject != "Tất cả":
        filtered = [video for video in filtered if video.get("auto_subject") == subject]
    if niche != "Tất cả":
        filtered = [video for video in filtered if video.get("auto_niche") == niche]
    filtered = [
        video
        for video in filtered
        if int(video.get("view_count") or 0) >= int(minimum_views)
        and int(video.get("subscriber_count") or 0) <= int(maximum_subscribers)
        and (
            not keyword
            or keyword in str(video.get("title", "")).lower()
            or keyword in str(video.get("source_keyword", "")).lower()
        )
    ]

    sort_keys = {
        "Hệ số vượt trội": lambda row: (
            float(row.get("outlier_score") or 0),
            int(row.get("views_per_day") or 0),
        ),
        "View/ngày": lambda row: int(row.get("views_per_day") or 0),
        "Lượt xem": lambda row: int(row.get("view_count") or 0),
        "Mới nhất": lambda row: row.get("published_at") or "",
    }
    filtered = sorted(filtered, key=sort_keys[sort_by], reverse=True)

    source_counts = {
        "Kênh theo dõi": sum(1 for row in filtered if row.get("source") in {"Kênh theo dõi", "Cả hai"}),
        "Toàn thị trường": sum(1 for row in filtered if row.get("source") in {"Toàn thị trường", "Cả hai"}),
    }
    st.caption(
        f"Sau bộ lọc: {len(filtered)} video · từ kênh theo dõi: {source_counts['Kênh theo dõi']} · "
        f"từ toàn thị trường: {source_counts['Toàn thị trường']}."
    )
    if not filtered:
        st.info(
            "Không có video đạt điều kiện. Hãy thử ngưỡng ≥1.2x, tăng thời gian lên 30 ngày hoặc giảm View tối thiểu."
        )
    else:
        show_paged_videos(
            filtered,
            result_limit=int(result_limit),
            page_key="outlier_page",
            columns_count=4,
            items_per_page=24,
        )
elif nav == "Toàn thị trường":
    st.caption(
        "Tool ② tìm video và kênh mới trên toàn YouTube theo từ khóa. Chỉ gọi API khi bạn bấm quét; "
        "kết quả được lưu vào Supabase để dùng lại và so sánh tăng trưởng."
    )
    if not market_tables_or_notice(supabase_url, supabase_key):
        st.code("supabase_market_migration.sql", language="text")
        st.stop()

    market_keywords = load_market_keywords(supabase_url, supabase_key)
    active_keywords = [row for row in market_keywords if bool(row.get("is_active"))]
    keyword_by_id = {int(row["id"]): row for row in market_keywords}

    requested_keyword_id = st.session_state.pop("market_open_keyword_id", None)
    if requested_keyword_id is not None and int(requested_keyword_id) in keyword_by_id:
        st.session_state["market_mode"] = "Dùng từ khóa đã lưu"
        st.session_state["market_saved_keyword_id"] = int(requested_keyword_id)

    mode_options = ["Tìm nhanh"] + (["Dùng từ khóa đã lưu"] if market_keywords else [])
    if st.session_state.get("market_mode") not in mode_options:
        st.session_state["market_mode"] = mode_options[0]
    mode = st.radio(
        "Chế độ tìm",
        mode_options,
        horizontal=True,
        key="market_mode",
    )

    selected_keyword: dict[str, Any] | None = None
    if mode == "Dùng từ khóa đã lưu":
        default_id = int(st.session_state.get("market_saved_keyword_id") or market_keywords[0]["id"])
        if default_id not in keyword_by_id:
            default_id = int(market_keywords[0]["id"])
        if st.session_state.get("market_saved_keyword_id") not in keyword_by_id:
            st.session_state["market_saved_keyword_id"] = default_id
        selected_id = st.selectbox(
            "Từ khóa đã lưu",
            options=list(keyword_by_id),
            index=list(keyword_by_id).index(default_id),
            format_func=lambda keyword_id: (
                f"{keyword_by_id[keyword_id].get('keyword')} · "
                f"{keyword_by_id[keyword_id].get('region_code')} · "
                f"{keyword_by_id[keyword_id].get('video_type')}"
            ),
            key="market_saved_keyword_id",
        )
        selected_keyword = keyword_by_id[int(selected_id)]

    config_key = str(selected_keyword.get("id")) if selected_keyword else "quick"
    default_query = str(selected_keyword.get("keyword", "")) if selected_keyword else ""
    default_region = str(selected_keyword.get("region_code", "US")) if selected_keyword else "US"
    default_language = str(selected_keyword.get("language_code", "en")) if selected_keyword else "en"
    default_type = str(selected_keyword.get("video_type", "all")) if selected_keyword else "all"
    default_days = int(selected_keyword.get("period_days", 30) or 30) if selected_keyword else 30
    default_limit = int(selected_keyword.get("result_limit", 24) or 24) if selected_keyword else 24
    default_subject = str(selected_keyword.get("subject", "")) if selected_keyword else ""
    default_niche = str(selected_keyword.get("niche", "")) if selected_keyword else ""

    region_options = ["US", "VN", "ID", "FR", "DE", "ES", "GB", "BR", "TH", "CA", "AU", "MX"]
    language_options = ["en", "vi", "es", "pt", "id", "fr", "de", "th", "ko", "ja"]
    type_options = ["all", "long", "shorts"]
    days_options = [1, 3, 7, 30, 90, 365]
    limit_options = [12, 24, 50]

    with st.form(f"market_scan_form_{config_key}"):
        top = st.columns([3, 1, 1, 1])
        with top[0]:
            query = st.text_input(
                "Từ khóa thị trường",
                value=default_query,
                placeholder="police bodycam, homeless documentary, village cooking...",
                key=f"market_query_{config_key}",
            ).strip()
        with top[1]:
            region = st.selectbox(
                "Quốc gia",
                region_options,
                index=region_options.index(default_region) if default_region in region_options else 0,
                key=f"market_region_{config_key}",
            )
        with top[2]:
            language = st.selectbox(
                "Ngôn ngữ",
                language_options,
                index=language_options.index(default_language) if default_language in language_options else 0,
                key=f"market_language_{config_key}",
            )
        with top[3]:
            video_type = st.selectbox(
                "Loại video",
                type_options,
                index=type_options.index(default_type) if default_type in type_options else 0,
                format_func=lambda value: {"all": "Tất cả", "long": "Video dài", "shorts": "Shorts"}[value],
                key=f"market_type_{config_key}",
            )

        middle = st.columns(5)
        with middle[0]:
            days = st.selectbox(
                "Khoảng thời gian",
                days_options,
                index=days_options.index(default_days) if default_days in days_options else 3,
                format_func=lambda value: f"{value} ngày",
                key=f"market_days_{config_key}",
            )
        with middle[1]:
            search_limit = st.selectbox(
                "Số kết quả",
                limit_options,
                index=limit_options.index(default_limit) if default_limit in limit_options else 1,
                key=f"market_limit_{config_key}",
            )
        with middle[2]:
            deep_limit = st.selectbox(
                "Phân tích sâu số kênh",
                [0, 5, 10, 20],
                index=2,
                key=f"market_deep_{config_key}",
                help="Lấy tối đa 50 video gần đây của các kênh mạnh nhất để tính median/outlier. Chọn 0 để tiết kiệm quota.",
            )
        with middle[3]:
            order_label = st.selectbox(
                "Ưu tiên kết quả",
                ["Lượt xem", "Mới nhất", "Liên quan"],
                key=f"market_order_{config_key}",
            )
        with middle[4]:
            force_refresh = st.checkbox(
                "Bỏ cache 30 phút",
                value=False,
                key=f"market_force_{config_key}",
            )

        lower = st.columns(2)
        with lower[0]:
            subject_value = st.text_input(
                "Chủ đề",
                value=default_subject,
                placeholder="Ví dụ: News & Society",
                key=f"market_subject_{config_key}",
            )
        with lower[1]:
            niche_value = st.text_input(
                "Ngách",
                value=default_niche,
                placeholder="Ví dụ: Police Bodycam",
                key=f"market_niche_{config_key}",
            )

        save_before_scan = st.checkbox(
            "Lưu từ khóa này vào danh sách theo dõi thị trường",
            value=selected_keyword is not None,
            disabled=selected_keyword is not None,
            key=f"market_save_before_{config_key}",
        )
        st.caption(
            f"Ước tính mỗi lần quét dùng khoảng {estimate_market_scan_units(int(deep_limit), int(search_limit))} quota units. "
            "YouTube không cung cấp lượng tìm kiếm từ khóa chính xác; tool phân tích mẫu video thu thập được."
        )
        scan_submitted = st.form_submit_button(
            "Quét toàn thị trường",
            type="primary",
            disabled=not bool(query),
            use_container_width=True,
        )

    if scan_submitted:
        keyword_id = int(selected_keyword["id"]) if selected_keyword else None
        if save_before_scan and selected_keyword is None:
            try:
                saved = store.upsert_market_keyword(
                    build_keyword_payload(
                        keyword=query,
                        subject=subject_value,
                        niche=niche_value,
                        region_code=region,
                        language_code=language,
                        video_type=video_type,
                        period_days=int(days),
                        result_limit=int(search_limit),
                    )
                )
                keyword_id = int(saved["id"])
                clear_saved_data_cache()
            except Exception as exc:
                st.error(f"Không lưu được từ khóa: {exc}")
        order_map = {"Lượt xem": "viewCount", "Mới nhất": "date", "Liên quan": "relevance"}
        execute_market_scan_ui(
            store=store,
            api=api,
            query=query,
            region_code=region,
            language_code=language,
            video_type=video_type,
            period_days=int(days),
            result_limit=int(search_limit),
            subject=subject_value,
            niche=niche_value,
            keyword_id=keyword_id,
            deep_channel_limit=int(deep_limit),
            order=order_map[order_label],
            force_refresh=bool(force_refresh),
        )

    market_results = st.session_state.get("market_results", [])
    active_scan_id = st.session_state.get("market_active_scan_id")
    if selected_keyword and st.session_state.get("market_active_keyword_id") != int(selected_keyword["id"]):
        market_results = []
    if selected_keyword and not market_results:
        scans = store.list_market_scans(keyword_id=int(selected_keyword["id"]), limit=1)
        if scans:
            active_scan_id = int(scans[0]["id"])
            market_results = store.list_market_results(scan_id=active_scan_id, limit=50)
            st.session_state["market_active_scan_id"] = active_scan_id
            st.session_state["market_active_keyword_id"] = int(selected_keyword["id"])
            st.session_state["market_results"] = market_results

    if market_results:
        scans = load_market_scans(supabase_url, supabase_key)
        active_scan = next(
            (row for row in scans if int(row.get("id", 0) or 0) == int(active_scan_id or 0)),
            None,
        )
        metrics = st.columns(5)
        metrics[0].metric("Video tìm thấy", len(market_results))
        metrics[1].metric(
            "Tổng view mẫu",
            fmt_int(sum(int(row.get("view_count", 0) or 0) for row in market_results)),
        )
        metrics[2].metric(
            "View/ngày trung bình",
            fmt_int(
                int(
                    sum(int(row.get("views_per_day", 0) or 0) for row in market_results)
                    / max(1, len(market_results))
                )
            ),
        )
        metrics[3].metric(
            "Kênh khác nhau",
            len({str(row.get("channel_id", "")) for row in market_results}),
        )
        metrics[4].metric(
            "Quota đã dùng",
            int(active_scan.get("api_units_estimated", 0) or 0) if active_scan else "—",
        )

        st.markdown("### Kết quả thị trường")
        filters = st.columns(5)
        with filters[0]:
            min_views = st.number_input(
                "View tối thiểu",
                min_value=0,
                value=0,
                step=1_000,
                key="market_results_min_views",
            )
        with filters[1]:
            max_subscribers = st.number_input(
                "Subscriber tối đa",
                min_value=0,
                value=10_000_000,
                step=10_000,
                key="market_results_max_subscribers",
            )
        with filters[2]:
            min_outlier = st.selectbox(
                "Outlier tối thiểu",
                [0.0, 1.2, 2.0, 5.0, 10.0],
                key="market_results_min_outlier",
            )
        with filters[3]:
            result_type_filter = st.selectbox(
                "Loại",
                ["Tất cả", "Video dài", "Shorts"],
                key="market_results_type",
            )
        with filters[4]:
            result_sort = st.selectbox(
                "Sắp xếp",
                ["View/ngày", "Lượt xem", "Outlier", "Mới nhất"],
                key="market_results_sort",
            )

        filtered_results = [
            row
            for row in market_results
            if int(row.get("view_count", 0) or 0) >= int(min_views)
            and int(row.get("channel_subscriber_count", 0) or 0) <= int(max_subscribers)
            and float(row.get("outlier_score", 0) or 0) >= float(min_outlier)
        ]
        if result_type_filter == "Video dài":
            filtered_results = [row for row in filtered_results if row.get("video_type") == "long"]
        elif result_type_filter == "Shorts":
            filtered_results = [row for row in filtered_results if row.get("video_type") == "shorts"]
        sort_map = {
            "View/ngày": lambda row: int(row.get("views_per_day", 0) or 0),
            "Lượt xem": lambda row: int(row.get("view_count", 0) or 0),
            "Outlier": lambda row: float(row.get("outlier_score", 0) or 0),
            "Mới nhất": lambda row: row.get("published_at") or "",
        }
        filtered_results = sorted(filtered_results, key=sort_map[result_sort], reverse=True)
        if not filtered_results:
            st.info("Không có video phù hợp với bộ lọc hiện tại.")
        else:
            items_per_page = 24
            total_pages = max(1, math.ceil(len(filtered_results) / items_per_page))
            page = st.selectbox(
                "Trang kết quả thị trường",
                list(range(1, total_pages + 1)),
                key="market_result_page",
                disabled=total_pages <= 1,
            )
            start_index = (int(page) - 1) * items_per_page
            page_rows = filtered_results[start_index : start_index + items_per_page]
            render_market_video_grid(
                page_rows,
                store=store,
                tracked_channel_ids={str(row.get("channel_id", "")) for row in channels},
                columns_count=4,
            )
    else:
        st.info(
            "Nhập từ khóa rồi bấm Quét toàn thị trường, hoặc chọn một từ khóa đã lưu để mở kết quả gần nhất."
        )
elif nav == "Kênh theo dõi":
    st.caption("Mở trang không tự quét. Chỉ các nút bên dưới mới gọi YouTube API.")

    with st.expander("Thêm nhiều kênh", expanded=not bool(channels)):
        references = st.text_area(
            "Mỗi dòng một link kênh, @handle hoặc Channel ID",
            height=140,
            placeholder="https://www.youtube.com/@channel/videos\n@anotherchannel",
            key="new_channel_references",
        )
        if st.button("Thêm và lấy dữ liệu", type="primary", key="add_channels_button"):
            if not api:
                st.error("Chưa cấu hình YOUTUBE_API_KEY trong Streamlit Secrets.")
            else:
                items = [line.strip() for line in references.splitlines() if line.strip()]
                progress = st.progress(0.0)
                status = st.empty()
                success_count = 0
                errors: list[str] = []
                for index, reference in enumerate(items, start=1):
                    try:
                        channel = sync_reference(
                            store,
                            api,
                            reference,
                            lookback_days,
                            max_pages,
                        )
                        success_count += 1
                        status.info(f"{index}/{len(items)} · {channel['title']}")
                    except Exception as exc:
                        errors.append(f"{reference}: {exc}")
                        status.warning(f"{index}/{len(items)} · Lỗi {reference}")
                    progress.progress(index / max(1, len(items)))
                clear_saved_data_cache()
                st.session_state["flash_message"] = (
                    f"Đã thêm {success_count}/{len(items)} kênh"
                    + (f", có {len(errors)} lỗi." if errors else ".")
                )
                if errors:
                    st.session_state["flash_errors"] = errors
                st.rerun()

    search_text = st.text_input(
        "Tìm kênh",
        placeholder="Tên kênh, chủ đề hoặc ngách",
        key="channel_search",
    ).strip().lower()
    subjects = ["Tất cả"] + sorted(
        {str(channel.get("auto_subject")) for channel in channels if channel.get("auto_subject")}
    )
    niches = ["Tất cả"] + sorted(
        {str(channel.get("auto_niche")) for channel in channels if channel.get("auto_niche")}
    )
    filter_columns = st.columns(3)
    with filter_columns[0]:
        selected_subject = st.selectbox("Chủ đề", subjects, key="channel_subject")
    with filter_columns[1]:
        selected_niche = st.selectbox("Ngách", niches, key="channel_niche")
    with filter_columns[2]:
        stale_days = st.selectbox(
            "Kênh chưa cập nhật quá",
            [1, 3, 7, 14, 30],
            index=2,
            key="channel_stale_days",
        )

    filtered_channels = []
    for channel in channels:
        haystack = " ".join(
            [
                str(channel.get("title", "")),
                str(channel.get("auto_subject", "")),
                str(channel.get("auto_niche", "")),
            ]
        ).lower()
        if search_text and search_text not in haystack:
            continue
        if selected_subject != "Tất cả" and channel.get("auto_subject") != selected_subject:
            continue
        if selected_niche != "Tất cả" and channel.get("auto_niche") != selected_niche:
            continue
        filtered_channels.append(channel)

    title_by_id = {
        str(channel.get("channel_id")): str(channel.get("title") or channel.get("channel_id"))
        for channel in filtered_channels
    }
    selected_ids = st.multiselect(
        "Chọn kênh để thao tác",
        options=list(title_by_id),
        format_func=lambda channel_id: title_by_id.get(channel_id, channel_id),
        key="selected_channel_ids",
    )
    selected_rows = [
        channel for channel in filtered_channels if str(channel.get("channel_id")) in selected_ids
    ]

    actions = st.columns(4)
    with actions[0]:
        if st.button(
            "Quét kênh được chọn",
            disabled=not bool(selected_rows),
            use_container_width=True,
            key="scan_selected_channels",
        ):
            scan_channels_ui(
                store,
                api,
                selected_rows,
                lookback_days,
                max_pages,
                "Quét kênh được chọn",
            )
    with actions[1]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(stale_days))
        stale_channels = [
            channel
            for channel in channels
            if (parse_dt(channel.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc))
            < cutoff
        ]
        if st.button(
            f"Quét kênh quá hạn ({len(stale_channels)})",
            disabled=not bool(stale_channels),
            use_container_width=True,
            key="scan_stale_channels",
        ):
            scan_channels_ui(
                store,
                api,
                stale_channels,
                lookback_days,
                max_pages,
                "Quét kênh chưa cập nhật",
            )
    with actions[2]:
        confirm_all = st.checkbox("Xác nhận quét tất cả", key="confirm_scan_all_channels")
        if st.button(
            f"Quét tất cả ({len(channels)})",
            disabled=not confirm_all or not channels,
            use_container_width=True,
            key="scan_all_channels",
        ):
            scan_channels_ui(
                store,
                api,
                channels,
                lookback_days,
                max_pages,
                "Quét tất cả",
            )
    with actions[3]:
        confirm_delete = st.checkbox("Xác nhận xóa", key="confirm_delete_channels")
        if st.button(
            "Xóa kênh được chọn",
            disabled=not confirm_delete or not selected_rows,
            use_container_width=True,
            key="delete_selected_channels",
        ):
            errors: list[str] = []
            for channel in selected_rows:
                try:
                    store.delete_channel(str(channel["channel_id"]))
                except Exception as exc:
                    errors.append(f"{channel.get('title')}: {exc}")
            clear_saved_data_cache()
            if errors:
                st.error("Một số kênh không xóa được: " + " | ".join(errors))
            else:
                st.session_state["flash_message"] = f"Đã xóa {len(selected_rows)} kênh."
                st.rerun()

    if filtered_channels:
        rows = [
            {
                "Kênh": channel.get("title"),
                "Chủ đề": channel.get("auto_subject"),
                "Ngách": channel.get("auto_niche"),
                "Quốc gia": channel.get("country"),
                "Subscriber": channel.get("subscriber_count"),
                "Tổng view": channel.get("total_view_count"),
                "Video": channel.get("video_count"),
                "View video 30 ngày": channel.get("views_of_videos_published_30d"),
                "Tần suất/tuần": channel.get("frequency_per_week"),
                "Video mới nhất": channel.get("last_video_title"),
                "Ngày đăng gần nhất": channel.get("last_video_published_at"),
                "Cập nhật": channel.get("updated_at"),
                "Link": channel.get("canonical_url"),
            }
            for channel in filtered_channels
        ]
        dataframe = pd.DataFrame(rows)
        st.dataframe(
            dataframe,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Link": st.column_config.LinkColumn("Link"),
                "Subscriber": st.column_config.NumberColumn(format="%d"),
                "Tổng view": st.column_config.NumberColumn(format="%d"),
                "View video 30 ngày": st.column_config.NumberColumn(format="%d"),
            },
        )
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            dataframe.to_excel(writer, index=False, sheet_name="Kenh")
        st.download_button(
            "Xuất Excel",
            output.getvalue(),
            "youtube_channels.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="export_channels_excel",
        )
    else:
        st.info("Không có kênh phù hợp với bộ lọc.")

elif nav == "Shorts":
    st.caption(
        "Gộp Shorts từ kênh theo dõi và kết quả toàn thị trường. Video được nhận diện gần đúng bằng thời lượng tối đa 180 giây."
    )
    tracked_contextual = attach_channel_context(videos, channels)
    tracked_scored = add_outlier_scores(tracked_contextual)
    market_rows: list[dict[str, Any]] = []
    try:
        if market_schema_ready(supabase_url, supabase_key):
            market_rows = load_market_results(supabase_url, supabase_key)
    except Exception as exc:
        st.warning(f"Không đọc được Shorts toàn thị trường: {exc}")
    combined = combine_video_sources(tracked_scored, market_rows)
    scored = [video for video in combined if is_short(video)]

    controls = st.columns(6)
    with controls[0]:
        period = st.selectbox(
            "Thời gian",
            ["24 giờ", "3 ngày", "7 ngày", "30 ngày", "Tất cả"],
            index=3,
            key="shorts_period",
        )
    with controls[1]:
        source_filter = st.selectbox(
            "Nguồn",
            ["Tất cả", "Kênh theo dõi", "Toàn thị trường"],
            key="shorts_source",
        )
    with controls[2]:
        minimum_views = st.number_input(
            "View tối thiểu",
            min_value=0,
            value=0,
            step=1_000,
            key="shorts_min_views",
        )
    with controls[3]:
        maximum_subscribers = st.number_input(
            "Subscriber tối đa",
            min_value=0,
            value=10_000_000,
            step=10_000,
            key="shorts_max_subscribers",
        )
    with controls[4]:
        minimum_outlier = st.selectbox(
            "Outlier tối thiểu",
            [0.0, 1.2, 2.0, 5.0, 10.0],
            index=0,
            key="shorts_min_outlier",
        )
    with controls[5]:
        result_limit = st.selectbox(
            "Số lượng",
            [20, 50, 100, 200],
            index=1,
            key="shorts_result_limit",
        )

    filtered = filter_by_period(scored, period)
    if source_filter == "Kênh theo dõi":
        filtered = [row for row in filtered if row.get("source") in {"Kênh theo dõi", "Cả hai"}]
    elif source_filter == "Toàn thị trường":
        filtered = [row for row in filtered if row.get("source") in {"Toàn thị trường", "Cả hai"}]
    filtered = [
        video
        for video in filtered
        if int(video.get("view_count") or 0) >= int(minimum_views)
        and int(video.get("subscriber_count") or 0) <= int(maximum_subscribers)
        and float(video.get("outlier_score") or 0) >= float(minimum_outlier)
    ]
    filtered = sorted(
        filtered,
        key=lambda row: (
            float(row.get("outlier_score") or 0),
            int(row.get("views_per_day") or 0),
        ),
        reverse=True,
    )
    show_paged_videos(
        filtered,
        result_limit=int(result_limit),
        page_key="shorts_page",
        columns_count=5,
        items_per_page=25,
    )
elif nav == "Kênh mới nổi":
    st.caption(
        "Gộp kênh đang theo dõi với các kênh mới được phát hiện từ toàn thị trường. "
        "Kênh thị trường được xếp hạng bằng view/ngày, view/subscriber và outlier nếu đã phân tích sâu."
    )
    try:
        snapshots = load_saved_snapshots(supabase_url, supabase_key)
    except Exception as exc:
        snapshots = []
        st.warning(f"Không tải được snapshot: {exc}")

    contextual = attach_channel_context(videos, channels)
    scored = add_outlier_scores(contextual)
    outlier_counts: dict[str, int] = {}
    for video in scored:
        if float(video.get("outlier_score") or 0) >= 2:
            channel_id = str(video.get("channel_id", ""))
            outlier_counts[channel_id] = outlier_counts.get(channel_id, 0) + 1
    growth7 = bulk_growth_by_channel(channels, snapshots, 7) if snapshots else {}
    growth30 = bulk_growth_by_channel(channels, snapshots, 30) if snapshots else {}

    market_rows: list[dict[str, Any]] = []
    try:
        if market_schema_ready(supabase_url, supabase_key):
            market_rows = load_market_results(supabase_url, supabase_key)
    except Exception as exc:
        st.warning(f"Không đọc được kênh toàn thị trường: {exc}")
    market_channels = aggregate_market_channels(market_rows)
    market_by_id = {str(row.get("channel_id", "")): row for row in market_channels}

    filters = st.columns(3)
    with filters[0]:
        source_filter = st.selectbox(
            "Nguồn",
            ["Tất cả", "Kênh theo dõi", "Toàn thị trường"],
            key="emerging_source",
        )
    with filters[1]:
        max_subscribers = st.number_input(
            "Subscriber tối đa",
            min_value=0,
            value=500_000,
            step=10_000,
            key="emerging_max_subscribers",
        )
    with filters[2]:
        minimum_daily_views = st.number_input(
            "View/ngày tối thiểu",
            min_value=0,
            value=0,
            step=1_000,
            key="emerging_min_daily_views",
        )

    merged: dict[str, dict[str, Any]] = {}
    for channel in channels:
        channel_id = str(channel.get("channel_id", ""))
        subscribers = int(channel.get("subscriber_count", 0) or 0)
        merged[channel_id] = {
            "channel_id": channel_id,
            "Nguồn": "Kênh theo dõi",
            "Kênh": channel.get("title"),
            "Subscriber": subscribers,
            "View tăng 7 ngày": growth7.get(channel_id),
            "View tăng 30 ngày": growth30.get(channel_id),
            "Video outlier ≥2x": outlier_counts.get(channel_id, 0),
            "View/ngày mạnh nhất": 0,
            "View/Subscriber": 0.0,
            "Tần suất/tuần": channel.get("frequency_per_week"),
            "View video 30 ngày": channel.get("views_of_videos_published_30d"),
            "Chủ đề": channel.get("auto_subject"),
            "Ngách": channel.get("auto_niche"),
            "Quốc gia": channel.get("country"),
            "Từ khóa phát hiện": "",
            "Video mạnh nhất": channel.get("last_video_title"),
            "Phát hiện/Cập nhật": channel.get("updated_at"),
            "Link": channel.get("canonical_url"),
            "_market_result": None,
        }

    for market_channel in market_channels:
        channel_id = str(market_channel.get("channel_id", ""))
        if channel_id in merged:
            row = merged[channel_id]
            row["Nguồn"] = "Cả hai"
            row["View/ngày mạnh nhất"] = market_channel.get("View/ngày mạnh nhất")
            row["View/Subscriber"] = market_channel.get("View/Subscriber")
            row["Từ khóa phát hiện"] = market_channel.get("Từ khóa phát hiện")
            row["_market_result"] = market_channel.get("_result")
            if not row.get("Chủ đề"):
                row["Chủ đề"] = market_channel.get("Chủ đề")
            if not row.get("Ngách"):
                row["Ngách"] = market_channel.get("Ngách")
        else:
            merged[channel_id] = {
                "channel_id": channel_id,
                "Nguồn": "Toàn thị trường",
                "Kênh": market_channel.get("Kênh"),
                "Subscriber": market_channel.get("Subscriber"),
                "View tăng 7 ngày": None,
                "View tăng 30 ngày": None,
                "Video outlier ≥2x": 1 if float(market_channel.get("Outlier cao nhất", 0) or 0) >= 2 else 0,
                "View/ngày mạnh nhất": market_channel.get("View/ngày mạnh nhất"),
                "View/Subscriber": market_channel.get("View/Subscriber"),
                "Tần suất/tuần": None,
                "View video 30 ngày": None,
                "Chủ đề": market_channel.get("Chủ đề"),
                "Ngách": market_channel.get("Ngách"),
                "Quốc gia": market_channel.get("Quốc gia"),
                "Từ khóa phát hiện": market_channel.get("Từ khóa phát hiện"),
                "Video mạnh nhất": market_channel.get("Video mạnh nhất"),
                "Phát hiện/Cập nhật": market_channel.get("Phát hiện gần nhất"),
                "Link": market_channel.get("Link"),
                "_market_result": market_channel.get("_result"),
            }

    emerging_rows = []
    for row in merged.values():
        subscribers = int(row.get("Subscriber", 0) or 0)
        daily_views = int(row.get("View/ngày mạnh nhất", 0) or 0)
        if subscribers > int(max_subscribers) or daily_views < int(minimum_daily_views):
            continue
        if source_filter == "Kênh theo dõi" and row.get("Nguồn") not in {"Kênh theo dõi", "Cả hai"}:
            continue
        if source_filter == "Toàn thị trường" and row.get("Nguồn") not in {"Toàn thị trường", "Cả hai"}:
            continue
        emerging_rows.append(row)

    emerging_rows.sort(
        key=lambda row: (
            int(row.get("Video outlier ≥2x") or 0),
            float(row.get("View/Subscriber") or 0),
            int(row.get("View/ngày mạnh nhất") or 0),
            int(row.get("View tăng 30 ngày") or 0),
        ),
        reverse=True,
    )

    if emerging_rows:
        display_rows = [
            {key: value for key, value in row.items() if not key.startswith("_") and key != "channel_id"}
            for row in emerging_rows
        ]
        st.dataframe(
            pd.DataFrame(display_rows),
            use_container_width=True,
            hide_index=True,
            column_config={"Link": st.column_config.LinkColumn("Link")},
        )

        trackable = [
            row for row in emerging_rows
            if row.get("Nguồn") == "Toàn thị trường" and row.get("_market_result")
        ]
        if trackable:
            st.markdown("### Thêm kênh thị trường vào danh sách theo dõi")
            track_by_id = {str(row["channel_id"]): row for row in trackable}
            selected_channel_id = st.selectbox(
                "Chọn kênh",
                options=list(track_by_id),
                format_func=lambda channel_id: (
                    f"{track_by_id[channel_id].get('Kênh')} · "
                    f"{fmt_int(track_by_id[channel_id].get('Subscriber'))} subs"
                ),
                key="emerging_track_channel",
            )
            if st.button(
                "Thêm vào Kênh theo dõi",
                type="primary",
                key="emerging_track_button",
            ):
                try:
                    result = track_by_id[selected_channel_id]["_market_result"]
                    store.upsert_channel(market_result_to_tracked_channel(result))
                    clear_saved_data_cache()
                    st.session_state["flash_message"] = "Đã thêm kênh vào danh sách theo dõi."
                    st.rerun()
                except Exception as exc:
                    st.error(f"Không thêm được kênh: {exc}")
    else:
        st.info("Chưa có kênh phù hợp với bộ lọc.")
elif nav == "Từ khóa tăng trong tuần":
    st.caption(
        "Mức tăng được tính từ các mẫu video mà tool đã lưu qua nhiều lần quét: số video, tổng view, "
        "view/ngày và số kênh tham gia. Đây không phải lượng tìm kiếm chính xác do YouTube cung cấp."
    )
    if not market_tables_or_notice(supabase_url, supabase_key):
        st.stop()

    market_keywords, market_scans, market_results = load_market_bundle(
        supabase_url, supabase_key
    )
    controls = st.columns(4)
    with controls[0]:
        window_label = st.selectbox(
            "Khoảng so sánh",
            ["24 giờ", "3 ngày", "7 ngày", "30 ngày"],
            index=2,
            key="keyword_growth_window",
        )
    window_days = {"24 giờ": 1, "3 ngày": 3, "7 ngày": 7, "30 ngày": 30}[window_label]
    regions = ["Tất cả"] + sorted(
        {str(row.get("region_code", "")) for row in market_keywords if row.get("region_code")}
    )
    languages = ["Tất cả"] + sorted(
        {str(row.get("language_code", "")) for row in market_keywords if row.get("language_code")}
    )
    subjects = ["Tất cả"] + sorted(
        {str(row.get("subject", "")) for row in market_keywords if row.get("subject")}
    )
    with controls[1]:
        region_filter = st.selectbox("Quốc gia", regions, key="keyword_growth_region")
    with controls[2]:
        language_filter = st.selectbox("Ngôn ngữ", languages, key="keyword_growth_language")
    with controls[3]:
        subject_filter = st.selectbox("Chủ đề", subjects, key="keyword_growth_subject")

    growth_rows = keyword_growth_rows(
        market_keywords,
        market_scans,
        market_results,
        window_days=window_days,
    )
    growth_rows = [
        row
        for row in growth_rows
        if (region_filter == "Tất cả" or row.get("Quốc gia") == region_filter)
        and (language_filter == "Tất cả" or row.get("Ngôn ngữ") == language_filter)
        and (subject_filter == "Tất cả" or row.get("Chủ đề") == subject_filter)
    ]

    if not growth_rows:
        st.info(
            "Chưa đủ lịch sử để so sánh. Mỗi từ khóa cần ít nhất 2 lần quét vào các thời điểm khác nhau. "
            "Hãy vào Từ khóa đã lưu và quét lại sau 24 giờ, 3 ngày hoặc 7 ngày."
        )
    else:
        metrics = st.columns(4)
        metrics[0].metric("Từ khóa đủ dữ liệu", len(growth_rows))
        metrics[1].metric(
            "Từ khóa đang tăng",
            sum(1 for row in growth_rows if float(row.get("Mức tăng", 0) or 0) > 0),
        )
        metrics[2].metric(
            "Mức tăng cao nhất",
            f"{float(growth_rows[0].get('Mức tăng', 0) or 0) * 100:.1f}%",
        )
        metrics[3].metric("Cửa sổ", window_label)

        display_rows = []
        for row in growth_rows:
            display = {key: value for key, value in row.items() if key != "keyword_id"}
            for key in [
                "Mức tăng",
                "Thay đổi video",
                "Thay đổi view",
                "Thay đổi view/ngày",
                "Thay đổi số kênh",
            ]:
                display[key] = round(float(display.get(key, 0) or 0) * 100, 1)
            display_rows.append(display)
        st.dataframe(
            pd.DataFrame(display_rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Mức tăng": st.column_config.NumberColumn(format="%.1f%%"),
                "Thay đổi video": st.column_config.NumberColumn(format="%.1f%%"),
                "Thay đổi view": st.column_config.NumberColumn(format="%.1f%%"),
                "Thay đổi view/ngày": st.column_config.NumberColumn(format="%.1f%%"),
                "Thay đổi số kênh": st.column_config.NumberColumn(format="%.1f%%"),
                "Quét gần nhất": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                "Mốc so sánh": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
            },
        )

        open_by_id = {int(row["keyword_id"]): row for row in growth_rows}
        selected_growth_id = st.selectbox(
            "Mở kết quả của từ khóa",
            options=list(open_by_id),
            format_func=lambda keyword_id: str(open_by_id[keyword_id].get("Từ khóa", "")),
            key="keyword_growth_open_id",
        )
        if st.button("Mở trong Toàn thị trường", key="keyword_growth_open_button"):
            st.session_state["market_open_keyword_id"] = int(selected_growth_id)
            st.session_state["market_results"] = []
            st.session_state["main_navigation"] = "Toàn thị trường"
            st.rerun()
elif nav == "Từ khóa đã lưu":
    st.caption(
        "Quản lý 5–20 từ khóa thị trường. Web không tự quét khi mở trang; chu kỳ chỉ là thông tin chuẩn bị cho lịch chạy ngoài app."
    )
    if not market_tables_or_notice(supabase_url, supabase_key):
        st.stop()

    market_keywords = load_market_keywords(supabase_url, supabase_key)
    active_count = sum(1 for row in market_keywords if bool(row.get("is_active")))

    with st.expander("Thêm từ khóa thị trường", expanded=not bool(market_keywords)):
        with st.form("add_market_keyword_form"):
            row1 = st.columns([3, 1, 1, 1])
            with row1[0]:
                new_keyword = st.text_input(
                    "Từ khóa",
                    placeholder="natural disasters caught on camera",
                    key="saved_new_keyword",
                ).strip()
            with row1[1]:
                new_region = st.selectbox(
                    "Quốc gia",
                    ["US", "VN", "ID", "FR", "DE", "ES", "GB", "BR", "TH", "CA", "AU", "MX"],
                    key="saved_new_region",
                )
            with row1[2]:
                new_language = st.selectbox(
                    "Ngôn ngữ",
                    ["en", "vi", "es", "pt", "id", "fr", "de", "th", "ko", "ja"],
                    key="saved_new_language",
                )
            with row1[3]:
                new_type = st.selectbox(
                    "Loại video",
                    ["all", "long", "shorts"],
                    format_func=lambda value: {"all": "Tất cả", "long": "Video dài", "shorts": "Shorts"}[value],
                    key="saved_new_type",
                )
            row2 = st.columns(5)
            with row2[0]:
                new_subject = st.text_input("Chủ đề", key="saved_new_subject")
            with row2[1]:
                new_niche = st.text_input("Ngách", key="saved_new_niche")
            with row2[2]:
                new_days = st.selectbox(
                    "Khoảng quét",
                    [1, 3, 7, 30, 90, 365],
                    index=3,
                    format_func=lambda value: f"{value} ngày",
                    key="saved_new_days",
                )
            with row2[3]:
                new_limit = st.selectbox(
                    "Số kết quả",
                    [12, 24, 50],
                    index=1,
                    key="saved_new_limit",
                )
            with row2[4]:
                new_cycle = st.selectbox(
                    "Chu kỳ dự kiến",
                    ["manual", "daily", "every_3_days", "weekly"],
                    format_func=lambda value: {
                        "manual": "Thủ công",
                        "daily": "Mỗi ngày",
                        "every_3_days": "Mỗi 3 ngày",
                        "weekly": "Mỗi tuần",
                    }[value],
                    key="saved_new_cycle",
                )
            add_submitted = st.form_submit_button(
                "Lưu từ khóa",
                type="primary",
                disabled=not bool(new_keyword) or active_count >= 20,
            )
        if active_count >= 20:
            st.warning("Đã có 20 từ khóa hoạt động. Hãy tạm dừng hoặc xóa một từ khóa trước khi thêm.")
        if add_submitted:
            try:
                store.upsert_market_keyword(
                    build_keyword_payload(
                        keyword=new_keyword,
                        subject=new_subject,
                        niche=new_niche,
                        region_code=new_region,
                        language_code=new_language,
                        video_type=new_type,
                        period_days=int(new_days),
                        result_limit=int(new_limit),
                        scan_cycle=new_cycle,
                    )
                )
                clear_saved_data_cache()
                st.session_state["flash_message"] = f"Đã lưu từ khóa: {new_keyword}"
                st.rerun()
            except Exception as exc:
                st.error(f"Không lưu được từ khóa: {exc}")

    market_keywords = load_market_keywords(supabase_url, supabase_key)
    if not market_keywords:
        st.info("Chưa có từ khóa thị trường nào.")
    else:
        metrics = st.columns(4)
        metrics[0].metric("Tổng từ khóa", len(market_keywords))
        metrics[1].metric("Đang hoạt động", sum(1 for row in market_keywords if row.get("is_active")))
        metrics[2].metric("Đang tạm dừng", sum(1 for row in market_keywords if not row.get("is_active")))
        metrics[3].metric(
            "Đã từng quét",
            sum(1 for row in market_keywords if row.get("last_scanned_at")),
        )

        display_rows = [
            {
                "Từ khóa": row.get("keyword"),
                "Chủ đề": row.get("subject"),
                "Ngách": row.get("niche"),
                "Quốc gia": row.get("region_code"),
                "Ngôn ngữ": row.get("language_code"),
                "Loại": row.get("video_type"),
                "Khoảng quét": f"{row.get('period_days')} ngày",
                "Số kết quả": row.get("result_limit"),
                "Chu kỳ": row.get("scan_cycle"),
                "Trạng thái": "Hoạt động" if row.get("is_active") else "Tạm dừng",
                "Quét gần nhất": row.get("last_scanned_at"),
                "Kết quả gần nhất": row.get("last_result_count"),
            }
            for row in market_keywords
        ]
        st.dataframe(
            pd.DataFrame(display_rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Quét gần nhất": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")
            },
        )

        keyword_by_id = {int(row["id"]): row for row in market_keywords}
        selected_keyword_id = st.selectbox(
            "Chọn từ khóa để thao tác",
            options=list(keyword_by_id),
            format_func=lambda keyword_id: (
                f"{keyword_by_id[keyword_id].get('keyword')} · "
                f"{keyword_by_id[keyword_id].get('region_code')}"
            ),
            key="saved_keyword_action_id",
        )
        selected_keyword = keyword_by_id[int(selected_keyword_id)]
        actions = st.columns(4)
        with actions[0]:
            if st.button(
                "Quét ngay",
                type="primary",
                use_container_width=True,
                disabled=not bool(selected_keyword.get("is_active")),
                key="saved_keyword_scan_now",
            ):
                outcome = execute_market_scan_ui(
                    store=store,
                    api=api,
                    query=str(selected_keyword.get("keyword", "")),
                    region_code=str(selected_keyword.get("region_code", "US")),
                    language_code=str(selected_keyword.get("language_code", "en")),
                    video_type=str(selected_keyword.get("video_type", "all")),
                    period_days=int(selected_keyword.get("period_days", 30) or 30),
                    result_limit=int(selected_keyword.get("result_limit", 24) or 24),
                    subject=str(selected_keyword.get("subject", "")),
                    niche=str(selected_keyword.get("niche", "")),
                    keyword_id=int(selected_keyword["id"]),
                    deep_channel_limit=10,
                    order="viewCount",
                    force_refresh=False,
                )
                if outcome:
                    st.session_state["market_open_keyword_id"] = int(selected_keyword["id"])
        with actions[1]:
            if st.button(
                "Mở kết quả",
                use_container_width=True,
                key="saved_keyword_open_results",
            ):
                st.session_state["market_open_keyword_id"] = int(selected_keyword["id"])
                st.session_state["market_results"] = []
                st.session_state["main_navigation"] = "Toàn thị trường"
                st.rerun()
        with actions[2]:
            toggle_label = "Tạm dừng" if selected_keyword.get("is_active") else "Kích hoạt"
            if st.button(
                toggle_label,
                use_container_width=True,
                key="saved_keyword_toggle",
            ):
                try:
                    store.update_market_keyword(
                        int(selected_keyword["id"]),
                        {
                            "is_active": not bool(selected_keyword.get("is_active")),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    clear_saved_data_cache()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Không cập nhật được trạng thái: {exc}")
        with actions[3]:
            confirm_delete_keyword = st.checkbox(
                "Xác nhận xóa",
                key="saved_keyword_confirm_delete",
            )
            if st.button(
                "Xóa từ khóa",
                use_container_width=True,
                disabled=not confirm_delete_keyword,
                key="saved_keyword_delete",
            ):
                try:
                    store.delete_market_keyword(int(selected_keyword["id"]))
                    clear_saved_data_cache()
                    st.session_state["flash_message"] = "Đã xóa từ khóa và lịch sử quét liên quan."
                    st.rerun()
                except Exception as exc:
                    st.error(f"Không xóa được từ khóa: {exc}")

        active_rows = [row for row in market_keywords if bool(row.get("is_active"))]
        if active_rows:
            with st.expander("Quét nhiều từ khóa thủ công", expanded=False):
                active_by_id = {int(row["id"]): row for row in active_rows}
                batch_ids = st.multiselect(
                    "Chọn từ khóa",
                    options=list(active_by_id),
                    format_func=lambda keyword_id: str(active_by_id[keyword_id].get("keyword", "")),
                    key="saved_keyword_batch_ids",
                )
                estimated_units = sum(
                    estimate_market_scan_units(10, int(active_by_id[keyword_id].get("result_limit", 24) or 24))
                    for keyword_id in batch_ids
                )
                st.caption(
                    f"Ước tính tổng quota: {estimated_units} units. Các từ khóa có cache dưới 30 phút sẽ không gọi lại API."
                )
                confirm_batch = st.checkbox(
                    "Tôi xác nhận quét các từ khóa đã chọn",
                    key="saved_keyword_batch_confirm",
                )
                if st.button(
                    "Bắt đầu quét theo lô",
                    type="primary",
                    disabled=not batch_ids or not confirm_batch,
                    key="saved_keyword_batch_scan",
                ):
                    if not api:
                        st.error("Chưa cấu hình YOUTUBE_API_KEY.")
                    else:
                        progress = st.progress(0.0)
                        status = st.empty()
                        errors: list[str] = []
                        successes = 0
                        for index, keyword_id in enumerate(batch_ids, start=1):
                            row = active_by_id[int(keyword_id)]
                            status.info(f"{index}/{len(batch_ids)} · {row.get('keyword')}")
                            try:
                                run_market_scan(
                                    store,
                                    api,
                                    query=str(row.get("keyword", "")),
                                    region_code=str(row.get("region_code", "US")),
                                    language_code=str(row.get("language_code", "en")),
                                    video_type=str(row.get("video_type", "all")),
                                    period_days=int(row.get("period_days", 30) or 30),
                                    result_limit=int(row.get("result_limit", 24) or 24),
                                    subject=str(row.get("subject", "")),
                                    niche=str(row.get("niche", "")),
                                    keyword_id=int(row["id"]),
                                    deep_channel_limit=10,
                                    order="viewCount",
                                    force_refresh=False,
                                )
                                successes += 1
                            except Exception as exc:
                                errors.append(f"{row.get('keyword')}: {exc}")
                            progress.progress(index / max(1, len(batch_ids)))
                        clear_saved_data_cache()
                        st.success(f"Đã hoàn thành {successes}/{len(batch_ids)} từ khóa.")
                        if errors:
                            with st.expander(f"Xem {len(errors)} lỗi"):
                                for error in errors:
                                    st.write(error)
elif nav == "Cài đặt":
    st.caption("Không hiển thị hoặc cho phép sao chép API key thật trên giao diện.")
    try:
        market_ready = market_schema_ready(supabase_url, supabase_key)
    except Exception:
        market_ready = False
    configuration = st.columns(4)
    configuration[0].metric("Supabase", "Đã cấu hình" if supabase_url and supabase_key else "Thiếu")
    configuration[1].metric("YouTube API", "Đã cấu hình" if api else "Thiếu")
    configuration[2].metric("Tool theo dõi kênh", "Hoạt động")
    configuration[3].metric("Tool toàn thị trường", "Hoạt động" if market_ready else "Thiếu migration")

    st.markdown("### Thiết lập quét kênh theo dõi")
    st.write(f"Số ngày quét: **{lookback_days}**")
    st.write(f"Số trang mỗi kênh: **{max_pages}**")
    st.write("Số video chuẩn tính median: **20**")
    st.write("Số kết quả mỗi trang Video vượt trội: **24**")
    st.write(f"Giới hạn đọc video đã lưu cho dashboard: **{MAX_SAVED_VIDEOS:,}**")

    st.markdown("### Thiết lập nghiên cứu toàn thị trường")
    if market_ready:
        try:
            keywords = load_market_keywords(supabase_url, supabase_key)
            scans = load_market_scans(supabase_url, supabase_key)
            results = load_market_results(supabase_url, supabase_key)
            market_metrics = st.columns(4)
            market_metrics[0].metric("Từ khóa đã lưu", len(keywords))
            market_metrics[1].metric("Lịch sử quét", len(scans))
            market_metrics[2].metric("Dòng kết quả thị trường", len(results))
            market_metrics[3].metric(
                "Quota lần quét gần nhất",
                int(scans[0].get("api_units_estimated", 0) or 0) if scans else "—",
            )
        except Exception as exc:
            st.warning(f"Không tải được thống kê thị trường: {exc}")
        st.info(
            "Quét thị trường dùng cache Supabase 30 phút. Mặc định phân tích sâu 10 kênh, "
            f"ước tính khoảng {estimate_market_scan_units(10, 24)} quota units cho một từ khóa."
        )
    else:
        st.warning(
            "Chạy file `supabase_market_migration.sql` trong Supabase SQL Editor để kích hoạt lưu từ khóa, lịch sử quét và kết quả thị trường."
        )

    tests = st.columns(3)
    with tests[0]:
        if st.button("Kiểm tra Supabase", use_container_width=True, key="test_supabase"):
            try:
                store.ping()
                st.success("Kết nối Supabase hoạt động.")
            except Exception as exc:
                st.error(f"Supabase lỗi: {exc}")
    with tests[1]:
        if st.button(
            "Kiểm tra YouTube API",
            use_container_width=True,
            disabled=api is None,
            key="test_youtube_api",
        ):
            try:
                assert api is not None
                api.test_connection()
                st.success("YouTube API hoạt động.")
            except Exception as exc:
                st.error(f"YouTube API lỗi: {exc}")
    with tests[2]:
        if st.button(
            "Kiểm tra bảng thị trường",
            use_container_width=True,
            key="test_market_schema",
        ):
            try:
                if store.market_schema_ready():
                    st.success("Ba bảng thị trường đã sẵn sàng.")
                else:
                    st.warning("Chưa chạy migration thị trường.")
            except Exception as exc:
                st.error(f"Kiểm tra bảng thị trường lỗi: {exc}")

    if st.button("Xóa cache dữ liệu", key="clear_data_cache"):
        clear_saved_data_cache()
        st.session_state.pop("market_results", None)
        st.session_state.pop("market_active_scan_id", None)
        st.session_state.pop("market_active_keyword_id", None)
        st.success("Đã xóa cache. Dữ liệu sẽ được đọc lại ở lần rerun tiếp theo.")
