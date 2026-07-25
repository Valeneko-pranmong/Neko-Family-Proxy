alter role authenticator
  set pgrst.db_schemas = 'public, graphql_public, launcher';

grant usage on schema launcher to authenticated;
revoke usage on schema launcher from anon;

notify pgrst, 'reload config';
