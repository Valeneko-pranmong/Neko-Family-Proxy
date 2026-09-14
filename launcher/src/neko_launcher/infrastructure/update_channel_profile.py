from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neko_launcher.updater.trust_profile import VerifiedUpdateTrustProfile


@dataclass(frozen=True)
class UpdateChannelProfile:
    profile_id: str
    channel: str
    owner: str
    repository: str
    release_public_keys: Mapping[str, bytes]
    latest_release_api: str
    browser_download_prefix: str

    @classmethod
    def from_verified(cls, profile: VerifiedUpdateTrustProfile) -> UpdateChannelProfile:
        owner = profile.owner
        repo = profile.repository
        return cls(
            profile_id=profile.profile_id,
            channel=profile.channel,
            owner=owner,
            repository=repo,
            release_public_keys=types.MappingProxyType(dict(profile.release_public_keys)),
            latest_release_api=f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
            browser_download_prefix=f"/{owner}/{repo}/releases/download/",
        )
