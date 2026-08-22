# Legacy Firestore collections — cleanup inventory

**Status: inventory only. Nothing here has been deleted, and nothing should be
deleted on the strength of this document alone.**

Compiled 2026-08-22 while moving agent configuration into the control plane. The
question it answers is: *when `agent-service` is decommissioned, which Firestore
collections in `karosCMO` become dead, and which only look dead?*

Source of truth for the scan: the `col` maps in
`karosCMO/src/lib/data.ts` (48 collections) and
`karosCMO/src/lib/data-client-agents.ts` (3), plus `src/lib/data-analytics.ts`
and `src/services/logger.ts`.

Two structural facts shape everything below:

* **No code outside `data.ts` touches Firestore directly.** Not
  `src/lib/agent-service/**`, not the webhook route, not
  `agent-service/runner/src/**`. So "collections the legacy runner owns" is a
  much shorter list than the size of that subsystem suggests.
* **The legacy runner keeps no Firestore state of its own.** Its results are
  mirrored into the core `jobs` collection (with `agentId: "agent-service"`) by
  `src/app/api/agent-service/webhook/route.ts`. There is no run-trace or
  dispatch-bookkeeping collection to drop.

---

## A. Legacy execution plumbing

| Collection | Owner | In `deleteClientCascade`? |
|---|---|---|
| `customAgents` | `src/lib/actions/custom-agent-actions.ts`, imported from the lab manifest by `src/lib/agent-service/custom-agent-import.ts` | No — global registry, not client-scoped |
| `dynamicAgentSpecs` | `src/lib/actions/dynamic-agent-actions.ts`; frozen into a `specSnapshot` by `src/lib/jobs/submit-custom.ts` | No — **deliberately** excluded, documented at `data.ts:2696` ("a client delete must not cascade-delete a spec other clients still run") |

**Do not treat `customAgents` as disposable on its own.** Every X / LinkedIn /
Reddit surface in the portal is keyed off a row in it, and `Client.customAgentIds`
(a field, not a collection) references it. It dies only *after* those agents are
fully served by the control plane, not as part of turning the runner off.

---

## B. Per-agent intake and feedback state

All of these are already in `CLIENT_SCOPED_COLLECTIONS` (`data.ts:480-518`,
mirrored in `scripts/purge-orphaned-client-docs.ts`), so per-client deletion
already sweeps them.

**Shared:** `clientSeats`, `agentIntake`, `seatVoiceProfiles`

**X (e13):** `xNewsUpdates` (shared with LinkedIn despite the name — SCRUM-51),
`xTakes`, `xDraftFeedback`

**LinkedIn (e10):** `liDraftFeedback`, `liDirectionRequests`, `liAgentState`

**Reddit (e15):** `redditDraftFeedback`, `redditAgentState`

**The other four custom agents** (out of scope for the current migration, listed
so the inventory is complete): `newsletterDraftFeedback`, `newsletterAgentState`,
`newsletterLedger`, `blogAgentState`, `reputationAgentState`, `carouselAgentState`

> ### These are not caches
>
> The single most important finding in this document. Several `*AgentState`
> collections are **authorities**, not derived data:
>
> * `newsletterLedger` / `newsletterAgentState` — issue numbering
> * `blogAgentState` — the post index and subject-claim register
> * `reputationAgentState` — the no-repeat response ledger
> * `carouselAgentState` — the used/unused topic catalogue
>
> Wiping them does not cause a cold start. It causes **duplicate public output**:
> a re-used newsletter number, a second post on a claimed subject, a repeated
> reply to a reviewer. Any migration has to carry this state across or
> deliberately accept the duplicate, and that is a product decision.

---

## C. Core portal data — never wipe

`users`, `clients`, `jobs`, `assets`, `transcripts`, `accessTokens`,
`contextItems`, `clientReports`, `clientCompetitors`, `clientContextDocs`,
`clientActivityLogs`, `clientIntegrations`, `jiraConfig`, `clientRequests`,
`loginLogs`, `clientTasks`, `taskComments`, `clientSettings`, `feedbacks`,
`clientCredits`, `creditLedger`, `actionItems`, `scheduledRuns`, `clientSeoGeo`,
`clientMarketingAnalytics`, `clientFollowerSnapshots`, `clientActionStates`,
`campaigns`, `clientInsightsCache`, `plannedScheduledRuns`

Telemetry, on a 30-day purge via `src/app/api/cleanup-logs/route.ts`:
`usageLogs`, `errorLogs`, `analyticsSnapshot`

---

## D. Current architecture — in active use

* `agentEngineRuns` + its `steps` subcollection, and `agentEngineGates` — written
  by agent-engine, read by the portal via `src/lib/agent-engine/read-run.ts`
* `clientAgents`, `agentSlots`, `clientAgentFeedback` — the Phase-3 client-agent
  model (`src/lib/data-client-agents.ts`)
* `prompts`, `promptVersions`, `templates`, `templateVersions` — **this service.**
  They do not exist in `karosCMO` at all; nothing there reads or writes them.

---

## Open questions for a human

1. **`clientAgents` / `agentSlots` / `clientAgentFeedback` are missing from both
   `CLIENT_SCOPED_COLLECTIONS` and the `purge-orphaned-client-docs.ts` mirror.**
   They are client-scoped by deterministic doc id, so deleting a client currently
   orphans them. Unlike `dynamicAgentSpecs` — whose exclusion is documented and
   intentional — there is no comment explaining this one. It reads as a bug, not
   a decision, and it is a live data-hygiene issue independent of any migration.

2. **`scheduledRuns` vs `plannedScheduledRuns`.** Both feed the legacy dispatch
   path. Classified as C (portal scheduling data, per the comments at
   `data.ts:128` and `:193-195`), but if the whole legacy path is retired,
   `scheduledRuns` — the `/api/scheduler` recurring-generator record — may become
   dead. Needs someone who knows whether the new path reuses it.

3. **`_importPreflight`** appears only in `scripts/import-sitti-runway.ts:351`, a
   one-off client import. Not in any `col` map. Probably scratch data; unverified.

4. **`firestore.rules`' "Collections in use" comment block is badly stale** — it
   lists ~12 collections against the real 51, and names an `agents` collection
   that does not exist in code. Harmless (the rules themselves are deny-all) but
   actively misleading to the next reader.

## Suggested sequencing

1. Fix (1) — it is a real bug today, unrelated to the migration.
2. Migrate X / LinkedIn / Reddit onto control-plane agents; keep bucket B intact
   and read-only in parallel until the new path has produced real output.
3. Decide the bucket-B carry-over question above (duplicate-output risk) —
   product decision, not an engineering one.
4. Only then retire `customAgents` rows for the migrated agents.
5. Answer (2) before touching either scheduling collection.
