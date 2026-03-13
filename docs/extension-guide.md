# Extension guide

How to extend repo-man: add a storage provider, add a package format (e.g. RPM), or add a layout profile for an existing format (e.g. APT).

## Adding a storage provider

1. **Implement the interface**  
   In `repo_man/storage/`, create a new module (e.g. `s3.py`). Implement `StorageBackend` from `repo_man/storage/base.py`:
   - `get(path)` → bytes or None  
   - `put(path, data)`  
   - `list_prefix(prefix)` → iterator of keys  
   - `delete(path)` → bool  
   - `exists(path)` → bool  

2. **Config / factory**  
   Extend config (or a small factory) so that when `storage.backend` (or env) is e.g. `s3`, the app constructs your backend (with bucket, prefix, credentials from config/env) and passes it to serve, cache, and publish. The rest of the code already uses the abstract interface.

3. **Tests**  
   Add unit tests under `tests/unit/storage/` that exercise your backend (e.g. against a real S3 bucket or MinIO). Reuse the same tests as for local storage where possible (e.g. put/get/delete/list_prefix).

## Adding a repo/format type (e.g. RPM)

1. **Implement the format interface**  
   In `repo_man/formats/`, add a package (e.g. `rpm/`). Implement the abstract interface from `repo_man/formats/base.py`:
   - `cache_fetch_metadata(upstream_id, upstream_config)`  
   - `cache_get_or_fetch_package(upstream_id, relative_path, upstream_config, storage)`  
   - `publish_packages(path_prefix, paths, ..., storage)`  
   - `prune(upstream_id, storage, keep_versions_per_package)`  

2. **CLI and config**  
   Add subcommands or options for the new format (e.g. `repo-man cache add-upstream --format rpm` or a separate `repo-man rpm ...` group). Config upstreams can carry a `format` field (apt | rpm). The serve layer already routes by path prefix; you only need to route requests for that prefix to your format’s cache/publish logic when resolving storage keys or fetching from upstream.

3. **Tests**  
   Add unit tests for parsing (e.g. repodata), version comparison if needed, and prune. Add integration tests for cache hit/miss and publish.

## Adding a layout profile (APT)

If a new APT layout appears (e.g. a variant of classic or single-stream):

1. **Layout type**  
   Extend the APT format to recognise a new layout (e.g. in config `layout: my-layout`). In `repo_man/formats/apt/`, add logic to map request paths and upstream URLs to the correct metadata and pool paths for that layout.

2. **Config**  
   Document the new layout and its config (path structure, any extra fields). No change to the storage or format interface is required if the layout still uses the same cache/publish key structure; otherwise extend the key scheme only within the APT format.

## Code pointers

- **Storage interface**: `repo_man/storage/base.py`  
- **Local storage example**: `repo_man/storage/local.py`  
- **Format interface**: `repo_man/formats/base.py`  
- **APT format**: `repo_man/formats/apt/` (cache, publish, metadata, version)  
- **CLI**: `repo_man/cli/` (main, cache_cmd, publish_cmd, serve_cmd, config_cmd)  
- **Serve**: `repo_man/serve.py` (path → storage key, metrics)  
- **Config**: `repo_man/config.py` (repo root, config file, upstreams, retention N)

Storage and format are designed to be pluggable; the same serve and CLI layers work with any backend that implements the interfaces.
