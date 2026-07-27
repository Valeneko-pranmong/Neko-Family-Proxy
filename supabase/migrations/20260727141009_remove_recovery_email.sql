-- Remove auth_email_for_username RPC since it was used for password reset lookup
DROP FUNCTION IF EXISTS launcher.auth_email_for_username(TEXT);

-- Re-create the user_exists RPC to ensure it only depends on usernames, not recovery emails
CREATE OR REPLACE FUNCTION launcher.user_exists(p_username TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1
        FROM auth.users
        WHERE raw_user_meta_data->>'username' = p_username
    );
END;
$$;