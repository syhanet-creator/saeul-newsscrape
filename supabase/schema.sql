-- 광고 배너 저장소 (Supabase → SQL Editor 에서 한 번 실행)
create table if not exists public.banners (
  id bigint generated always as identity primary key,
  caption text default '',
  image_url text not null,
  link_url text default '',
  active boolean not null default true,
  start_at timestamptz,
  end_at timestamptz,
  sort int not null default 0,
  created_at timestamptz not null default now()
);

-- 정책을 만들지 않으므로 공개(anon) 키로는 읽기·쓰기 모두 불가. 서버(service_role 키)만 접근한다.
alter table public.banners enable row level security;

-- 배너 이미지 보관함(공개 읽기)
insert into storage.buckets (id, name, public) values ('banners', 'banners', true)
on conflict (id) do nothing;
