# Test Pack Index

This document indexes all test inputs, execution outputs, failure scenarios, and logs against the requirements and claims in `REPORT.md` and `REQUIREMENTS_AUDIT.md`.

---

## 📁 1. Test Inputs & Outputs Map

| Scenario / Test Name | Input File | Output File | Status | HTTP Code | Requirement Tested |
|---|---|---|---|---|---|
| **01 Health Probe** | `test_inputs/01_health_probe.json` | `test_outputs/01_health_probe_result.json` | **PASS** | `200 OK` | Liveness & Readiness check |
| **02 Discourse Publish** | `test_inputs/02_discourse_publish.json` | `test_outputs/02_discourse_simulated_publish_result.json` | **PASS** | `200 OK` | Core Connector: Discourse forum |
| **03 Lemmy Publish** | `test_inputs/03_lemmy_publish.json` | `test_outputs/03_lemmy_simulated_publish_result.json` | **PASS** | `200 OK` | Core Connector: Lemmy ActivityPub |
| **04 Dev.to Publish** | `test_inputs/04_devto_publish.json` | `test_outputs/04_devto_simulated_publish_result.json` | **PASS** | `200 OK` | Core Connector: Dev.to article |
| **05 Ghost Publish** | `test_inputs/05_ghost_publish.json` | `test_outputs/05_ghost_simulated_publish_result.json` | **PASS** | `200 OK` | Core Connector: Ghost CMS Admin API |
| **06 Webhook Publish** | `test_inputs/06_webhook_publish.json` | `test_outputs/06_webhook_simulated_publish_result.json` | **PASS** | `200 OK` | Core Connector: HMAC-SHA256 Webhook |
| **07 Assisted Pack Generation** | `test_inputs/07_assisted_pack.json` | `test_outputs/07_assisted_pack_generation_result.json` | **PASS** | `200 OK` | Core Connector: Assisted ready pack |
| **08 Hashnode Publish** | `test_inputs/08_hashnode_publish.json` | `test_outputs/hashnode_publish_simulation_result.json` | **PASS** | `200 OK` | Extended Connector: Hashnode GraphQL |
| **09 Slack Publish** | `test_inputs/09_slack_publish.json` | `test_outputs/slack_publish_simulation_result.json` | **PASS** | `200 OK` | Extended Connector: Slack Block Kit |
| **10 Mailchimp Publish** | `test_inputs/10_mailchimp_publish.json` | `test_outputs/mailchimp_newsletter_simulation_result.json` | **PASS** | `200 OK` | Path 1: Mailchimp Newsletter |
| **11 Content Tailoring** | `test_inputs/11_tailoring_forum.json` | `test_outputs/tailoring_forum_discussion_result.json` | **PASS** | `200 OK` | Advanced Scope: Discussion prompt adaptation |
| **12 Relevance Scoring** | `test_inputs/12_relevance_scoring.json` | `test_outputs/audience_relevance_scoring_result.json` | **PASS** | `200 OK` | Advanced Scope: 1-5 Pillar relevance |
| **13 AI Rules Extraction** | `test_inputs/13_rules_propose.json` | `test_outputs/ai_rules_propose_result.json` | **PASS** | `200 OK` | Path 1: Guidelines to structured rules |
| **14 Destination Recommender** | `test_inputs/14_recommender.json` | `test_outputs/destination_recommendation_result.json` | **PASS** | `200 OK` | Path 1: Multi-factor ranking engine |

---

## 🛡️ 2. Negative & Failure Test Cases (Defensive Handling)

| Failure Scenario | Test File Reference | Error Code Returned | Expected HTTP Status | How System Handles It |
|---|---|---|---|---|
| **Link Policy Violation** | `tests/test_posting_rules.py::test_posting_rule_disallows_links` | `DEST_SPEC_VIOLATION` | `400 Bad Request` | Defensive pre-flight regex check rejects external URLs before hitting external platform. |
| **Weekly Cap Exceeded** | `tests/test_posting_rules.py::test_weekly_frequency_cap_with_injectable_clock` | `DEST_RULE_FREQUENCY_CAP` | `429 Too Many Requests` | In-memory timestamp window blocks 6th request with sliding 7-day rolling window. |
| **Idempotency Conflict** | `tests/test_safe_retries.py::test_idempotency_detects_conflicting_reuse` | `IDEMPOTENCY_CONFLICT` | `499/409 Conflict` | Hashed payload comparison detects same idempotency key with altered body and safely blocks duplicate. |
| **Auth Token Missing** | `tests/test_mailchimp_connector.py::test_mailchimp_real_missing_auth` | `CONNECTION_AUTH_EXPIRED` | `401 Unauthorized` | Validates required API key credentials before attempting outbound live network call. |
| **Unknown Destination** | `tests/test_certification.py::test_certify_non_existent_destination` | `NOT_FOUND` | `404 Not Found` | Gracefully reports unconfigured destination without unhandled exception. |

---

## 📊 3. Aggregated Execution Summary
- **Aggregated Batch Run:** `test_outputs/summary.json`
- **Total Tests:** 14
- **Passed:** 14 (100.0%)
- **Pytest Suite:** 172 passed in 10.07s
