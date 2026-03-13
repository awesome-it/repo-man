# Monitoring and alerting

This document gives concrete Prometheus queries and alert ideas for repo-man: **cache statistics (hits and misses)**, **client statistics**, **upstream update failures**, and **misconfiguration**. For per-client metrics and “hosts not updating” alerts, see [client-metrics.md](client-metrics.md).

---

## Cache statistics (hits and misses)

`repo_man_cache_requests_total` is a counter with label **`result`**: `hit` when the response was served from cache (storage), and `miss` when it was fetched from upstream (pull-through) or the request could not be satisfied (e.g. 404). Only requests for **cache** keys (`cache/<upstream>/...`) are counted; local/published paths are not.

**Hit rate (fraction of cache lookups that were hits, over 5m):**

```promql
  rate(repo_man_cache_requests_total{result="hit"}[5m])
/ (rate(repo_man_cache_requests_total{result="hit"}[5m]) + rate(repo_man_cache_requests_total{result="miss"}[5m]))
```

**Hit and miss rates (per second):**

```promql
rate(repo_man_cache_requests_total{result="hit"}[5m])
rate(repo_man_cache_requests_total{result="miss"}[5m])
```

Use these to see how effective the pull-through cache is and to spot a sudden drop in hit rate (e.g. after a prune or upstream change).

---

## Client statistics (hosts not updating)

Use **per-client** metrics to see which hosts use the cache and to alert when a host stops pulling packages (e.g. no other update/patch monitoring in place).

- **Metrics:** `repo_man_client_packages_served_total`, `repo_man_client_last_served_timestamp_seconds`
- **Details and examples:** [client-metrics.md](client-metrics.md)

---

## Upstream update failures

When repo-man pulls from an upstream (e.g. Ubuntu archive), failures can be due to the upstream being down, network issues, or bad URL/suite/config. Use these metrics to detect and alert.

### Upstream last successful access

`repo_man_upstream_last_access_timestamp_seconds{upstream="<name>"}` is set when a **successful** fetch (metadata or package) from that upstream happens. It is **not** updated when a fetch fails.

- **Alert idea: upstream not updated recently**  
  If you expect traffic to an upstream (e.g. clients use `/ubuntu` daily), a very old timestamp means no successful fetch for a long time — upstream unreachable, wrong URL, or no requests.

**Time since last successful fetch (seconds):**

```promql
time() - repo_man_upstream_last_access_timestamp_seconds
```

**Upstreams with no successful fetch in the last 24 hours** (only for upstreams that have a series; i.e. have been used at least once before):

```promql
(time() - repo_man_upstream_last_access_timestamp_seconds) > (24 * 3600)
```

**Upstreams with no successful fetch in the last 7 days** (e.g. for weekly-update expectations):

```promql
(time() - repo_man_upstream_last_access_timestamp_seconds) > (7 * 24 * 3600)
```

### Upstream fetch errors

`repo_man_cache_upstream_fetch_errors_total{upstream="<name>"}` is incremented when a fetch from upstream **fails** (e.g. HTTP error, timeout). A rising rate or a high count over a short window indicates upstream or network issues.

**Rate of fetch errors per upstream (errors per second):**

```promql
rate(repo_man_cache_upstream_fetch_errors_total[5m])
```

**Alert idea: upstream failing repeatedly** — e.g. more than 1 error per minute on average over 5 minutes:

```promql
rate(repo_man_cache_upstream_fetch_errors_total[5m]) > (1/60)
```

### HTTP 404 rate as a proxy for upstream/config issues

When clients request a path that repo-man cannot satisfy (cache miss and upstream fetch failed, or no such path), repo-man returns **404**. So a **high 404 rate for a given path_prefix** often indicates:

- Upstream unreachable or returning errors
- Misconfiguration: wrong URL, wrong suite/component/arch, or wrong path_prefix so requests don’t match

**404 rate per path_prefix (requests per second):**

```promql
rate(repo_man_http_requests_total{status="404"}[5m])
```

**Path prefixes with a high share of 404s** (e.g. more than half of requests in the last 5 minutes are 404s):

```promql
  rate(repo_man_http_requests_total{status="404"}[5m])
/ rate(repo_man_http_requests_total[5m])
> 0.5
```

Use this to find path_prefixes that are misconfigured or whose upstream is failing.

---

## Misconfiguration

Misconfiguration (wrong URL, wrong path_prefix, wrong suite/component, bad credentials, etc.) often shows up as:

1. **Many 404s** for that path_prefix (see above).
2. **Upstream never or rarely updated** — `repo_man_upstream_last_access_timestamp_seconds` absent or very old for an upstream you expect to be used.
3. **Storage or publish errors** — e.g. repo root not writable, full disk.

### Storage and publish errors

- `repo_man_storage_errors_total{operation="...", backend="..."}` — storage backend errors (e.g. local filesystem, future S3).
- `repo_man_publish_errors_total{path_prefix="..."}` — failures during publish (e.g. write or metadata generation).

**Alert on any storage or publish error rate:**

```promql
rate(repo_man_storage_errors_total[5m]) > 0
# or
rate(repo_man_publish_errors_total[5m]) > 0
```

### Checklist for “upstream or path misconfiguration”

- **404 rate** for the path_prefix high? → Check upstream URL, layout, suite/component/arch and path_prefix in config.
- **upstream_last_access_timestamp_seconds** for that upstream missing or very old? → Upstream may be down or URL/suite wrong; fix config or investigate upstream.
- **cache_upstream_fetch_errors_total** increasing? → Upstream or network issue; check logs and upstream availability.

---

## Quick reference

| Goal | Metrics | Example alert |
|------|---------|----------------|
| Cache hits and misses | `repo_man_cache_requests_total` (label `result`: hit, miss) | Hit rate = `rate(hit)/(rate(hit)+rate(miss))` |
| Hosts not updating | `repo_man_client_last_served_timestamp_seconds` | Time since last package served > 7 days → [client-metrics.md](client-metrics.md) |
| Upstream not updating | `repo_man_upstream_last_access_timestamp_seconds` | `time() - metric > 24*3600` |
| Upstream fetch failures | `repo_man_cache_upstream_fetch_errors_total` | `rate(...[5m]) > threshold` |
| High 404s (config/upstream) | `repo_man_http_requests_total{status="404"}` | 404 rate or ratio high per path_prefix |
| Storage/publish problems | `repo_man_storage_errors_total`, `repo_man_publish_errors_total` | `rate(...[5m]) > 0` |

Full metric list: [operations.md](operations.md#prometheus-metrics).
