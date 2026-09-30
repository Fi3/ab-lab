// Dedicated inherited pipes carry tool RPC; assistant prose and Pi's RPC stdin
// are never parsed as host operations.
import { createReadStream, readFileSync, writeSync } from 'node:fs';
import { createInterface } from 'node:readline';

export function registerHostTools(pi) {
  const definitions = process.env.AGENT_LAB_PI_HOST_TOOLS;
  if (!definitions) return;
  const pending = new Map();
  const input = createReadStream(null, {
    fd: Number(process.env.AGENT_LAB_PI_HOST_RESPONSE_FD), autoClose: false,
  });
  const lines = createInterface({ input });
  const rejectAll = error => {
    for (const request of pending.values()) request.reject(error);
    pending.clear();
  };
  lines.on('line', line => {
    try {
      const response = JSON.parse(line);
      const request = pending.get(response.callId);
      if (!request) return;
      pending.delete(response.callId);
      if (typeof response.success !== 'boolean' || typeof response.text !== 'string') {
        request.reject(new Error('Invalid host tool response'));
      } else request.resolve(response);
    } catch (error) { rejectAll(error); }
  });
  input.on('error', rejectAll);
  lines.on('close', () => rejectAll(new Error('Host tool bridge closed')));

  for (const tool of JSON.parse(readFileSync(definitions, 'utf8'))) {
    pi.registerTool({
      name: tool.name, label: tool.name, description: tool.description,
      parameters: tool.inputSchema, executionMode: 'sequential',
      async execute(callId, args, signal) {
        if (signal?.aborted) throw new Error('aborted');
        if (pending.has(callId)) throw new Error('Duplicate pending host tool call');
        const policy = JSON.parse(readFileSync(process.env.AGENT_LAB_PI_POLICY, 'utf8'));
        const request = {
          type: 'lab_host_tool_call', threadId: process.env.AGENT_LAB_PI_HOST_THREAD_ID,
          turnId: policy.turn_id, callId, tool: tool.name, arguments: args,
        };
        let stop;
        try {
          const response = await new Promise((resolve, reject) => {
            pending.set(callId, { resolve, reject });
            stop = () => {
              pending.delete(callId);
              reject(new Error('aborted'));
            };
            signal?.addEventListener('abort', stop, { once: true });
            const bytes = Buffer.from(JSON.stringify(request) + '\n');
            let offset = 0;
            try {
              while (offset < bytes.length) offset += writeSync(
                Number(process.env.AGENT_LAB_PI_HOST_REQUEST_FD), bytes, offset, bytes.length - offset);
            } catch (error) {
              pending.delete(callId);
              reject(error);
            }
          });
          if (!response.success) throw new Error(response.text);
          return { content: [{ type: 'text', text: response.text }], details: { callId } };
        } finally {
          if (stop) signal?.removeEventListener('abort', stop);
        }
      },
    });
  }
}
