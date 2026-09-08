from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neko_launcher.infrastructure.github_release import (
    GITHUB_RELEASE_OWNER,
    GITHUB_RELEASE_REPOSITORY,
    GITHUB_RELEASE_USER_AGENT,
    GitHubReleaseAsset,
)
from neko_launcher.updater.canonical_json import canonical_json_loads

MANIFEST_MAX_BYTES = 65_536
_CHUNK_SIZE = 1_048_576  # 1 MiB streaming chunk

_ASSET_PATH_PREFIX = (
    f"/{GITHUB_RELEASE_OWNER}/{GITHUB_RELEASE_REPOSITORY}/releases/download/"
)

_ALLOWED_REDIRECT_HOSTS = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})


@dataclass(frozen=True)
class DownloadedManifest:
    exact_bytes: bytes
    document: object
    actual_size: int


@dataclass(frozen=True)
class DownloadedArtifact:
    size: int
    sha256: str


class GitHubAssetDownloadError(ValueError):
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


def _validate_initial_asset_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
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


def _validate_redirect_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError:
        return False

    if (
        parsed.scheme != "https"
        or not hostname
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        return False

    try:
        ascii_host = hostname.encode("idna").decode("ascii").lower()
    except Exception:
        return False

    return ascii_host in _ALLOWED_REDIRECT_HOSTS


def _extract_single_location(headers: object) -> str | None:
    if headers is None:
        return None

    locations: list[str] | None = None
    if hasattr(headers, "get_all"):
        locations = headers.get_all("Location")
    elif hasattr(headers, "get"):
        loc = headers.get("Location")
        if loc is not None:
            locations = loc if isinstance(loc, list) else [loc]

    if not locations or len(locations) != 1:
        return None

    location = locations[0]
    if not isinstance(location, str) or not location.strip():
        return None

    return location.strip()


def _open_asset_stream(
    initial_url: str,
    *,
    connect_timeout: float,
    maximum_redirects: int,
    opener: Any | None = None,
) -> Any:
    if not _validate_initial_asset_url(initial_url):
        raise GitHubAssetDownloadError("DOWNLOAD_REDIRECT_INVALID") from None

    active_opener = (
        opener
        if opener is not None
        else urllib.request.build_opener(_NoRedirectHandler())
    )

    current_url = initial_url
    visited_urls = {current_url}
    redirect_count = 0

    while True:
        request = urllib.request.Request(
            current_url,
            method="GET",
            headers={
                "User-Agent": GITHUB_RELEASE_USER_AGENT,
                "Accept": "*/*",
            },
        )
        try:
            response = active_opener.open(request, timeout=connect_timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                response_headers = exc.headers
            else:
                raise GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE") from None
        else:
            status = getattr(response, "status", getattr(response, "code", None))
            if status is None:
                status = response.getcode()

            if status == 200:
                return response
            elif status in (301, 302, 303, 307, 308):
                response_headers = getattr(response, "headers", response.info())
            else:
                raise GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE") from None

        redirect_count += 1
        if redirect_count > maximum_redirects:
            raise GitHubAssetDownloadError("DOWNLOAD_REDIRECT_INVALID") from None

        location = _extract_single_location(response_headers)
        if location is None:
            raise GitHubAssetDownloadError("DOWNLOAD_REDIRECT_INVALID") from None

        next_url = urllib.parse.urljoin(current_url, location)
        if next_url in visited_urls:
            raise GitHubAssetDownloadError("DOWNLOAD_REDIRECT_INVALID") from None
        visited_urls.add(next_url)

        if not _validate_redirect_url(next_url):
            raise GitHubAssetDownloadError("DOWNLOAD_REDIRECT_INVALID") from None

        current_url = next_url


class GitHubManifestDownloader:
    def __init__(
        self,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        maximum_redirects: int = 5,
        _opener: Any | None = None,
    ) -> None:
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._maximum_redirects = maximum_redirects
        self._opener = _opener

    def download(self, asset: GitHubReleaseAsset) -> DownloadedManifest:
        if asset.name != "release-v2.json":
            raise GitHubAssetDownloadError("MANIFEST_RESPONSE_INVALID") from None

        response = _open_asset_stream(
            asset.browser_download_url,
            connect_timeout=self._connect_timeout,
            maximum_redirects=self._maximum_redirects,
            opener=self._opener,
        )

        try:
            with response:
                chunks: list[bytes] = []
                total_read = 0
                while True:
                    try:
                        chunk = response.read(4096)
                    except (urllib.error.URLError, TimeoutError, OSError):
                        raise GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE") from None

                    if not chunk:
                        break
                    chunks.append(chunk)
                    total_read += len(chunk)
                    if total_read > MANIFEST_MAX_BYTES:
                        raise GitHubAssetDownloadError("MANIFEST_TOO_LARGE") from None
        except GitHubAssetDownloadError:
            raise
        except Exception:
            raise GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE") from None

        exact_bytes = b"".join(chunks)

        if asset.size != len(exact_bytes):
            raise GitHubAssetDownloadError("MANIFEST_RESPONSE_INVALID") from None

        try:
            document = canonical_json_loads(exact_bytes)
        except Exception:
            raise GitHubAssetDownloadError("MANIFEST_RESPONSE_INVALID") from None

        return DownloadedManifest(
            exact_bytes=exact_bytes,
            document=document,
            actual_size=len(exact_bytes),
        )


class GitHubAssetDownloader:
    def __init__(
        self,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        maximum_redirects: int = 5,
        _opener: Any | None = None,
    ) -> None:
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._maximum_redirects = maximum_redirects
        self._opener = _opener

    def download(
        self,
        *,
        initial_url: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
    ) -> DownloadedArtifact:
        dest_path = Path(destination)
        if not dest_path.parent.is_dir():
            raise GitHubAssetDownloadError("DOWNLOAD_WRITE_FAILED") from None

        response = _open_asset_stream(
            initial_url,
            connect_timeout=self._connect_timeout,
            maximum_redirects=self._maximum_redirects,
            opener=self._opener,
        )

        try:
            file_handle = dest_path.open("xb")
        except (FileExistsError, OSError):
            if hasattr(response, "close"):
                response.close()
            raise GitHubAssetDownloadError("DOWNLOAD_WRITE_FAILED") from None

        incomplete = True
        hasher = hashlib.sha256()
        bytes_written = 0

        try:
            with response:
                try:
                    while True:
                        try:
                            chunk = response.read(_CHUNK_SIZE)
                        except (urllib.error.URLError, TimeoutError, OSError):
                            raise GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE") from None

                        if not chunk:
                            break

                        bytes_written += len(chunk)
                        if bytes_written > expected_size:
                            raise GitHubAssetDownloadError("DOWNLOAD_SIZE_MISMATCH") from None

                        hasher.update(chunk)
                        try:
                            file_handle.write(chunk)
                        except OSError:
                            raise GitHubAssetDownloadError("DOWNLOAD_WRITE_FAILED") from None

                    if bytes_written < expected_size:
                        raise GitHubAssetDownloadError("DOWNLOAD_SIZE_MISMATCH") from None

                    try:
                        file_handle.flush()
                        os.fsync(file_handle.fileno())
                    except OSError:
                        pass

                    actual_sha256 = hasher.hexdigest().lower()
                    if actual_sha256 != expected_sha256.lower():
                        raise GitHubAssetDownloadError("DOWNLOAD_HASH_MISMATCH") from None

                    incomplete = False
                finally:
                    file_handle.close()
        finally:
            if incomplete:
                try:
                    dest_path.unlink(missing_ok=True)
                except OSError:
                    pass

        return DownloadedArtifact(
            size=bytes_written,
            sha256=actual_sha256,
        )
