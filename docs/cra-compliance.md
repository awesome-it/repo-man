# CRA (Cyber Resilience Act) conformity checklist

This document maps EU Regulation (EU) 2024/2973 (Cyber Resilience Act) documentation requirements to this project. It helps identify what exists and what is missing for CRA alignment (including for open-source software stewards under Article 24).

## Annex II – Information and instructions to the user

| Requirement | Status | Where / action |
|-------------|--------|----------------|
| 1. Manufacturer name, address, email/website | ⬜ Missing | Add to README or a dedicated contact/legal doc. |
| 2. Single point of contact for vulnerability reporting; link to coordinated vulnerability disclosure policy | ✅ | [SECURITY.md](../SECURITY.md) (contact + disclosure policy). |
| 3. Name, type, unique identification of the product | ✅ | README (repo-man), [pyproject.toml](../pyproject.toml) (name, version). |
| 4. Intended purpose, security environment, essential functionalities, security properties | ✅ | [README](../README.md), [architecture.md](architecture.md), [design-decisions.md](design-decisions.md). |
| 5. Known/foreseeable circumstances that may lead to significant cybersecurity risks | ⬜ Missing | Add a short “Security considerations” or “Known risks” section (e.g. in operations or a dedicated doc). |
| 6. Internet address of EU declaration of conformity | ⬜ N/A or later | Only if a declaration is issued. |
| 7. Type of technical security support and end-date of support period | ✅ | [Support policy](support-policy.md). |
| 8. Instructions: (a) secure use; (b) how changes affect security; (c) install security updates; (d) secure decommissioning/data removal; (e) turn off auto security updates; (f) integration info | ⬜ Partial | [operations.md](operations.md) covers use and config. Add explicit “Secure use and lifecycle” section covering (a)–(e) and reference from README. |
| 9. Where SBOM can be accessed (if made available) | ⬜ Missing | Add SBOM generation (e.g. from lockfile) and document location, or state “SBOM available on request” in SECURITY or support policy. |

## Annex VII – Technical documentation

| Requirement | Status | Where / action |
|-------------|--------|----------------|
| 1. General description (intended purpose, versions, user info per Annex II) | ✅ | README, docs index, operations. |
| 2(a) Design/development, system architecture | ✅ | [architecture.md](architecture.md), [design-decisions.md](design-decisions.md). |
| 2(b) Vulnerability handling: SBOM, coordinated disclosure, contact, secure updates | ✅ / ⬜ | SECURITY.md (disclosure, contact). Add SBOM (e.g. `uv export` or CycloneDX) and where to find it. |
| 3. Assessment of cybersecurity risks | ⬜ Missing | Add a short risk assessment or “Security considerations” doc. |
| 4. Information determining support period | ✅ | [Support policy](support-policy.md). |
| 5. Harmonised standards / solutions to meet essential requirements | ⬜ Partial | Can be added when claiming conformity; reference standards or describe measures. |
| 6. Test reports | ⬜ Partial | Tests exist; add one-line note in docs that test runs verify behaviour (and where tests live). |
| 7. EU declaration of conformity | ⬜ N/A or later | Only if conformity is declared. |
| 8. SBOM (on request by authority) | ⬜ Missing | Generate and store SBOM; document how to produce/request. |

## Other

| Item | Status | Action |
|------|--------|--------|
| LICENSE file in repository root | ✅ | [LICENSE](../LICENSE) (MIT). |
| SECURITY.md in repository root | ✅ | Present with contact and disclosure policy. |
| Support / EOL policy | ✅ | [Support policy](support-policy.md). |

## Summary of missing or incomplete items

1. **Manufacturer / steward contact** – Name, address, email/website in README or a dedicated doc.
2. **Known risks / security considerations** – Short section on foreseeable cybersecurity risks and secure use.
3. **Secure use and lifecycle** – Explicit instructions for secure use, updates, decommissioning, and (if applicable) turning off auto-updates; can extend operations.md or add a short doc.
4. **SBOM** – Generate (e.g. from lockfile), publish or document “on request,” and reference in SECURITY or support policy.
5. **Risk assessment** – Short assessment of cybersecurity risks (can be a small doc or section).
6. **LICENSE** – Add a LICENSE file and reference it in the README.
7. **Test documentation** – One-line note that tests exist and where they are (e.g. in README or architecture).

After adding the missing pieces, update this checklist so each row shows ✅ and the corresponding location.
