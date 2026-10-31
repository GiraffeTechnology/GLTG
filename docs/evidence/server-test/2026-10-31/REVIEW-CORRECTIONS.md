# Historical evidence corrections

This additive note qualifies three unresolved review findings in PR #29. It
preserves the original 2026-10-16 evidence and its manifest; it does not rewrite
raw results, rerun old checks or upgrade component evidence to delivery.

1. **Aggregate target cleanup is unknown.** The last historical target attempt
   ended with transport exit 255 and no remote cleanup result or proof that
   execution never began. Earlier successful cleanup records cannot certify
   that attempt. Do not rely on the historical aggregate `true` value.
2. **Committed-source identity differs from the recorded runtime digest.**
   Hashing the 90 tracked `src` blobs at candidate `61092e0` with the documented
   path/NUL/bytes algorithm produces
   `d2f5c7d111253398efb619336506f0dd5a9b48bd93ee463d6cfcc26d3ad10d52`.
   This is a static committed-byte identity, not a claim that those exact bytes
   were executed. The old `a06d2c6f...` runtime digest remains unreconciled; do
   not replace it in an old test result and thereby imply a new verification.
3. **The published dependency-audit claim is not independently verifiable.**
   Its command/exit, tool/database state and report digest are absent from the
   published evidence chain. Treat it as an unverified historical report,
   not a completed security check or an audit of the target server.

`review-corrections.json` provides the exact affected claims, statuses and
source references. For these claims it takes precedence over the unqualified
historical summary. The original test counts and individual attempt results
remain preserved with their original scope and limitations. No product tests,
target access, cleanup, database actions, merge or deployment were performed
to produce this correction. Required future checks must run only in the
authorized environment; no local or Windows product tests were run.
