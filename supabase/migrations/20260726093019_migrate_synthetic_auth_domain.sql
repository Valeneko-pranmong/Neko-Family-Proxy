-- `.local` is rejected by Supabase Auth's email validator for new signups.
-- Move existing username-backed Auth identifiers to a syntactically valid,
-- non-mailbox domain while preserving their password hashes and user IDs.

update auth.users
set email = replace(email, '@auth.neko.local', '@auth.neko.family'),
    updated_at = now()
where email like '%@auth.neko.local';
