// A cancelled native tool batch can make Pi enter another model turn. Prove
// that this request never reached the provider instead of pricing an empty
// SDK error message as if it were a completed model response.
import { randomUUID } from 'node:crypto';
import { closeSync, fsyncSync, openSync, readFileSync, writeSync } from 'node:fs';
import { dirname } from 'node:path';

export const NO_DISPATCH_PREFIX = 'Lab request not dispatched: ';

export function installRequestGuard(runtime, policyPath, journalPath, threadId) {
  if (!runtime || typeof runtime.prepareRequest !== 'function') {
    throw new Error('Pi request accounting guard cannot be installed');
  }
  const prepare = runtime.prepareRequest;
  runtime.prepareRequest = async function (model, options) {
    if (!options?.signal?.aborted) return prepare.call(this, model, options);
    const policy = JSON.parse(readFileSync(policyPath, 'utf8'));
    if (typeof policy.turn_id !== 'string' || !policy.turn_id) {
      throw new Error('Cancelled Pi request has no owned turn');
    }
    const receipt = { type: 'request_not_dispatched', receipt_id: randomUUID(),
      thread_id: threadId, turn_id: policy.turn_id, provider: model.provider,
      model: model.id, api: model.api, reason: 'already_aborted_before_prepare' };
    const fd = openSync(journalPath, 'a', 0o600);
    try {
      const bytes = Buffer.from(JSON.stringify(receipt) + '\n');
      let offset = 0;
      while (offset < bytes.length) offset += writeSync(fd, bytes, offset, bytes.length - offset);
      fsyncSync(fd);
    } finally { closeSync(fd); }
    const directory = openSync(dirname(journalPath), 'r');
    try { fsyncSync(directory); } finally { closeSync(directory); }
    // The underlying authentication/preparation and provider stream are never
    // invoked on this branch. The native lazy stream carries this receipt ID
    // into its synthetic error, without adding anything to the model prompt.
    throw new Error(NO_DISPATCH_PREFIX + receipt.receipt_id);
  };
}
