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
    meta.append(f'{fmt_int(video.get("view_count"))} views')
    if video.get("views_per_day"):
        meta.append(f'{fmt_int(video.get("views_per_day"))}/ngày')
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
        f'<div class="video-title">{title}</div>'
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


def clear_saved_data_cache() -> None:
    load_saved_channels.clear()
    load_saved_videos.clear()
    load_saved_snapshots.clear()


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
    st.caption("Dashboard nghiên cứu thị trường YouTube")
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
    st.caption("Trang này chỉ đọc dữ liệu đã lưu. YouTube API chỉ chạy khi bấm nút quét.")
    try:
        snapshots = load_saved_snapshots(supabase_url, supabase_key)
    except Exception as exc:
        snapshots = []
        st.warning(f"Không tải được snapshot tăng trưởng: {exc}")

    contextual = attach_channel_context(videos, channels)
    scored = add_outlier_scores(contextual)
    growth7 = bulk_growth_by_channel(channels, snapshots, 7) if snapshots else {}
    growth_values = [value for value in growth7.values() if value is not None]

    now = datetime.now(timezone.utc)
    outlier_24h = sum(
        1
        for video in scored
        if float(video.get("outlier_score") or 0) >= 2
        and (parse_dt(video.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc))
        >= now - timedelta(hours=24)
    )
    outlier_7d = sum(
        1
        for video in scored
        if float(video.get("outlier_score") or 0) >= 2
        and (parse_dt(video.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc))
        >= now - timedelta(days=7)
    )
    outlier_30d = sum(
        1
        for video in scored
        if float(video.get("outlier_score") or 0) >= 2
        and (parse_dt(video.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc))
        >= now - timedelta(days=30)
    )

    kpi_columns = st.columns(6)
    kpis = [
        ("Kênh theo dõi", len(channels)),
        ("Video đã tải", len(videos)),
        ("Outlier 24 giờ", outlier_24h),
        ("Outlier 7 ngày", outlier_7d),
        ("Outlier 30 ngày", outlier_30d),
        ("View tăng 7 ngày", sum(growth_values) if growth_values else None),
    ]
    for column, (label, value) in zip(kpi_columns, kpis):
        with column:
            display = fmt_int(value) if value is not None else "—"
            st.markdown(
                f'<div class="kpi"><div class="kpi-label">{label}</div>'
                f'<div class="kpi-value">{display}</div></div>',
                unsafe_allow_html=True,
            )

    left, right = st.columns([3, 1])
    with left:
        st.caption(f"Dữ liệu cập nhật gần nhất: {latest_timestamp(channels, videos)}")
    with right:
        st.button(
            "Mở Video vượt trội",
            use_container_width=True,
            on_click=lambda: st.session_state.update(
                {"main_navigation": "Video vượt trội"}
            ),
        )

    with st.expander("Quét dữ liệu mới", expanded=False):
        st.warning(
            f"Thao tác này sẽ gọi YouTube API cho {len(channels)} kênh. App không tự chạy thao tác này khi mở trang."
        )
        confirm_scan = st.checkbox(
            "Tôi xác nhận quét toàn bộ kênh",
            key="overview_confirm_full_scan",
        )
        if st.button(
            "Quét dữ liệu mới",
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
                "Quét dữ liệu mới",
            )

    st.markdown("### Video vượt trội nổi bật")
    top_preview = sorted(
        [video for video in scored if float(video.get("outlier_score") or 0) >= 1.2],
        key=lambda row: (
            float(row.get("outlier_score") or 0),
            int(row.get("views_per_day") or 0),
        ),
        reverse=True,
    )[:8]
    if top_preview:
        render_video_grid(top_preview, columns_count=4)
    else:
        st.info("Chưa có video đạt ngưỡng 1.2× trong dữ liệu đã lưu.")

elif nav == "Video vượt trội":
    st.caption(
        "Outlier được tính theo median tối đa 20 video cũ hơn của chính kênh, không so sánh chéo giữa các kênh."
    )
    contextual = attach_channel_context(videos, channels)
    scored = add_outlier_scores(contextual, baseline_size=20)

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
            st.selectbox(
                "Nguồn",
                ["Kênh theo dõi"],
                disabled=True,
                key="outlier_source",
                help="Nguồn Toàn thị trường sẽ được thêm khi có bảng lưu market results ở Giai đoạn 2.",
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
                value=1_000_000,
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
            "Lọc tiêu đề theo từ khóa",
            placeholder="Nhập một phần tiêu đề hoặc từ khóa",
            key="outlier_keyword",
        ).strip().lower()

    filtered = filter_by_period(scored, period)
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
            and int(video.get("view_count") or 0) > max(1, int(video.get("subscriber_count") or 0))
            and float(video.get("outlier_score") or 0) >= 2
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
        and (not keyword or keyword in str(video.get("title", "")).lower())
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
        "Chỉ tìm khi bấm nút. Kết quả cùng bộ lọc được giữ trong phiên 10 phút để tránh gọi search.list lặp lại."
    )
    row = st.columns([3, 1, 1, 1])
    with row[0]:
        query = st.text_input(
            "Từ khóa thị trường",
            placeholder="police bodycam, homeless documentary, village cooking...",
            key="market_query",
        ).strip()
    with row[1]:
        region = st.selectbox(
            "Quốc gia",
            ["US", "VN", "ID", "FR", "DE", "ES", "GB", "BR", "TH"],
            key="market_region",
        )
    with row[2]:
        days = st.selectbox("Thời gian", [1, 3, 7, 30, 90, 365], index=3, key="market_days")
    with row[3]:
        search_limit = st.selectbox("Số kết quả", [12, 24, 50], index=1, key="market_limit")

    if st.button(
        "Quét toàn thị trường",
        type="primary",
        disabled=not bool(query),
        key="market_search_button",
    ):
        if not api:
            st.error("Chưa cấu hình YOUTUBE_API_KEY trong Streamlit Secrets.")
        else:
            cache_key = (query.lower(), region, int(days), int(search_limit))
            cached = st.session_state.get("market_search_cache", {})
            cached_at = cached.get("created_at")
            is_fresh = (
                cached.get("key") == cache_key
                and isinstance(cached_at, datetime)
                and datetime.now(timezone.utc) - cached_at < timedelta(minutes=10)
            )
            if is_fresh:
                st.session_state["market_results"] = cached.get("results", [])
                st.info("Đang dùng kết quả đã giữ trong phiên, không gọi lại YouTube API.")
            else:
                published_after = (
                    datetime.now(timezone.utc) - timedelta(days=int(days))
                ).isoformat().replace("+00:00", "Z")
                try:
                    with st.spinner("Đang lấy dữ liệu từ YouTube..."):
                        results = api.search_videos(
                            query,
                            max_results=int(search_limit),
                            region_code=region,
                            published_after=published_after,
                            order="viewCount",
                        )
                    normalized: list[dict[str, Any]] = []
                    for result in results:
                        row_result = dict(result)
                        row_result["duration_seconds"] = duration_to_seconds(
                            str(row_result.get("duration", ""))
                        )
                        published = parse_dt(row_result.get("published_at"))
                        age_hours = (
                            max(1.0, (datetime.now(timezone.utc) - published).total_seconds() / 3600)
                            if published
                            else 24.0
                        )
                        row_result["views_per_day"] = int(
                            int(row_result.get("view_count", 0) or 0)
                            / max(age_hours / 24, 1 / 24)
                        )
                        normalized.append(row_result)
                    st.session_state["market_results"] = normalized
                    st.session_state["market_search_cache"] = {
                        "key": cache_key,
                        "created_at": datetime.now(timezone.utc),
                        "results": normalized,
                    }
                except Exception as exc:
                    st.error(f"Không thể tìm video trên YouTube: {exc}")

    market_results = st.session_state.get("market_results", [])
    if market_results:
        total_views = sum(int(row.get("view_count", 0) or 0) for row in market_results)
        average_daily = int(
            sum(int(row.get("views_per_day", 0) or 0) for row in market_results)
            / max(1, len(market_results))
        )
        metrics = st.columns(3)
        metrics[0].metric("Video tìm thấy", len(market_results))
        metrics[1].metric("Tổng view mẫu", fmt_int(total_views))
        metrics[2].metric("View/ngày trung bình", fmt_int(average_daily))
        render_video_grid(market_results, columns_count=4)
        st.caption(
            "Giai đoạn 1 chưa lưu kết quả tìm kiếm thị trường vào Supabase; chức năng này sẽ dùng bảng riêng ở Giai đoạn 2."
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
        "Dữ liệu hiện tại chưa có cờ Shorts chính thức; trang dùng thời lượng tối đa 180 giây để phân loại gần đúng."
    )
    contextual = attach_channel_context(videos, channels)
    scored = [video for video in add_outlier_scores(contextual) if is_short(video)]

    controls = st.columns(5)
    with controls[0]:
        period = st.selectbox(
            "Thời gian",
            ["24 giờ", "3 ngày", "7 ngày", "30 ngày", "Tất cả"],
            index=3,
            key="shorts_period",
        )
    with controls[1]:
        minimum_views = st.number_input(
            "View tối thiểu",
            min_value=0,
            value=0,
            step=1_000,
            key="shorts_min_views",
        )
    with controls[2]:
        maximum_subscribers = st.number_input(
            "Subscriber tối đa",
            min_value=0,
            value=1_000_000,
            step=10_000,
            key="shorts_max_subscribers",
        )
    with controls[3]:
        minimum_outlier = st.selectbox(
            "Outlier tối thiểu",
            [0.0, 1.2, 2.0, 5.0, 10.0],
            index=1,
            key="shorts_min_outlier",
        )
    with controls[4]:
        result_limit = st.selectbox(
            "Số lượng",
            [20, 50, 100, 200],
            index=1,
            key="shorts_result_limit",
        )

    filtered = filter_by_period(scored, period)
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
        "Bản Giai đoạn 1 dùng dữ liệu kênh theo dõi hiện có; kênh mới phát hiện từ toàn thị trường sẽ được bổ sung ở Giai đoạn 2."
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

    max_subscribers = st.number_input(
        "Subscriber tối đa",
        min_value=0,
        value=500_000,
        step=10_000,
        key="emerging_max_subscribers",
    )
    emerging_rows = []
    for channel in channels:
        channel_id = str(channel.get("channel_id", ""))
        subscribers = int(channel.get("subscriber_count", 0) or 0)
        if subscribers > int(max_subscribers):
            continue
        emerging_rows.append(
            {
                "Kênh": channel.get("title"),
                "Subscriber": subscribers,
                "View tăng 7 ngày": growth7.get(channel_id),
                "View tăng 30 ngày": growth30.get(channel_id),
                "Video outlier ≥2x": outlier_counts.get(channel_id, 0),
                "Tần suất/tuần": channel.get("frequency_per_week"),
                "View video 30 ngày": channel.get("views_of_videos_published_30d"),
                "Chủ đề": channel.get("auto_subject"),
                "Ngách": channel.get("auto_niche"),
                "Quốc gia": channel.get("country"),
                "Cập nhật": channel.get("updated_at"),
                "Link": channel.get("canonical_url"),
            }
        )
    emerging_rows.sort(
        key=lambda row: (
            int(row.get("Video outlier ≥2x") or 0),
            int(row.get("View tăng 30 ngày") or 0),
            int(row.get("View video 30 ngày") or 0),
        ),
        reverse=True,
    )
    if emerging_rows:
        st.dataframe(
            pd.DataFrame(emerging_rows),
            use_container_width=True,
            hide_index=True,
            column_config={"Link": st.column_config.LinkColumn("Link")},
        )
    else:
        st.info("Chưa có kênh phù hợp với ngưỡng subscriber.")

elif nav == "Từ khóa tăng trong tuần":
    st.info(
        "Chưa kích hoạt ở Giai đoạn 1 vì schema hiện tại không có bảng lịch sử từ khóa hoặc market scan. "
        "Không thể tính mức tăng đáng tin cậy chỉ từ một lần tìm kiếm YouTube."
    )
    st.markdown(
        "Trang đã được giữ trong menu để Giai đoạn 3 bổ sung so sánh cửa sổ 24 giờ, 3 ngày, 7 ngày và 30 ngày từ dữ liệu thu thập thực tế."
    )

elif nav == "Từ khóa đã lưu":
    st.info(
        "Schema hiện tại chỉ có channels, videos và snapshots. Chưa có bảng từ khóa đã lưu nên app không tự đoán tên cột hoặc ghi dữ liệu vào bảng chưa tồn tại."
    )
    st.markdown(
        "Giai đoạn 2 sẽ cần SQL migration riêng cho danh sách từ khóa, lịch sử quét và kết quả thị trường."
    )

elif nav == "Cài đặt":
    st.caption("Không hiển thị hoặc cho phép sao chép API key thật trên giao diện.")
    configuration = st.columns(3)
    configuration[0].metric("Supabase", "Đã cấu hình" if supabase_url and supabase_key else "Thiếu")
    configuration[1].metric("YouTube API", "Đã cấu hình" if api else "Thiếu")
    configuration[2].metric("Dữ liệu cache", "TTL 5 phút")

    st.markdown("### Thiết lập phiên hiện tại")
    st.write(f"Số ngày quét: **{lookback_days}**")
    st.write(f"Số trang mỗi kênh: **{max_pages}**")
    st.write("Số video chuẩn tính median: **20**")
    st.write("Số kết quả mỗi trang Video vượt trội: **24**")
    st.write(f"Giới hạn đọc video đã lưu cho dashboard: **{MAX_SAVED_VIDEOS:,}**")

    tests = st.columns(2)
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

    if st.button("Xóa cache dữ liệu", key="clear_data_cache"):
        clear_saved_data_cache()
        st.success("Đã xóa cache. Dữ liệu sẽ được đọc lại ở lần rerun tiếp theo.")
