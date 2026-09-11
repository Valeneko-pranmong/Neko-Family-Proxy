from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

GITHUB_RELEASE_OWNER = "Valeneko-pranmong"
GITHUB_RELEASE_REPOSITORY = "Neko-Family-Proxy"
GITHUB_RELEASE_API_URL = (
    "https://api.github.com/repos/Valeneko-pranmong/"
    "Neko-Family-Proxy/releases/latest"
)
GITHUB_RELEASE_USER_AGENT = "Neko-Family-Proxy-Launcher/5.1"

_RESPONSE_MAX_BYTES = 262_144
_ASSET_MAX_BYTES = 1_073_741_824
_TAG_PATTERN = re.compile(r"v[A-Za-z0-9._+-]{1,64}\Z", re.ASCII)
_ASSET_NAME_PATTERN = re.compile(r"[A-Za-z0-9._+-]{1,128}\Z", re.ASCII)
_ASSET_PATH_PREFIX = (
    f"/{GITHUB_RELEASE_OWNER}/{GITHUB_RELEASE_REPOSITORY}/releases/download/"
)


@dataclass(frozen=True)
class GitHubReleaseAsset:
    id: int
    name: str
    size: int
    browser_download_url: str


@dataclass(frozen=True)
class GitHubRelease:
    id: int
    tag_name: str
    draft: bool
    prerelease: bool
    assets: tuple[GitHubReleaseAsset, ...]


class GitHubReleaseDiscoveryError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


def _invalid() -> GitHubReleaseDiscoveryError:
    return GitHubReleaseDiscoveryError("GITHUB_RELEASE_RESPONSE_INVALID")


def _positive_integer(value: object, maximum: int | None = None) -> bool:
    return (
        type(value) is int
        and value > 0
        and (maximum is None or value <= maximum)
    )


def _valid_asset_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and parsed.path.startswith(_ASSET_PATH_PREFIX)
        and len(parsed.path) > len(_ASSET_PATH_PREFIX)
    )


def parse_github_release(document: object, allow_prerelease: bool = False) -> GitHubRelease:
    if not isinstance(document, dict):
        raise _invalid()

    release_id = document.get("id")
    tag_name = document.get("tag_name")
    draft = document.get("draft")
    prerelease = document.get("prerelease")
    raw_assets = document.get("assets")

    if not _positive_integer(release_id):
        raise _invalid()
    if not isinstance(tag_name, str) or _TAG_PATTERN.fullmatch(tag_name) is None:
        raise _invalid()
    if type(draft) is not bool or type(prerelease) is not bool:
        raise _invalid()
    if draft or (prerelease and not allow_prerelease):
        raise GitHubReleaseDiscoveryError("GITHUB_RELEASE_INELIGIBLE")
    if not isinstance(raw_assets, list) or not 1 <= len(raw_assets) <= 64:
        raise _invalid()

    assets: list[GitHubReleaseAsset] = []
    asset_ids: set[int] = set()
    asset_names: set[str] = set()
    folded_names: set[str] = set()
    for raw_asset in raw_assets:
        if not isinstance(raw_asset, dict):
            raise _invalid()
        asset_id = raw_asset.get("id")
        name = raw_asset.get("name")
        size = raw_asset.get("size")
        download_url = raw_asset.get("browser_download_url")
        if not _positive_integer(asset_id):
            raise _invalid()
        if not isinstance(name, str) or _ASSET_NAME_PATTERN.fullmatch(name) is None:
            raise _invalid()
        if not _positive_integer(size, _ASSET_MAX_BYTES):
            raise _invalid()
        if not _valid_asset_url(download_url):
            raise _invalid()
        folded_name = name.casefold()
        if asset_id in asset_ids or name in asset_names or folded_name in folded_names:
            raise _invalid()
        asset_ids.add(asset_id)
        asset_names.add(name)
        folded_names.add(folded_name)
        assets.append(
            GitHubReleaseAsset(
                id=asset_id,
                name=name,
                size=size,
                browser_download_url=download_url,
            )
        )

    return GitHubRelease(
        id=release_id,
        tag_name=tag_name,
        draft=draft,
        prerelease=prerelease,
        assets=tuple(assets),
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate key")
        document[key] = value
    return document


class GitHubLatestReleaseGateway:
    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def _execute_request(self, url: str, allow_prerelease: bool) -> GitHubRelease | None:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": GITHUB_RELEASE_USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise GitHubReleaseDiscoveryError("GITHUB_RELEASE_UNAVAILABLE")
                body = response.read(_RESPONSE_MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise GitHubReleaseDiscoveryError("GITHUB_RELEASE_UNAVAILABLE") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GitHubReleaseDiscoveryError("GITHUB_RELEASE_UNAVAILABLE") from None

        if len(body) > _RESPONSE_MAX_BYTES:
            raise _invalid()
        try:
            document = json.loads(
                body.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise _invalid() from None
        return parse_github_release(document, allow_prerelease=allow_prerelease)

    def fetch(self) -> GitHubRelease | None:
        return self._execute_request(GITHUB_RELEASE_API_URL, allow_prerelease=False)

    def fetch_by_id(self, release_id: int) -> GitHubRelease | None:
        url = (
            f"https://api.github.com/repos/{GITHUB_RELEASE_OWNER}/"
            f"{GITHUB_RELEASE_REPOSITORY}/releases/{release_id}"
        )
        return self._execute_request(url, allow_prerelease=True)
