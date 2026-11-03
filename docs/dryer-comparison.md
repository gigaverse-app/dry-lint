# Dryer versus native TF-IDF on gigaverse-backend

Keep **TF-IDF as the default** and use Dryer as an optional additional source. At the measured defaults, Dryer
adds 17 unique backlog pairs but misses 389 TF-IDF backlog pairs, and takes about 7.9 times as long to scan.
These are unjudged candidate counts. They do not measure true-duplicate recall.

## Method and provenance

Measured on 3 November 2026, Windows 11, Python 3.14.7, on one developer machine:

- Backend snapshot: `22dfbe180c6704101658a088cc269a25fa9c82dd`, in a clean detached worktree.
- Recent-change base: `9d5314c54bb3e7e15c825e8eac44e6960ab42d9d` (`HEAD~40`, 40 first-parent steps, not 40 individual PR tests).
- Native baseline: dry-lint main `ab54f0baca999fce05448f3555ad422659a92b82`.
- Plugin implementation: `599d0e9767e32eac42641746613ac9aa5837c638`.
- Dryer: `66ff6d21a42c04afcad89c78a80066176d1294b0`; tree-sitter 0.26.0; tree-sitter-language-pack 1.23.1.
- Canonical corpus: **5,057 functions in 501 tracked Python files**. The default dry-lint exclusions remove
  `*/tests/*`, `tests/*`, `*/migrations/*`, `*/scripts/*`. Include is `*`, with the Python extractor selecting `*.py`. These are glob rules, not a semantic production-code filter;
  for example, top-level `perf/` functions are included. There are 295 touched functions since the base.
- Corpus SHA-256: `edb5a12c18cd3008ab2c7b6672cef90aa35c3f52efe8028a345b4bd9660a0efb`.
- Main PRs #1, #3 and #4 are included, including the comparer plugin framework and Action changes: declaration-only stubs are omitted, same-file neighbours are excluded before limiting,
  and delegation rules inspect AST calls. Both sources use these shared fixes.
- Same extracted functions, cross-file neighbour budget (3), suppressions and mutual-nearest scan policy.
  TF-IDF uses its existing 0.5/0.3 floors; Dryer uses upstream defaults 0.82, four lines, 20 nodes.
  **4,164 functions pass Dryer's size gates.** Different size gates and floors are part of this default-configuration
  comparison; this is not a controlled accuracy comparison at matched recall or a standalone Dryer CLI benchmark.
- Three repetitions, alternating detector order; no judge, network judgement, source execution or backend deployment.
  Whole-file upstream extraction matched the adapter for every canonical function span. The grammar was already
  downloaded before timing. Source extraction and behavior tokenization happened once (1.611 s), outside per-comparer timings.
- Independently ran unmodified dry-lint main against the same snapshot: all 420 scan pairs, 149 changed-function
  pairs and their scores exactly match the refactored TF-IDF source.

Use [the reproduction command](detectors.md#reproduce-the-backend-comparison). The harness writes private raw
candidate JSON, individual timing runs, versions, settings and the corpus hash outside the repository.
These timings measure this local implementation on this checkout; they are not universal performance claims.

## Candidate volume and overlap

Counts are review workload, with no inherently better direction.

| Workload | Native TF-IDF | Dryer | Shared | TF-IDF only | Dryer only | Union |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Whole-repository mutual-nearest backlog | 420 | 48 | 31 | 389 | 17 | 437 |
| Changed-function candidates since base | 149 | 4 | 3 | 146 | 1 | 150 |
| Changed-function pairs skipped by shared rules | 44 | 1 | n/a | n/a | n/a | n/a |

The union would add 4.0% more backlog candidates to TF-IDF, or 0.7% more changed-function candidates.
These are set unions for analysis; the CLI selects one source per invocation and does not implement an ensemble.
All three runs returned identical pairs for each detector.

## Time

Seconds, lower is better. Median over three repetitions; ranges show observed minimum and maximum.
A real invocation also pays source extraction and interpreter startup. The scan row excludes index construction.

| Operation | TF-IDF median (range) | Dryer median (range) |
| --- | ---: | ---: |
| Build comparer index from extracted functions | 0.180 (0.131-0.189) | 2.536 (2.106-2.971) |
| Propose candidates for 295 touched functions | 0.633 (0.552-0.719) | 3.070 (2.657-4.479) |
| Scan the full backlog | 6.015 (5.291-8.558) | 47.770 (47.360-48.193) |

Dryer compares eligible fingerprint sets per query, with an exact set-size upper-bound filter; TF-IDF uses an
inverted index. Neither requires a model. The integration intentionally reuses upstream normalization and
`jaccard` rather than introducing a separately maintained structural algorithm.

## Exploratory source review

One assistant reviewed all 17 Dryer-exclusive backlog pairs and 12 random TF-IDF-exclusive pairs, sampled with
Python's `random.Random(20261103)` from the returned list. The review was **unblinded and not independently
adjudicated**. Different review population sizes mean these counts are not a head-to-head accuracy estimate.
They are a qualitative audit, not a validated precision estimate or a recall measurement. Categories follow
[the consolidation guideline](benchmark.md#labelling-guideline).

| Reviewed population | Plausible consolidation | Separate concepts or intentional patterns | Needs domain decision |
| --- | ---: | ---: | ---: |
| 12 randomly sampled TF-IDF-only pairs | 1 | 10 | 1 |
| All 17 Dryer-only pairs | 2 | 15 | 0 |

Useful differences:

- **Dryer-only:** `User.set_profile_picture` and `CommunityEvent.set_thumbnail` share the lifecycle of soft-deleting
  previous media, replacing a relation and saving. Their changed vocabulary hides this pairing from native scan.
- **Dryer-only:** `community_join_request` and `community_join_request_approved` build and validate exactly the same
  `CommunityJoinRequestData`; only the task passed to `_run_on_commit` differs. The payload construction could share
  an owner while delivery stays separate.
- **TF-IDF-only sample:** client cleanup and stage-lock cleanup both retain unfinished tasks and register completion
  callbacks. This shared ownership fragment is worth inspecting, while cancellation policy stays at each caller.
- **Dryer noise:** unrelated model setters, feature-flag accessors and simple `.filter(...).exists()` queries can
  have identical normalized structure. `False` and `None` literals normalize away, so unrelated predicates can
  also score 1. Matching these shapes does not imply one domain concept.
- **TF-IDF noise:** implementations and test doubles share vocabulary, as do reading and writing related domain
  objects. Metric aggregation and downstream metric emission are separate steps despite their shared field names.

The verdict judge is still necessary. No backend code was changed as part of this experiment.

### Reviewed sample ledger

Names identify functions in the frozen backend snapshot; the raw local review also records full paths.
`consolidate` means a plausible shared implementation or fragment, not approval to refactor immediately.

| Source | Pair | Assessment | Reason |
| --- | --- | --- | --- |
| tfidf | `DurableWorkCapability.classify_error` / `ImageRenditionGeneration.classify_error` | separate | Default error policy versus a specialized override. |
| tfidf | `LiveKitRoomClient.aget_room_egress_by_egress_id` / `LiveKitRoomMockClient.aget_room_egress_by_egress_id` | separate | Real async client method versus a test double. |
| tfidf | `format_event_time_with_timezone` / `_format_event_date` | separate | Distinct presentation wrappers already share clock formatting. |
| tfidf | `CommunityChatMuteMemberView.post` / `StreamChatMuteParticipantView.post` | uncertain | Community and stream chat moderation share orchestration but access policies and provider targets differ. |
| tfidf | `UserProfileSerializer.get_terms_and_policy_accepted` / `TermsAndPolicyService.accept_terms` | separate | Read current acceptance versus create a new acceptance row. |
| tfidf | `EventTicket.set_payment_intent_id` / `StripeClient.get_payment_intent` | separate | Persist an identifier versus retrieve a remote payment object. |
| tfidf | `CommunityRTMPSettingView.delete` / `StreamRTMPStreamingView.delete` | separate | Delete RTMP configuration versus disable active streaming; same HTTP scaffold. |
| tfidf | `CampaignPrometheus.create` / `PrometheusEmailSignalSink.create` | pattern | Same registry-selection convention for different collector families. |
| tfidf | `CommunityEvent.is_ended` / `ActiveRoomSerializer.get_ended_at` | separate | Status predicate versus timestamp serialization. |
| tfidf | `_cancel_or_own_client_cleanup` / `_own_stage_lock_cleanup` | consolidate | Shared retention and completion handling for background cleanup tasks; cancellation remains caller policy. |
| tfidf | `LiveStreamStorageService._get_stream_metrics` / `StreamsMetricsManager.track_participants_metrics` | separate | Metric aggregation versus downstream metric emission. |
| tfidf | `PaymentsService.create` / `StripePaymentsWebhookClient.create` | pattern | Factories construct distinct service types. |
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
