"""Unit tests for do-release-upgrade HEAD path allowlist."""

from repo_man.http_upgrade_paths import is_do_release_upgrade_head_path


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


def test_reject_other_paths() -> None:
    assert not is_do_release_upgrade_head_path("/ubuntu/dists/jammy/Release")
    assert not is_do_release_upgrade_head_path("/ubuntu/pool/main/v/vim/vim_1_amd64.deb")
    assert not is_do_release_upgrade_head_path("/metrics")
    assert not is_do_release_upgrade_head_path("/ubuntu/foo-meta-release/bar")
