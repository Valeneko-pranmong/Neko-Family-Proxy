-- Use a live project-owned domain for username-backed Auth identifiers.
-- Password hashes and user IDs are preserved.

update auth.users
set email = replace(
      email,
      '@auth.neko.family',
      '@miikoutrnxsunbndecqh.supabase.co'
    ),
    updated_at = now()
where email like '%@auth.neko.family';
