-- Phase T6D — Hourly Retention Pruning Schedule for Historical Server Metrics
-- Schedules hourly execution of launcher.prune_server_metrics_history(7) via pg_cron.

create extension if not exists pg_cron with schema extensions;

grant usage on schema cron to postgres;
grant all on all tables in schema cron to postgres;

-- Idempotent schedule creation: unschedule prior job if present
do $$
begin
  if exists (select 1 from cron.job where jobname = 'prune_server_metrics_history_hourly') then
    perform cron.unschedule('prune_server_metrics_history_hourly');
  end if;
end $$;

-- Schedule hourly pruning (runs at minute 0 of every hour)
select cron.schedule(
  'prune_server_metrics_history_hourly',
  '0 * * * *',
  $$select launcher.prune_server_metrics_history(7);$$
);
