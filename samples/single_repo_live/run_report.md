# Run Report

## Input
- repo: https://github.com/pallets/click
- mode: live
- input_mode: direct
- timestamp: 20260708_062704

## Preflight
- status: PROCEED
- reason: 정상 진행

## Collector Status
- metadata: OK
- readme: OK
- issues: OK
- prs: OK
- file_tree: OK
- dependency: OK

## Issue Sampler
- sampled_issue_count: 8
- sample_max_chars: 1500
- template_sections_compressed: YES
- defect_count: 5
- feature_request_count: 6
- workflow_pain_count: 5
- confusion_count: 4
- noise_count: 1
- uncertain_count: 1

## Comments Signal
- high_comment_issue_count: 3
- unique_commenters_available: YES
- bike_shedding_possible_count: 0

## LLM Key Pool
- provider: google_genai_gemma
- model: gemma-4-31b-it
- configured_key_count: 11
- loaded_key_count: 11
- strategy: round_robin
- used_key_indexes: [1, 2, 3, 4, 5, 6]
- disabled_key_indexes: []
- temp_failed_key_indexes: [1]
- retry_count: 1
- failover_count: 1
- retry_backoff_strategy: exponential_jitter
- retry_initial_delay_seconds: 2.0
- retry_max_delay_seconds: 60.0
- request_timeout_seconds: 180.0
- respect_retry_after: True

## Missing Data
- (없음)

## Errors
- (없음)

## JSON Validation
PASS

## Content Gate
PASS

## Length Truncation
- length_truncated: NO
- truncated_field_count: 0
- truncated_fields: (없음)

## Judge Raw
- raw_verdict: KEEP
- raw_score: 8

## Validator Final
- final_verdict: KEEP
- final_score: 8

## Ceiling Rules
- applied: (없음)
- corrected: NO
- correction_reason: (없음)
- before_score: 8
- after_score: 8
- before_verdict: KEEP
- after_verdict: KEEP

## Secret Redaction
PASS

## Token/API Key Exposure
NO

## Output Files
- debug/raw/metadata.json
- debug/raw/readme.md
- debug/raw/issues.json
- debug/raw/prs.json
- debug/raw/file_tree.json
- debug/raw/dependency_evidence.json
- debug/evidence_packet.md
- debug/prompts/bouncer.md
- debug/worker_outputs/bouncer.json
- debug/prompts/readme_scout.md
- debug/worker_outputs/readme_scout.json
- debug/prompts/pain_scout.md
- debug/worker_outputs/pain_scout.json
- debug/prompts/structure_risk_scout.md
- debug/worker_outputs/structure_risk_scout.json
- debug/prompts/critic_judge.md
- debug/worker_outputs/critic_judge_raw.json
- debug/judge_output_raw.json
- debug/worker_outputs/critic_judge_final.json
- debug/judge_output_final.json
- idea_card.md
