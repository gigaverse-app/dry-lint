# Dryer versus native TF-IDF on gigaverse-backend

Keep **TF-IDF as the default** and use Dryer as an optional additional source. At the measured defaults, Dryer
adds 23 unique backlog pairs but misses 234 TF-IDF backlog pairs, and takes about 5.3 times as long to scan.
These are unjudged candidate counts. They do not measure true-duplicate recall.

## Method and provenance

Measured on 3 November 2026, Windows 11, Python 3.14.7, on one developer machine:

- Backend snapshot: `22dfbe180c6704101658a088cc269a25fa9c82dd`, in a clean detached worktree.
- Recent-change base: `9d5314c54bb3e7e15c825e8eac44e6960ab42d9d` (`HEAD~40`, 40 first-parent steps, not 40 individual PR tests).
- Native baseline: dry-lint main `13fabc5a8f318e3279c42a4a75c32872e01c3c40`.
- Plugin implementation: `4b522230303dc4f7ffa3aeee8beced42fa4623f0`.
- Dryer: `66ff6d21a42c04afcad89c78a80066176d1294b0`; tree-sitter 0.26.0; tree-sitter-language-pack 1.23.1.
- Canonical corpus: **5,505 functions in 510 tracked Python files**. The default dry-lint exclusions remove
  `*/tests/*`, `tests/*`, `*/migrations/*`, `*/scripts/*`. These are glob rules, not a semantic production-code filter;
  for example, top-level `perf/` functions are included. There are 297 touched functions since the base.
- Corpus SHA-256: `2e925b7e110be478b906196014b21484fd50f565d07e480e5dc82f087b41fe5a`.
- Same extracted functions, cross-file neighbour budget (3), suppressions and mutual-nearest scan policy.
  TF-IDF uses its existing 0.5/0.3 floors; Dryer uses upstream defaults 0.82, four lines, 20 nodes.
  **4,283 functions pass Dryer's size gates.** Different size gates and floors are part of this default-configuration
  comparison; this is not a controlled accuracy comparison at matched recall or a standalone Dryer CLI benchmark.
- Three repetitions, alternating detector order; no judge, network judgement, source execution or backend deployment.
  Whole-file upstream extraction matched the adapter for every canonical function span. The grammar was already
  downloaded before timing. Source extraction happened once (0.699 s), outside per-detector timings.
- Independently ran unmodified dry-lint main against the same snapshot: all 247 scan pairs, 106 changed-function
  pairs and their scores exactly match the refactored TF-IDF source.

Use [the reproduction command](detectors.md#reproduce-the-backend-comparison). The harness writes private raw
candidate JSON, individual timing runs, versions, settings and the corpus hash outside the repository.
These timings measure this local implementation on this checkout; they are not universal performance claims.

## Candidate volume and overlap

Counts are review workload, with no inherently better direction.

| Workload | Native TF-IDF | Dryer | Shared | TF-IDF only | Dryer only | Union |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Whole-repository mutual-nearest backlog | 247 | 36 | 13 | 234 | 23 | 270 |
| Changed-function candidates since base | 106 | 5 | 3 | 103 | 2 | 108 |
| Changed-function pairs skipped by shared rules | 104 | 1 | n/a | n/a | n/a | n/a |

The union would add 9.3% more backlog candidates to TF-IDF, or 1.9% more changed-function candidates.
These are set unions for analysis; the CLI selects one source per invocation and does not implement an ensemble.
All three runs returned identical pairs for each detector.

## Time

Seconds, lower is better. Median over three repetitions; ranges show observed minimum and maximum.
A real invocation also pays source extraction and interpreter startup. The scan row excludes index construction.

| Operation | TF-IDF median (range) | Dryer median (range) |
| --- | ---: | ---: |
| Build fingerprints/index | 1.053 (1.013-1.168) | 2.221 (2.107-2.269) |
| Propose candidates for 297 touched functions | 0.530 (0.490-0.547) | 2.378 (2.188-2.433) |
| Scan the full backlog | 6.902 (6.359-7.029) | 36.584 (35.188-38.386) |

Dryer compares eligible fingerprint sets per query, with an exact set-size upper-bound filter; TF-IDF uses an
inverted index. Neither requires a model. The integration intentionally reuses upstream normalization and
`jaccard` rather than introducing a separately maintained structural algorithm.

## Exploratory source review

One assistant reviewed 12 random source-exclusive backlog pairs per detector, sampled with Python's
`random.Random(20261103)` from each returned list. The review was **unblinded, small and not independently
adjudicated**. It is a qualitative audit, not a validated precision estimate or a recall measurement.
The categories use the consolidation guideline in [benchmark.md](benchmark.md#labelling-guideline).

| Sample | Plausible consolidation | Separate concepts or intentional patterns | Needs domain decision |
| --- | ---: | ---: | ---: |
| 12 TF-IDF-only pairs | 3 | 8 | 1 |
| 12 Dryer-only pairs | 1 | 11 | 0 |

Useful differences:

- **TF-IDF-only:** `_is_newer` in `core/shared/swr_cache.py` and `_is_newer_stampede_value` in
  `perf/instrumentation/diag.py` make the same timestamp-freshness decision. Another pair attaches assets to clips
  using different algorithms and different empty-clip policies; their shared association step is worth reviewing.
- **Dryer-only:** `User.set_profile_picture` and `CommunityEvent.set_thumbnail` share the lifecycle of soft-deleting
  previous media, replacing a relation and saving. Their changed vocabulary hides this pairing from native scan.
- **Dryer noise:** unrelated abstract methods both raising `NotImplementedError`, and simple `.filter(...).exists()`
  queries, can have identical normalized structure. Matching those shapes does not imply a common domain concept.
- **TF-IDF noise:** different provider-SID setters, dependency providers and cache-key constructors can share
  vocabulary despite separate responsibilities. Both redaction wrappers already call a shared replacement primitive.

The verdict judge is still necessary. No backend code was changed as part of this experiment.

### Reviewed sample ledger

Names below identify functions in the frozen backend snapshot; the raw local review also records full paths.
`consolidate` means a plausible shared implementation or shared fragment, not approval to refactor immediately.

| Source | Pair | Assessment | Reason |
| --- | --- | --- | --- |
| tfidf | `format_event_time_with_timezone` / `_format_event_date` | separate | Distinct presentation wrappers; clock formatting is already shared. |
| tfidf | `attach_clip_assets` / `PastEventService.group_assets_by_clips` | consolidate | Both attach assets by clip ID; query loading and empty-clip policy can stay at callers. |
| tfidf | `work_options_v1` / `durable_work_constraints` | separate | Historical migration schema must stay independent of evolving runtime constraints. |
| tfidf | `BulkEntryOutcome.is_success` / `DurableWorkCapability.on_success` | separate | Success predicate versus an optional lifecycle hook. |
| tfidf | `redact_oauth_secrets` / `redact_active_secrets` | separate | Both already delegate replacement to strip_secret_values; input discovery differs. |
| tfidf | `CommunityBaseSerializer._access_service` / `resolve_community_service` | pattern | Separate dependency providers for different service types. |
| tfidf | `_live_room_missing_marker` / `_live_room_confirmation_in_flight_marker` | separate | Different cache identities and lifecycles. |
| tfidf | `_is_newer` / `_is_newer_stampede_value` | consolidate | Identical timestamp freshness decision. |
| tfidf | `VCalendarService._get_community_event_url` / `URLShortenerService._parse_to_event_url` | uncertain | Both build event links but use different destinations and identity contracts; needs product intent. |
| tfidf | `OobCode.set_verification_sid` / `RoomsService._set_room_sid` | pattern | Persist different provider identifiers on different domain objects. |
| tfidf | `GetStreamActivityFeedPort.list_feed_members` / `CommunityService.community_feed_members` | separate | Abstract port versus membership conversion implementation. |
| tfidf | `CommunityMembershipCapability._emit_leave_metrics` / `CommunityMembershipView.delete` | consolidate | Repeated membership-leave metric emission can share an owner while callers retain orchestration. |
| dryer | `User.get_profile_picture_url` / `CommunityEvent.get_thumbnail` | pattern | Simple URL getters for distinct media relations. |
| dryer | `phone_auth_velocity_window_seconds` / `_sms_pumping_block_score` | pattern | Both already use the typed feature-flag reader for different policy values. |
| dryer | `UserService.unset_device` / `CommunityService.remove_event_participant` | separate | Ownership-guarded device deletion versus event participation removal. |
| dryer | `PaymentsService.list_discount_coupon` / `RoomsService.get_community_rooms` | pattern | Simple queries over different domain models. |
| dryer | `UserService.sanitize_bio` / `CommunityService.sanitize_community_data` | pattern | Independent tasks use the same on-commit scheduling convention. |
| dryer | `GetStreamClient.getstream_user_exists` / `CommunityService.is_member` | separate | Provider identity existence versus community membership existence. |
| dryer | `User.set_profile_picture` / `CommunityEvent.set_thumbnail` | consolidate | Same replace-media-and-soft-delete-previous lifecycle, with the relation as variation. |
| dryer | `AuthenticationService.get_accounts` / `GetStreamClientPort.find_identity_collision_user_ids` | separate | Abstract methods with unrelated contracts. |
| dryer | `CommunityEvent.is_ended` / `Room.is_pre_live` | separate | Different state predicates over different domains. |
| dryer | `GetStreamActivityFeedPort.remove_manager_membership_level_from_member` / `TwilioClientPort.send_verify_auth_sms` | separate | Abstract methods with unrelated contracts. |
| dryer | `GetStreamActivityFeedPort.create_post_activity_feed_item` / `GetStreamClientPort.mute_community_chat_member` | separate | Abstract methods with unrelated contracts. |
| dryer | `CommunityEvent.set_notification_sent` / `StripeAccount.set_rejected` | pattern | Simple state setters on distinct models. |

## Practical choice

Use TF-IDF for the ordinary PR workflow. Use `--detector dryer --judge none` for a separate structural pass when
additional renamed-shape candidates justify the scan cost, then judge them before acting. Keep the score scales
separate. Lowering Dryer's floor or changing shared neighbour policy would require a new measurement; this
comparison does not tune either detector or claim one finds every duplicate.
