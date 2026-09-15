"""Unit tests for do-release-upgrade HEAD path allowlist and meta-release rewrite."""

from repo_man.http_upgrade_paths import (
    is_do_release_upgrade_head_path,
    is_meta_release_path,
    public_origin_from_headers,
    rewrite_meta_release_urls,
)


def test_allowlist_dist_upgrader() -> None:
    assert is_do_release_upgrade_head_path(
        "/ubuntu/dists/noble-updates/main/dist-upgrader-all/current/ReleaseAnnouncement"
    )
    assert is_do_release_upgrade_head_path(
        "/ubuntu/dists/noble-updates/main/dist-upgrader-amd64/current/foo.tar.gz"
    )


def test_allowlist_meta_release() -> None:
    assert is_do_release_upgrade_head_path("/ubuntu/meta-release")
    assert is_do_release_upgrade_head_path("/ubuntu/meta-release-lts")
    assert is_do_release_upgrade_head_path("/p/meta-release?lang=en")
    assert is_meta_release_path("/ubuntu/meta-release-lts")
    assert not is_meta_release_path("/ubuntu/dists/jammy/Release")


def test_reject_other_paths() -> None:
    assert not is_do_release_upgrade_head_path("/ubuntu/dists/jammy/Release")
    assert not is_do_release_upgrade_head_path("/ubuntu/pool/main/v/vim/vim_1_amd64.deb")
    assert not is_do_release_upgrade_head_path("/metrics")
    assert not is_do_release_upgrade_head_path("/ubuntu/foo-meta-release/bar")


def test_rewrite_meta_release_urls_maps_archive_hosts() -> None:
    body = b"""Dist: noble
Release-File: http://archive.ubuntu.com/ubuntu/dists/noble-updates/Release
ReleaseNotes: http://archive.ubuntu.com/ubuntu/dists/noble-updates/main/dist-upgrader-all/current/ReleaseAnnouncement
UpgradeTool: https://de.archive.ubuntu.com/ubuntu/dists/noble-updates/main/dist-upgrader-all/current/noble.tar.gz
UpgradeToolSignature: http://security.ubuntu.com/ubuntu/dists/noble-updates/main/dist-upgrader-all/current/noble.tar.gz.gpg
ReleaseNotesHtml: http://changelogs.ubuntu.com/EOLReleaseAnnouncement
"""
    out = rewrite_meta_release_urls(body, "https://repo.vbl-net.de", "/ubuntu").decode()
    assert "https://repo.vbl-net.de/ubuntu/dists/noble-updates/Release" in out
    assert "https://repo.vbl-net.de/ubuntu/dists/noble-updates/main/dist-upgrader-all/current/ReleaseAnnouncement" in out
    assert "https://repo.vbl-net.de/ubuntu/dists/noble-updates/main/dist-upgrader-all/current/noble.tar.gz" in out
    assert "https://repo.vbl-net.de/ubuntu/dists/noble-updates/main/dist-upgrader-all/current/noble.tar.gz.gpg" in out
    assert "http://changelogs.ubuntu.com/EOLReleaseAnnouncement" in out
    assert "archive.ubuntu.com" not in out
    assert "security.ubuntu.com" not in out


def test_rewrite_meta_release_urls_old_releases() -> None:
    body = b"UpgradeTool: http://old-releases.ubuntu.com/ubuntu/dists/dapper-updates/main/dist-upgrader-all/current/dapper.tar.gz\n"
    out = rewrite_meta_release_urls(body, "http://mirror.example:8080", "/ubuntu").decode()
    assert out == (
        "UpgradeTool: http://mirror.example:8080/ubuntu/dists/dapper-updates/"
        "main/dist-upgrader-all/current/dapper.tar.gz\n"
    )


def test_rewrite_meta_release_urls_noop_without_origin() -> None:
    body = b"Release-File: http://archive.ubuntu.com/ubuntu/dists/noble-updates/Release\n"
    assert rewrite_meta_release_urls(body, "", "/ubuntu") == body


def test_public_origin_from_headers_prefers_forwarded() -> None:
    assert (
        public_origin_from_headers(
            "internal:8080",
            scheme="http",
            forwarded_proto="https",
            forwarded_host="repo.vbl-net.de",
        )
        == "https://repo.vbl-net.de"
    )
    assert public_origin_from_headers("repo.example", scheme="https") == "https://repo.example"
    assert public_origin_from_headers(None) is None
