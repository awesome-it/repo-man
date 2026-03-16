# Documentation index

Human-readable documentation for repo-man: an extensible package repository manager with pluggable formats and storage.

| Document | Description |
|----------|-------------|
| [architecture.md](architecture.md) | High-level architecture, components, data flow, extension points, and **diagrams** (system context, request routing, storage layout, publish flow). |
| [design-decisions.md](design-decisions.md) | Rationale for pull-through cache, metadata freshness, latest-N retention, storage/format abstraction, config, and Prometheus. |
| [apt-repo-types.md](apt-repo-types.md) | APT format (included): repository kinds (classic Ubuntu/Debian/GitLab, Kubernetes, CRI-O, local) and layout types. |
| [extension-guide.md](extension-guide.md) | How to add storage providers, package format types, or layout profiles. |
| [examples.md](examples.md) | Deployment examples: office/datacenter cache and publishing, Kubernetes per-node DaemonSet, Compose for build pipelines. |
| [operations.md](operations.md) | Config reference, Prometheus metrics, production run, container and volume layout. |
| [client-metrics.md](client-metrics.md) | Client statistics metrics: per-client packages served, last-served timestamp, and alerting when hosts don’t update. |
| [monitoring.md](monitoring.md) | Monitoring and alerting: upstream update failures, misconfiguration, 404 rate, storage/publish errors; example PromQL. |
| [support-policy.md](support-policy.md) | Type of support, end-of-support policy, and security updates. |
| [cra-compliance.md](cra-compliance.md) | CRA (EU Cyber Resilience Act) conformity checklist and documentation mapping. |
