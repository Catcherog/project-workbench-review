"""Trace acceptance requirements to executed tests, without claiming live UAT."""
from pathlib import Path
import json
T=Path(__file__).resolve().parents[1]
tests=json.loads((T/'evidence/final-anchor-focused.json').read_text())['tests']
mapping={
 'RACE-01':['test_change_in_final_recipient_lookup_must_block[source]'],
 'RACE-02':['test_change_in_final_recipient_lookup_must_block[acl]','test_change_in_final_recipient_lookup_must_block[disclosure]'],
 'RACE-03':['test_unrelated_source_change_during_final_lookup_still_sends'],
 'RACE-04':['test_concurrent_writer_cannot_commit_between_check_and_send_boundary'],
 'READ-01':['test_final_private_directory_read_failure_is_blocked_and_reviewable'],
 'READ-02':['test_guard_exit_failure_after_sending_commit_remains_unknown','test_process_interruption_in_local_check_keeps_crash_recovery_evidence'],
 'ADOPT-01':['test_nested_import_types_are_rejected_before_native_state','test_adoption_rollback_after_item_insert_and_idempotent_recovery'],
 'ADOPT-02':['test_adoption_rollback_after_item_insert_and_idempotent_recovery'],
 'SCHED-01':['test_claim_recovery_does_not_starve_unrelated_occurrence','test_uncertain_prior_round_does_not_starve_unrelated_occurrence'],
 'REC-01':['test_recovery_bridges_already_verified_native_receipt'],
 'REC-02':['test_local_result_retry_uses_backoff_and_never_rereads_platform','test_historical_verified_result_converges_after_expiry_with_sending_disabled','test_reconcile_callback_failure_is_retried_after_native_verified'],
 'REC-03':['test_native_verified_mapping_mismatch_never_releases_unknown'],
 'SRC-01':['test_native_source_review_invalidates_old_card_and_is_idempotent','test_reviewed_new_source_can_resume_same_item_without_old_approval'],
 'SRC-02':['test_review_while_claimed_releases_only_proven_unsent_barrier'],
 'SRC-03':['test_source_review_preserves_unknown_and_cross_channel_barrier'],
 'SRC-04':['test_source_changes_after_review_preview_require_new_review','test_review_card_queued_before_revocation_is_not_delivered','test_review_card_cannot_rebind_stale_body_to_new_access_epoch'],
 'GAP-01':['test_failed_coverage_persists_review_gap_and_publishes_no_partial_facts','test_owner_private_info_route_exposes_gaps_but_rejects_group_and_nonowner'],
 'GAP-02':['test_read_to_outbox_acl_epoch_cannot_be_rebound_after_revocation','test_review_view_never_resurrects_expired_or_old_version_raw_text'],
 'DM-03':['test_current_private_reply_survives_expired_old_greeting'],
 'DM-04':['test_current_reply_readback_mismatch_never_records_feedback'],
 'DM-05':['test_substantive_exact_reply_is_visible_as_unverified_feedback','test_reply_association_and_feedback_roll_back_together'],
 'DM-06':['test_report_raw_text_expires_without_leaking_into_permanent_results','test_review_card_and_outbox_expire_with_earliest_source_raw'],
}
rows=[]
for requirement,names in mapping.items():
 matches=[]
 for name in names:
  found=[key for key,value in tests.items() if name in key]
  assert found,(requirement,name)
  assert all(tests[key]['status']=='passed' for key in found)
  matches+=found
 rows.append({'requirement':requirement,'tests':sorted(set(matches)),'status':'passed_original_macOS_real_SQLite_simulated_platform','real_platform_fault_acceptance':False})
(T/'evidence/checklist-test-coverage.json').write_text(json.dumps({'requirements':rows,'overlapping_tests_not_additive':True},indent=2)+'\n')
print('Mapped',len(rows),'requirements to passing executed cases')
