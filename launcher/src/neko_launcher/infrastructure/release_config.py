"""Build-time release configuration for the frozen 5.2.1 preview build.

The owner approved the public staging Proxy API origin for the preview/manual
release. Source/dev builds use ``NEKO_PROXY_API_URL`` instead; frozen builds
reject that environment override.
"""

RELEASE_PROXY_API_URL = "https://neko-control-room-staging.vercel.app"
RELEASE_IDENTITY_BASE_URL = "https://neko-network-id-staging.vercel.app"
RELEASE_CHANNEL = "preview"
