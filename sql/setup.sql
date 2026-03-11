-- Run this in Supabase Dashboard → SQL Editor

create table watchlist (
  id bigint generated always as identity primary key,
  user_id text not null,
  stock_id text not null,
  created_at timestamptz default now(),
  unique (user_id, stock_id)
);

-- Index for fast lookups by user
create index idx_watchlist_user_id on watchlist (user_id);
