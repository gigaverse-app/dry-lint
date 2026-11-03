# Dryer versus native TF-IDF on gigaverse-backend

Keep **TF-IDF as the default** and use Dryer as an optional additional source. At the measured defaults, Dryer
adds 19 unique backlog pairs but does not return 383 TF-IDF backlog pairs. The size-bucket optimization below
cuts Dryer's median scan time by 40% while retaining every pair, score and tie order; TF-IDF remains faster.
These are unjudged candidate counts. They do not measure true-duplicate recall.

## Initial comparison: method and provenance

Measured on 3 November 2026, Windows 11, Python 3.14.7, on one developer machine:

- Backend snapshot: `22dfbe180c6704101658a088cc269a25fa9c82dd`, in a clean detached worktree.
- Recent-change base: `9d5314c54bb3e7e15c825e8eac44e6960ab42d9d` (`HEAD~40`, 40 first-parent steps, not 40 individual PR tests).
- Native baseline: dry-lint main `104933be3582fb26de87ccb15e1c84929b5d523a`.
- Plugin implementation: `10698b1374b9aea17e28e714cc8e280929f270b9` (timed source; later CI-only integration does not alter these workloads).
- Dryer: `66ff6d21a42c04afcad89c78a80066176d1294b0`; tree-sitter 0.26.0; tree-sitter-language-pack 1.23.1.
- Canonical corpus: **5,057 functions in 501 tracked Python files**. The default dry-lint exclusions remove
  `*/tests/*`, `tests/*`, `*/migrations/*`, `*/scripts/*`. Include is `*`, with the Python extractor selecting `*.py`. These are glob rules, not a semantic production-code filter;
  for example, top-level `perf/` functions are included. There are 295 touched functions since the base.
- Corpus SHA-256: `edb5a12c18cd3008ab2c7b6672cef90aa35c3f52efe8028a345b4bd9660a0efb`.
- Includes main's comparer plugin framework and recall fixes: declaration-only stubs are omitted, same-file neighbours are excluded before limiting,
  and delegation rules inspect AST calls. Native TF-IDF version 2 also includes field/key identities, removes annotation noise and splits acronym boundaries (PR #6).
- Same extracted functions, cross-file neighbour budget (3), suppressions and mutual-nearest scan policy.
  TF-IDF uses its existing 0.5/0.3 floors; Dryer uses upstream defaults 0.82, four lines, 20 nodes.
  **4,164 functions pass Dryer's size gates.** Different size gates and floors are part of this default-configuration
  comparison; this is not a controlled accuracy comparison at matched recall or a standalone Dryer CLI benchmark.
- Three repetitions, alternating detector order; no judge, network judgement, source execution or backend deployment.
  Whole-file upstream extraction matched the adapter for every canonical function span. The grammar was already
  downloaded before timing. Source extraction and behavior tokenization happened once (1.695 s), outside per-comparer timings.
- Independently ran unmodified dry-lint main against the same snapshot: all 412 scan pairs, 139 changed-function
  pairs and their scores exactly match the refactored TF-IDF source.

Use [the reproduction command](detectors.md#reproduce-the-backend-comparison). The harness writes private raw
candidate JSON, individual timing runs, versions, settings and the corpus hash outside the repository.
These timings measure this local implementation on this checkout; they are not universal performance claims.
The developer machine was not isolated from other work; the observed timing ranges matter.

## Candidate volume and overlap

Counts are review workload, with no inherently better direction.

| Workload | Native TF-IDF | Dryer | Shared | TF-IDF only | Dryer only | Union |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Whole-repository mutual-nearest backlog | 412 | 48 | 29 | 383 | 19 | 431 |
| Changed-function candidates since base | 139 | 4 | 3 | 136 | 1 | 140 |
| Changed-function pairs skipped by shared rules | 35 | 1 | n/a | n/a | n/a | n/a |

The union would add 4.6% more backlog candidates to TF-IDF, or 0.7% more changed-function candidates.
These are set unions for analysis; the CLI selects one source per invocation and does not implement an ensemble.
All three runs returned identical pairs for each detector.

## Initial timings

Seconds, lower is better. Median over three repetitions; ranges show observed minimum and maximum.
A real invocation also pays source extraction and interpreter startup. The scan row excludes index construction.

| Operation | TF-IDF median (range) | Dryer median (range) |
| --- | ---: | ---: |
| Build comparer index from extracted functions | 0.143 (0.138-0.146) | 2.245 (2.040-2.385) |
| Propose candidates for 295 touched functions | 0.458 (0.395-0.480) | 3.048 (2.583-3.595) |
| Scan the full backlog | 4.381 (4.328-5.435) | 45.026 (39.730-50.390) |

Dryer compares eligible fingerprint sets per query, with an exact set-size upper-bound filter; TF-IDF uses an
inverted index. Neither requires a model. The integration intentionally reuses upstream normalization and
`jaccard` rather than introducing a separately maintained structural algorithm.

## Follow-up: prune size buckets before visiting functions

The initial adapter looked up every function and checked its size for every query. The optimized adapter groups
eligible functions by fingerprint count during indexing. The same exact Jaccard upper bound now skips entire
impossible buckets before visiting functions. The upstream scoring function and all thresholds are unchanged;
source positions explicitly preserve tie order after traversal changes.

Measured again on the same frozen backend, Python and dependency versions on 3 November 2026. The baseline
adapter is from `6d67e48aa6b7c7ac72eefbc01735abe522fa0f17`; the optimized adapter is from
`8ca0e0c`. Both ran in the same interpreter over one extracted corpus and the same shared pipeline. Three
repetitions alternated before/after order, with TF-IDF also measured. The grammar cache was warm and no judge
was called. This developer machine was not isolated from other work, so treat the ranges as part of the result.

| Operation | Dryer before median (range), seconds | Dryer after median (range), seconds | TF-IDF median (range), seconds |
| --- | ---: | ---: | ---: |
| Build index | 2.076 (2.054-3.256) | 2.389 (2.150-2.467) | 0.169 (0.147-0.175) |
| Query 295 touched functions | 2.654 (2.586-4.029) | 1.608 (1.457-1.816) | 0.568 (0.422-0.653) |
| Full scan | 42.562 (41.240-45.899) | 25.505 (19.908-29.053) | 6.167 (4.805-6.385) |

Dryer's median scan improved **40.1%** and changed-function query time improved **39.4%**. Median index time
increased by 0.313 seconds. Source extraction and interpreter startup are excluded from these rows. This is a
speed improvement, not a change in duplicate detection quality: every repetition asserted identical ordered
pair keys and scores, including all **48 scan pairs** and **4 changed-function pairs**. TF-IDF still returned
412 and 139 respectively. An exhaustive upstream-score test also covers four thresholds, filtered neighbours,
reindexing and tied scores.

For separate-checkout reproductions, run [the comparison harness](detectors.md#reproduce-the-backend-comparison)
from the baseline and optimized revisions against the same backend snapshot. Preserve both output directories;
compare ordered pair keys and scores as well as timings. The local alternating-run evidence includes each run's
timings and full candidate JSON; private source is not checked into this repository.

## Exploratory source review

One assistant reviewed all 19 Dryer-exclusive backlog pairs and 12 random TF-IDF-exclusive pairs, sampled with
Python's `random.Random(20261103)` from the returned list. The review was **unblinded and not independently
adjudicated**. Different review population sizes mean these counts are not a head-to-head accuracy estimate.
They are a qualitative audit, not a validated precision estimate or a recall measurement. Categories follow
[the consolidation guideline](benchmark.md#labelling-guideline).

| Reviewed population | Plausible consolidation | Separate concepts or intentional patterns | Needs domain decision |
| --- | ---: | ---: | ---: |
| 12 randomly sampled TF-IDF-only pairs | 2 | 9 | 1 |
| All 19 Dryer-only pairs | 2 | 17 | 0 |

Useful differences:

- **Dryer-only:** `User.set_profile_picture` and `CommunityEvent.set_thumbnail` share the lifecycle of soft-deleting
  previous media, replacing a relation and saving. Their changed vocabulary hides this pairing from native scan.
- **Dryer-only:** `community_join_request` and `community_join_request_approved` build and validate exactly the same
  `CommunityJoinRequestData`; only the task passed to `_run_on_commit` differs. The payload construction could share
  an owner while delivery stays separate.
- **TF-IDF-only sample:** the serializer and admin repeat exactly the same profile-completeness predicate.
  Pending and denied join-request tasks also repeat community payload construction and bulk-insert orchestration.
- **Dryer noise:** unrelated model setters, feature-flag accessors and simple `.filter(...).exists()` queries can
  have identical normalized structure. `False` and `None` literals normalize away, so unrelated predicates can
  also score 1. Matching these shapes does not imply one domain concept.
- **TF-IDF noise:** real clients and test doubles share vocabulary, as do independent model setters and service
  wrappers. Attempt admission and completion deliberately differ in lease requirements despite their shared fencing fields.

The verdict judge is still necessary. No backend code was changed as part of this experiment.

### Reviewed sample ledger

Names identify functions in the frozen backend snapshot; the raw local review also records full paths.
`consolidate` means a plausible shared implementation or fragment, not approval to refactor immediately.

| Source | Pair | Assessment | Reason |
| --- | --- | --- | --- |
| tfidf | `CommunityService.sanitize_community_data` / `RoomsService.sanitize_stream_data` | pattern | Small post-commit wrappers schedule different domain tasks under the same local-environment guard. |
| tfidf | `LiveKitRoomClient.aget_room_egress_by_egress_id` / `LiveKitRoomMockClient.aget_room_egress_by_egress_id` | separate | Real async client method versus a test double. |
| tfidf | `LiveKitRoomClient.aget_rtmp_room_egress` / `LiveKitRoomMockClient.aget_rtmp_room_egress` | separate | Async remote-client wrapper versus a test double returning an empty RoomEgress. |
| tfidf | `CommunityService.check_community_language_code` / `validate_community_language` | pattern | Predicate and validating adapter both use the canonical LANGUAGE_CODES setting; the membership operation is trivial. |
| tfidf | `record_effect_attempt` / `complete_work` | separate | Attempt admission requires an unexpired lease and records evidence; settlement accepts a current fence and finalizes work. Their lock predicates intentionally differ. |
| tfidf | `LiveCommunityShowcaseService.page_access` / `ShowcaseService.list_showcases` | uncertain | Membership and invitation batching overlap, but active-user and room-membership restrictions differ; confirm the access contract before sharing a loader. |
| tfidf | `UserProfileSerializer.get_profile_filled` / `UsersAdmin.profile_filled` | consolidate | Identical profile-completeness policy over the same User fields is repeated in the serializer and admin. |
| tfidf | `CommunityJoinRequestNotificationService.community_join_request_task` / `CommunityJoinRequestDeniedNotificationService.community_join_request_denied_task` | consolidate | Same per-user community notification payload and bulk-insert workflow; notification kind and delivery text can be parameters. |
| tfidf | `install_community_membership_service` / `install_registrations` | pattern | Thin wrappers already reuse Installed.install for different dependency slots. |
| tfidf | `GetStreamUserEntity.set_token` / `Room.set_link_token` | pattern | Persisting a provider authentication token and a room invite token are independent domain operations. |
| tfidf | `CommunityNewMembersView.get_queryset` / `StreamRoomsListView.get_queryset` | separate | Distinct membership and room query adapters use different not-found behavior and domain queries. |
| tfidf | `CommunityScheduledEventCapability.cancel_event` / `Command._remove_foreign` | separate | Product durable cancellation and calendar-provider harness cleanup invoke different deletion contracts. |
| dryer | `User.email_notifications_enabled` / `ImageBase.is_deleted` | separate | Different policy predicates, with False and None having different meanings. |
| dryer | `User.set_profile_picture` / `CommunityEvent.set_thumbnail` | consolidate | Same replace-media-and-soft-delete-previous lifecycle, with the relation as variation. |
| dryer | `User.get_profile_picture_url` / `CommunityEvent.get_thumbnail` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |
| dryer | `User.set_sanitized_bio` / `OobCode.set_verification_sid` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |
| dryer | `phone_auth_velocity_window_seconds` / `_sms_pumping_block_score` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |
| dryer | `UsersSearchQuerySerializer.create` / `ChangeInviteAudienceModeBodySerializer.create` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |
| dryer | `UserService.unset_device` / `CommunityService.remove_event_participant` | separate | Ownership-guarded device deletion versus event participation removal. |
| dryer | `UserService.sanitize_bio` / `CommunityService.sanitize_community_data` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |
| dryer | `CommunityEvent.set_notification_sent` / `StripeAccount.set_rejected` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |
| dryer | `CommunityEvent.set_email_notification_sent` / `RoomEgress.set_finished` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |
| dryer | `CommunityEvent.is_ended` / `Room.is_pre_live` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |
| dryer | `CommunityUserIdsSerializer.create` / `CheckoutSessionUrlQuerySerializer.create` | pattern | Serializer mapping idiom over distinct domain fields; normalized field names erase the independent payload contracts. |
| dryer | `CommunityJoinRequestQuerySerializer.create` / `RoomInviteQuerySerializer.create` | pattern | Serializer mapping idiom over distinct domain fields; normalized field names erase the independent payload contracts. |
| dryer | `settings_send_gate_on` / `shopify_reauth_recovery_enabled` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |
| dryer | `CommunityJoinRequestNotificationService.community_join_request` / `CommunityJoinRequestApprovedNotificationService.community_join_request_approved` | consolidate | Identical CommunityJoinRequestData construction and validation; only the scheduled task differs. |
| dryer | `EventTicket.set_paid` / `ImageBase.set_deleted` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |
| dryer | `PaymentsService.list_discount_coupon` / `RoomsService.get_community_rooms` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |
| dryer | `GetStreamClient.getstream_user_exists` / `CommunityService.is_member` | separate | Provider identity existence versus community membership existence. |
| dryer | `Command.add_arguments` / `Command.add_arguments` | pattern | Independent domain getters, setters, queries, flags, command arguments or task scheduling using a common idiom. |

## Practical choice

Use TF-IDF for the ordinary PR workflow. Use `--detector dryer --judge none` for a separate structural pass when
additional renamed-shape candidates justify the scan cost, then judge them before acting. Keep the score scales
separate. Lowering Dryer's floor or changing shared neighbour policy would require a new measurement; this
comparison does not tune either detector or claim one finds every duplicate.
