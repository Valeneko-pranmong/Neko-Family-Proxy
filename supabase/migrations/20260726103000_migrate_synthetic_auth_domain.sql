-- `.local` is rejected by Supabase Auth's email validator for new signups.
-- Move existing username-backed Auth identifiers to the project's live API
-- domain while preserving their password hashes and user IDs.

update auth.users
set email = regexp_replace(
      email,
      '@(auth\.neko\.local|auth\.neko\.family)$',
      '@miikoutrnxsunbndecqh.supabase.co'
    ),
    updated_at = now()
where email like '%@auth.neko.local'
   or email like '%@auth.neko.family';
