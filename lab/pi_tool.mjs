// Execute the installed Pi tool unchanged, already inside the OS sandbox.
import { readFileSync, writeSync } from 'node:fs';

const abort = new AbortController();
process.on('SIGTERM', () => abort.abort());
process.on('SIGINT', () => abort.abort());
// Direct fd writes reliably deliver output on both socket-backed stdio and
// pipes, including when running inside a restricted sandbox.
const emit = (type, value) => {
  const bytes = Buffer.from(JSON.stringify({ type, value }) + '\n');
  let offset = 0;
  while (offset < bytes.length) offset += writeSync(1, bytes, offset, bytes.length-offset);
};
try {
  const sdk = await import(process.env.AGENT_LAB_PI_MODULE);
  const request = JSON.parse(readFileSync(0, 'utf8'));
  const kind = ['Read', 'Bash', 'Edit', 'Write'].find(kind => kind.toLowerCase() === request.name);
  const tool = kind && sdk['create' + kind + 'ToolDefinition'](process.cwd());
  if (!tool) throw new Error('Unknown Pi native tool');
  const context = request.context && { ...request.context, sessionManager: {
    getSessionId: () => request.context.sessionId, getSessionFile: () => request.context.sessionFile,
  } };
  emit('result', await tool.execute(request.id, request.params, abort.signal, value => emit('update', value), context));
} catch (error) {
  emit('error', String(error.message ?? error));
}
