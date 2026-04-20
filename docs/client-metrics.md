# Client statistics metrics

repo-man exposes **per-client metrics** so you can see which hosts are using the package cache and how recently they pulled packages. This document describes the metrics, how client identity is determined, and how to use them for alerting—including when hosts stop updating and you don’t have other update/health alerting in place.

## Metrics

All metrics are exposed on `GET /metrics` (same HTTP server as the repo). Client metrics are updated when a **package file** (e.g. a `.deb`) is served to a client; metadata requests (Release, Packages) do **not** update client stats.

| Metric                                          | Type    | Labels   | Description                                                               |
|-------------------------------------------------|---------|----------|---------------------------------------------------------------------------|
| `repo_man_client_packages_served_total`         | Counter | `client` | Total number of packages served to each client.                           |
| `repo_man_client_last_served_timestamp_seconds` | Gauge   | `client` | Unix timestamp (seconds) when the last package was served to each client. |

- **`client`** is either the client’s **IP address** or, when available, its **reverse-DNS hostname** (see [Client identity](#client-identity) below).
- Each label value is one “client” (one host or IP). Over time you see which clients have used the cache and when they last did.

## Client identity

- The server uses the **remote IP** of the HTTP request (`client_address[0]`).
- A **reverse DNS lookup** (IP → hostname) is done asynchronously. Until the lookup returns, the label value is the IP; after that, it is the hostname (or the IP if the lookup fails or returns the same).
- Lookups are cached in process memory, so repeated requests from the same IP reuse the same label value. This gives you stable, readable labels (e.g. `host01.office.example.com`) when your DNS is set up for it.
- Only **package** responses (e.g. `.deb`) update these metrics. Metadata (Release, Packages, etc.) does not, so “last served” really means “last time this client pulled a package,” which corresponds to install/update activity.

## Use cases

- **Visibility** — See which hosts use the repo-man cache and how much they pull (`repo_man_client_packages_served_total`).
- **Freshness** — Use `repo_man_client_last_served_timestamp_seconds` to see when each client last received a package.
- **Alerting when hosts don’t update** — If you expect hosts to run updates regularly (e.g. security updates), you can alert when a known client has not been served any package for a long time. That can indicate a host that is no longer updating, even when you don’t have host-level update or health alerting (e.g. no agent, no central patch dashboard).

## Alerting: hosts not updating

When you **do** have a list of hosts that should be using repo-man (e.g. office workstations, build runners), you can use the “last served” metric to detect hosts that have stopped pulling packages.

### Idea

- Hosts that still update will periodically request packages from repo-man, so `repo_man_client_last_served_timestamp_seconds{client="..."}` will be updated.
- If a host is supposed to use the cache but stops updating (e.g. broken cron, disabled apt, machine off or disconnected), its “last served” time will age.
- Alert when “time since last package served” exceeds a threshold (e.g. 7 days for weekly update policies).

This is useful when:

- You don’t have host-level patch/update monitoring (e.g. no agent reporting “last apt update”).
- You want a single place (repo-man metrics) to see “who is still using the cache” and “who might have stopped updating.”

### Example Prometheus rules

**Time since last package served per client (in seconds):**

```promql
time() - repo_man_client_last_served_timestamp_seconds
```

**Clients that haven’t been served a package in more than 7 days:**

```promql
(time() - repo_man_client_last_served_timestamp_seconds) > (7 * 24 * 3600)
```

You can combine this with a list of expected clients (e.g. via a recording rule or a metric that enumerates “expected” hosts) to alert only for hosts that *should* be updating but haven’t been seen. If you don’t have such a list, you can still alert on “any client that used to be active but hasn’t been served in X days” by comparing current label sets to historical ones (e.g. with Prometheus’s `absent_over_time` or similar).

### Caveats

- **New hosts** — A host that has never pulled a package through repo-man will not have a series yet; it won’t appear in “last served” until it does at least one package request. So “missing” clients (expected but never seen) need a different approach (e.g. a list of expected hosts and `absent_over_time` for that list).
- **Metadata-only traffic** — Hosts that only do `apt-get update` (metadata) without installing/upgrading packages in the time window won’t update “last served”; the metric reflects package pulls, not metadata.
- **NAT / proxies** — If many hosts sit behind one IP, they will appear as one “client”; reverse DNS might still give you a useful label.

## See also

- [Monitoring and alerting](monitoring.md) — Upstream failures, misconfiguration, 404 rate, and more example alerts.
- [Operations](operations.md) — Full metrics list, scrape config, and config reference.
- [Architecture](architecture.md) — How the serve layer and metrics fit together.
