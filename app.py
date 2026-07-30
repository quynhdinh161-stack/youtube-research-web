from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import html
import math

import pandas as pd
import streamlit as st

from tracker.service_web import add_outlier_scores, duration_to_seconds, growth_for_channel, sync_channel, sync_reference
from tracker.supabase_store import SupabaseStore
from tracker.youtube_api import YouTubeDataAPI

st.set_page_config(page_title="YouTube Research", page_icon="🔎", layout="wide", initial_sidebar_state="expanded")

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
  --green:#16a34a;
}
html,body,[class*="css"]{color:var(--text)}
.stApp{background:var(--bg);color:var(--text)}
[data-testid="stSidebar"]{
  background:#ffffff;
  border-right:1px solid var(--line);
}
[data-testid="stSidebar"] *{color:var(--text)}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:var(--muted)!important}
[data-testid="stHeader"]{background:rgba(246,248,251,.94);border-bottom:1px solid rgba(217,225,236,.75)}
.block-container{padding-top:1.25rem;max-width:1500px}
h1,h2,h3{letter-spacing:-.02em;color:var(--text)}
p,li,label{color:var(--text)}
.muted,.meta{color:var(--muted)}
.card,.video-card,.kpi{
  background:var(--panel);
  border:1px solid var(--line);
  box-shadow:0 5px 18px rgba(15,23,42,.06);
}
.card{border-radius:16px;padding:14px;height:100%}
.video-card{border-radius:14px;overflow:hidden;height:100%}
.video-card img{width:100%;aspect-ratio:16/9;object-fit:cover;display:block}
.video-body{padding:10px 11px 12px}
.video-title{font-weight:700;line-height:1.25;font-size:.94rem;min-height:2.35rem;color:var(--text)}
.meta{font-size:.78rem;margin-top:6px}
.badge{display:inline-block;background:var(--accent);color:white;border-radius:999px;padding:3px 8px;font-weight:700;font-size:.75rem;margin-bottom:7px}
.kpi{border-radius:16px;padding:18px}
.kpi-label{color:var(--muted);font-size:.82rem}
.kpi-value{font-size:1.75rem;font-weight:800;margin-top:4px;color:var(--text)}
.stTabs [data-baseweb="tab-list"]{gap:10px}
.stTabs [data-baseweb="tab"]{background:var(--panel-soft);border:1px solid var(--line);border-radius:10px;padding:8px 14px;color:var(--text)}
.stTabs [aria-selected="true"]{background:var(--accent-soft);color:var(--accent);border-color:#c7d2fe}
.stButton>button{
  border-radius:10px;
  border:1px solid #cbd5e1;
  background:#ffffff;
  color:var(--text);
}
.stButton>button:hover{border-color:var(--accent);color:var(--accent)}
.stButton>button[kind="primary"]{background:var(--accent);border-color:var(--accent);color:#ffffff}
.stTextInput input,.stTextArea textarea,
.stSelectbox div[data-baseweb="select"],
.stNumberInput input{
  background:#ffffff!important;
  color:var(--text)!important;
  border-color:#cbd5e1!important;
}
.stTextInput input::placeholder,.stTextArea textarea::placeholder{color:#98a2b3!important}
[data-baseweb="popover"],[role="listbox"]{background:#ffffff!important;color:var(--text)!important}
[data-baseweb="menu"] li{color:var(--text)!important}
[data-testid="stDataFrame"]{background:#ffffff;border:1px solid var(--line);border-radius:12px;overflow:hidden}
[data-testid="stMetric"]{background:#ffffff;border:1px solid var(--line);border-radius:12px;padding:12px}
[data-testid="stAlert"]{border-radius:12px}
hr{border-color:var(--line)!important}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default)).strip()
    except Exception:
        return default


def fmt_int(v) -> str:
    try: v=int(v or 0)
    except: return "—"
    if v>=1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if v>=1_000_000: return f"{v/1_000_000:.1f}M"
    if v>=1_000: return f"{v/1_000:.1f}K"
    return f"{v:,}".replace(",", ".")


def age_text(value: str | None) -> str:
    if not value: return ""
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        days=max(0,(datetime.now(timezone.utc)-dt).days)
        if days==0: return "hôm nay"
        if days<30: return f"{days} ngày trước"
        if days<365: return f"{days//30} tháng trước"
        return f"{days//365} năm trước"
    except: return ""


def video_card(v: dict, show_channel: bool=True) -> str:
    title=html.escape(str(v.get("title", "")))
    thumb=html.escape(str(v.get("thumbnail_url", "")))
    channel=html.escape(str(v.get("channel_title") or v.get("channel_name") or ""))
    badge=""
    if v.get("outlier_score"):
        badge=f'<span class="badge">{v["outlier_score"]:.1f}×</span>'
    meta=[]
    if show_channel and channel: meta.append(channel)
    meta.append(f'{fmt_int(v.get("view_count"))} views')
    if v.get("published_at"): meta.append(age_text(v.get("published_at")))
    url=f'https://www.youtube.com/watch?v={v.get("video_id","")}'
    return f'''<div class="video-card"><a href="{url}" target="_blank"><img src="{thumb}"></a><div class="video-body">{badge}<div class="video-title">{title}</div><div class="meta">{" · ".join(meta)}</div></div></div>'''


def get_clients():
    yt_key = st.session_state.get("yt_key") or secret("YOUTUBE_API_KEY")
    sb_url = secret("SUPABASE_URL")
    sb_key = secret("SUPABASE_KEY")
    if not sb_url or not sb_key:
        st.error("Chưa cấu hình Supabase. Mở README và thêm SUPABASE_URL, SUPABASE_KEY vào Secrets.")
        st.stop()
    return SupabaseStore(sb_url, sb_key), (YouTubeDataAPI(yt_key) if yt_key else None)

with st.sidebar:
    st.markdown("## 🔎 YouTube Research")
    st.caption("Dashboard nghiên cứu kênh và video")
    key_default = secret("YOUTUBE_API_KEY")
    st.session_state["yt_key"] = st.text_input("YouTube API key", value=st.session_state.get("yt_key", key_default), type="password", help="Có thể lưu cố định trong Streamlit Secrets.").strip()
    lookback = st.slider("Số ngày quét video", 30, 180, 60, 10)
    max_pages = st.slider("Số trang/kênh", 1, 10, 4)
    st.divider()
    st.caption("Dữ liệu lưu trên Supabase. API key không hiển thị cho người dùng khác.")

store, api = get_clients()
channels = store.list_channels()
videos = store.list_videos(3000)
channel_map = {c["channel_id"]: c for c in channels}
for v in videos:
    c=channel_map.get(v.get("channel_id"),{})
    v["channel_name"]=c.get("title","")
    v["channel_title"]=c.get("title","")
videos_scored = add_outlier_scores(videos)

st.markdown("# Nghiên cứu")
st.caption("Tìm cơ hội nội dung, video vượt trội và kênh đang tăng trưởng.")

nav = st.radio("", ["✨ Dành cho bạn", "🔑 Từ khóa", "▶️ Video", "⚡ Shorts", "📺 Kênh"], horizontal=True, label_visibility="collapsed")

if nav.startswith("✨"):
    k1,k2,k3,k4=st.columns(4)
    growth7=[]
    for c in channels:
        g=growth_for_channel(store,c,7)
        if g is not None: growth7.append(g)
    stats=[("Kênh theo dõi",len(channels)),("Video đã lưu",len(videos)),("View tăng 7 ngày",sum(growth7) if growth7 else None),("Video outlier ≥2×",sum(1 for v in videos_scored if v.get("outlier_score",0)>=2))]
    for col,(label,val) in zip((k1,k2,k3,k4),stats):
        with col: st.markdown(f'<div class="kpi"><div class="kpi-label">{label}</div><div class="kpi-value">{fmt_int(val) if val is not None else "—"}</div></div>',unsafe_allow_html=True)
    st.markdown("### Video vượt trội trong các kênh đang theo dõi")
    top=sorted(videos_scored,key=lambda x:(x.get("outlier_score",0),x.get("views_per_day",0)),reverse=True)[:12]
    if not top: st.info("Thêm kênh ở mục Kênh để bắt đầu.")
    else:
        for start in range(0,len(top),4):
            cols=st.columns(4)
            for col,v in zip(cols,top[start:start+4]):
                with col: st.markdown(video_card(v),unsafe_allow_html=True)

elif nav.startswith("🔑"):
    st.markdown("### Nghiên cứu từ khóa")
    c1,c2,c3=st.columns([3,1,1])
    with c1: q=st.text_input("Từ khóa",placeholder="Ví dụ: village cooking, police bodycam, natural disasters")
    with c2: region=st.selectbox("Khu vực",["US","VN","ID","FR","DE","ES","GB"],index=0)
    with c3: days=st.selectbox("Thời gian",[7,30,90,365],index=1)
    if st.button("Tìm video",type="primary",disabled=not bool(q.strip())):
        if not api: st.error("Chưa có YouTube API key")
        else:
            after=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat().replace("+00:00","Z")
            with st.spinner("Đang lấy dữ liệu YouTube..."):
                results=api.search_videos(q.strip(),max_results=24,region_code=region,published_after=after,order="viewCount")
                for r in results:
                    r["duration_seconds"]=duration_to_seconds(r.get("duration",""))
                    dt=datetime.fromisoformat(r["published_at"].replace("Z","+00:00")) if r.get("published_at") else datetime.now(timezone.utc)
                    r["views_per_day"]=int(r.get("view_count",0)/max(1,(datetime.now(timezone.utc)-dt).days))
                st.session_state["keyword_results"]=results
                st.session_state["keyword_query"]=q.strip()
    results=st.session_state.get("keyword_results",[])
    if results:
        total=sum(r.get("view_count",0) for r in results)
        avg_day=int(sum(r.get("views_per_day",0) for r in results)/max(1,len(results)))
        a,b,c=st.columns(3)
        a.metric("Video tìm thấy",len(results)); b.metric("Tổng view mẫu",fmt_int(total)); c.metric("View/ngày trung bình",fmt_int(avg_day))
        for start in range(0,len(results),4):
            cols=st.columns(4)
            for col,v in zip(cols,results[start:start+4]):
                with col: st.markdown(video_card(v),unsafe_allow_html=True)

elif nav.startswith("▶️") or nav.startswith("⚡"):
    short_mode=nav.startswith("⚡")
    title="Shorts / video ngắn" if short_mode else "Video gần đây"
    st.markdown(f"### {title}")
    subset=[v for v in videos_scored if (int(v.get("duration_seconds") or duration_to_seconds(v.get("duration","")))<=180)==short_mode]
    subset=sorted(subset,key=lambda x:x.get("published_at") or "",reverse=True)[:120]
    if not subset: st.info("Chưa có dữ liệu phù hợp.")
    for start in range(0,len(subset),4):
        cols=st.columns(4)
        for col,v in zip(cols,subset[start:start+4]):
            with col: st.markdown(video_card(v),unsafe_allow_html=True)

else:
    st.markdown("### Quản lý và theo dõi kênh")
    with st.expander("➕ Thêm nhiều kênh",expanded=not bool(channels)):
        refs=st.text_area("Mỗi dòng một link kênh, @handle hoặc Channel ID",height=140,placeholder="https://www.youtube.com/@channel/videos\n@anotherchannel")
        if st.button("Thêm và lấy dữ liệu",type="primary"):
            if not api: st.error("Chưa có YouTube API key")
            else:
                items=[x.strip() for x in refs.splitlines() if x.strip()]
                bar=st.progress(0); status=st.empty(); ok=0
                for i,ref in enumerate(items,1):
                    try:
                        c=sync_reference(store,api,ref,lookback,max_pages); ok+=1; status.info(f"{i}/{len(items)} · {c['title']}")
                    except Exception as e: status.warning(f"{ref}: {e}")
                    bar.progress(i/max(1,len(items)))
                st.success(f"Đã thêm {ok}/{len(items)} kênh")
                st.rerun()
    c1,c2=st.columns([1,5])
    with c1:
        if st.button("🔄 Cập nhật tất cả",disabled=not bool(channels)):
            if not api: st.error("Chưa có YouTube API key")
            else:
                bar=st.progress(0); status=st.empty(); ok=0
                for i,c in enumerate(channels,1):
                    try: sync_channel(store,api,c["channel_id"],lookback,max_pages);ok+=1;status.info(f"{i}/{len(channels)} · {c['title']}")
                    except Exception as e: status.warning(f"{c['title']}: {e}")
                    bar.progress(i/max(1,len(channels)))
                st.success(f"Đã cập nhật {ok}/{len(channels)} kênh"); st.rerun()
    if channels:
        rows=[]
        for c in channels:
            rows.append({
                "Kênh":c.get("title"),"Chủ đề":c.get("auto_subject"),"Ngách":c.get("auto_niche"),
                "Subscriber":c.get("subscriber_count"),"Tổng view":c.get("total_view_count"),"Video":c.get("video_count"),
                "View video 30 ngày":c.get("views_of_videos_published_30d"),"Tần suất/tuần":c.get("frequency_per_week"),
                "Video mới nhất":c.get("last_video_title"),"Ngày đăng gần nhất":c.get("last_video_published_at"),"Link":c.get("canonical_url")
            })
        df=pd.DataFrame(rows)
        st.dataframe(df,use_container_width=True,hide_index=True,column_config={"Link":st.column_config.LinkColumn("Link"),"Subscriber":st.column_config.NumberColumn(format="%d"),"Tổng view":st.column_config.NumberColumn(format="%d"),"View video 30 ngày":st.column_config.NumberColumn(format="%d")})
        out=BytesIO()
        with pd.ExcelWriter(out,engine="openpyxl") as writer: df.to_excel(writer,index=False,sheet_name="Kenh")
        st.download_button("⬇️ Xuất Excel",out.getvalue(),"youtube_channels.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
