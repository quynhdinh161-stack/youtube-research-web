create table if not exists public.channels (
  channel_id text primary key,
  source_ref text, canonical_url text not null, handle text, title text not null,
  description text default '', country text default '', published_at timestamptz,
  subscriber_count bigint default 0, hidden_subscriber_count integer default 0,
  total_view_count bigint default 0, video_count bigint default 0,
  uploads_playlist_id text, channel_keywords text default '', topic_categories text default '',
  thumbnail_url text default '', auto_subject text default '', auto_niche text default '',
  classification_confidence text default '', classification_reason text default '',
  last_video_id text default '', last_video_title text default '', last_video_published_at timestamptz,
  last_video_views bigint default 0, videos_30d_count integer default 0,
  views_of_videos_published_30d bigint default 0, frequency_per_week numeric default 0,
  updated_at timestamptz default now(), last_error text default ''
);

create table if not exists public.videos (
  video_id text primary key,
  channel_id text references public.channels(channel_id) on delete cascade,
  title text default '', published_at timestamptz, view_count bigint default 0,
  like_count bigint default 0, comment_count bigint default 0, duration text default '',
  duration_seconds integer default 0, thumbnail_url text default '', last_seen_at timestamptz default now()
);
create index if not exists videos_channel_idx on public.videos(channel_id);
create index if not exists videos_published_idx on public.videos(published_at desc);

create table if not exists public.snapshots (
  channel_id text references public.channels(channel_id) on delete cascade,
  captured_date date not null,
  subscriber_count bigint default 0, total_view_count bigint default 0, video_count bigint default 0,
  last_video_id text default '', last_video_views bigint default 0,
  primary key(channel_id, captured_date)
);

alter table public.channels enable row level security;
alter table public.videos enable row level security;
alter table public.snapshots enable row level security;
-- Không cần policy khi dùng SUPABASE service_role key trong Streamlit Secrets.

-- Các bảng nghiên cứu toàn thị trường nằm trong file supabase_market_migration.sql.
