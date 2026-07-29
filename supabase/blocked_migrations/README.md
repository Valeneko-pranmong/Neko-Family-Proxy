# Blocked migrations

Files in this directory are retained only for security review and migration
history analysis. They are intentionally outside `supabase/migrations/` so the
Supabase CLI cannot apply them during normal migration workflows.

Do not rename a blocked file to `.sql`, move it into the active migration
directory, or execute it against a hosted project. Replace unsafe behavior with
a reviewed forward-fix migration instead.
