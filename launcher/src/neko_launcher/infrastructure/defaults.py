"""Built-in launcher configuration.

The publishable key is intentionally embedded in the desktop client.  It is
not a secret and is subject to the same RLS and RPC grants as every other
public client.  Privileged/service-role keys must never be placed here.
"""

SUPABASE_URL = "https://miikoutrnxsunbndecqh.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_mMW9OyuaGxB6YKmiPJo7gA_FNZjDb7v"
# Set this only after the permanent Vercel production URL is deployed and
# allow-listed in Supabase Auth. Preview URLs must not be embedded in releases.
PASSWORD_RESET_REDIRECT_URL = ""
PRODUCT_CODE = "neko-family-proxy"
