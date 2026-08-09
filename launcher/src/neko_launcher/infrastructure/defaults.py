"""Built-in launcher configuration.

The publishable key is intentionally embedded in the desktop client.  It is
not a secret and is subject to the same RLS and RPC grants as every other
public client.  Privileged/service-role keys must never be placed here.
"""

SUPABASE_URL = "https://miikoutrnxsunbndecqh.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_mMW9OyuaGxB6YKmiPJo7gA_FNZjDb7v"
PRODUCT_CODE = "neko-family-proxy"
ACCOUNT_RECOVERY_API_URL = "https://neko-control-room.vercel.app"
