-- Separate from legacy CRM schemas. Account ownership is enforced by Postgres.
create table public.gm_workspace_records (
    owner_id uuid not null references auth.users(id) on delete cascade,
    kind text not null check (kind in ('profile', 'campaign', 'lead', 'thread')),
    record_id text not null check (length(record_id) between 1 and 80),
    data jsonb not null check (jsonb_typeof(data) = 'object'),
    updated_at timestamptz not null default now(),
    primary key (owner_id, kind, record_id)
);
create index gm_workspace_records_owner_kind_updated
    on public.gm_workspace_records (owner_id, kind, updated_at desc);
alter table public.gm_workspace_records enable row level security;
revoke all on public.gm_workspace_records from anon;
grant select, insert, update, delete on public.gm_workspace_records to authenticated;
create policy workspace_owner_select on public.gm_workspace_records
    for select to authenticated using ((select auth.uid()) = owner_id);
create policy workspace_owner_insert on public.gm_workspace_records
    for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy workspace_owner_update on public.gm_workspace_records
    for update to authenticated using ((select auth.uid()) = owner_id)
    with check ((select auth.uid()) = owner_id);
create policy workspace_owner_delete on public.gm_workspace_records
    for delete to authenticated using ((select auth.uid()) = owner_id);
