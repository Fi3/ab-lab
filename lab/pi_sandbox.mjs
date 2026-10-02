// Keep Pi's native tool definitions/results; change only execution permissions.
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { resolve } from 'node:path';
import { registerHostTools } from './pi_host_tools.mjs';
import { installRequestGuard } from './pi_usage.mjs';

async function executeBash(policy, request, signal, onUpdate) {
  const sdk = await import(process.env.AGENT_LAB_PI_MODULE);
  const shell = sdk.getShellConfig();
  const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
  // Only the command belongs inside the sandbox. Pi's native output capture
  // must be able to persist truncated output without granting the command writes.
  const tool = sdk.createBashToolDefinition(process.cwd(), {
    spawnHook: context => ({ ...context,
      command: 'exec ' + [...policy.shell_argv, shell.shell, ...shell.args, context.command].map(quote).join(' '),
    }),
  });
  const abort = new AbortController();
  const stop = () => abort.abort();
  signal?.addEventListener('abort', stop, { once: true });
  if (signal?.aborted) stop();
  const timer = setTimeout(stop, Math.max(0, Math.min(2147483647, policy.deadline * 1000 - Date.now())));
  const context = request.context && { ...request.context, sessionManager: {
    getSessionId: () => request.context.sessionId, getSessionFile: () => request.context.sessionFile,
  } };
  try {
    return await tool.execute(request.id, request.params, abort.signal, onUpdate, context);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', stop);
  }
}

export async function execute(policy, request, signal, onUpdate) {
  if (signal?.aborted) throw new Error('aborted');
  if (Date.now() >= policy.deadline * 1000) throw new Error('workflow deadline reached');
  if (request.name === 'bash') return executeBash(policy, request, signal, onUpdate);
  return new Promise((resolve, reject) => {
    const child = spawn(policy.argv[0], policy.argv.slice(1), {
      cwd: process.cwd(), env: process.env, detached: true, stdio: ['pipe', 'pipe', 'pipe'],
    });
    let result, error, stderr = '', killTimer;
    const kill = (sig) => { try { process.kill(-child.pid, sig); } catch {} };
    const stop = () => {
      error = 'aborted or workflow deadline reached';
      kill('SIGTERM');
      killTimer ??= setTimeout(() => kill('SIGKILL'), 2000);
    };
    const timer = setTimeout(stop, Math.min(2147483647, policy.deadline * 1000 - Date.now()));
    signal?.addEventListener('abort', stop, { once: true });
    const lines = createInterface({ input: child.stdout });
    lines.on('line', line => {
      try {
        const event = JSON.parse(line);
        if (event.type === 'update') onUpdate?.(event.value);
        else if (event.type === 'result') result = event.value;
        else if (event.type === 'error') error = event.value;
        else error = 'invalid sandbox tool response';
      } catch { error = 'invalid sandbox tool response'; }
    });
    child.stderr.on('data', data => { stderr = (stderr + data.toString()).slice(-8192); });
    child.on('error', value => { error = value.message; });
    child.stdin.on('error', value => { error = value.message; });
    child.on('close', code => {
      clearTimeout(timer);
      clearTimeout(killTimer);
      signal?.removeEventListener('abort', stop);
      lines.close();
      if (error || code !== 0 || result === undefined) reject(new Error(error || stderr || `sandbox tool failed (exit ${code}, missing result)`));
      else resolve(result);
    });
    child.stdin.end(JSON.stringify(request));
  });
}

export function compactionPolicy(sdk, ctx, requested) {
  if (typeof sdk.SettingsManager?.create !== 'function') {
    throw new Error('installed Pi SDK cannot inspect native compaction settings');
  }
  const window = ctx.model?.contextWindow;
  if (!Number.isSafeInteger(requested) || requested <= 0 || !Number.isSafeInteger(window) || requested >= window) {
    throw new Error('compaction_tokens must be a positive integer below the model context window');
  }
  const manager = sdk.SettingsManager.create(ctx.cwd, process.env.PI_CODING_AGENT_DIR,
    { projectTrusted: ctx.isProjectTrusted() });
  if (typeof manager.getCompactionSettings !== 'function') {
    throw new Error('installed Pi SDK cannot inspect native compaction settings');
  }
  const settings = manager.getCompactionSettings(ctx.model);
  const effective = window - settings.reserveTokens;
  if (settings.enabled !== true || effective !== requested) {
    throw new Error('effective Pi compaction settings conflict with compaction_tokens (including project/model overrides)');
  }
  return { mode: 'harness-native', control: 'pi-native-settings-v1', enabled: true,
    requested_tokens: requested, auto_compact_tokens: effective,
    model_context_window: window, reserve_tokens: settings.reserveTokens };
}

export default async function (pi) {
  const sdk = await import(process.env.AGENT_LAB_PI_MODULE);
  const native = JSON.parse(readFileSync(process.env.AGENT_LAB_PI_POLICY, 'utf8')).native_process === true;
  const hostTools = process.env.AGENT_LAB_PI_HOST_TOOLS
    ? JSON.parse(readFileSync(process.env.AGENT_LAB_PI_HOST_TOOLS, 'utf8')).map(tool => tool.name) : [];
  const selectTools = () => {
    // The CLI allowlist retains all role tools; only this policy selects which
    // ones are exposed to the next model request.
    const policy = JSON.parse(readFileSync(process.env.AGENT_LAB_PI_POLICY, 'utf8'));
    if (native) return;
    pi.setActiveTools(['read', 'bash', ...(policy.writable ? ['edit', 'write'] : []), ...hostTools]);
  };
  for (const kind of native ? [] : ['Read', 'Bash', 'Edit', 'Write']) {
    const tool = sdk['create' + kind + 'ToolDefinition'](process.cwd());
    pi.registerTool({ ...tool, execute(id, params, signal, onUpdate, ctx) {
      const policy = JSON.parse(readFileSync(process.env.AGENT_LAB_PI_POLICY, 'utf8'));
      const context = { cwd: ctx.cwd, model: ctx.model, thinkingLevel: ctx.thinkingLevel,
        sessionId: ctx.sessionManager.getSessionId(), sessionFile: ctx.sessionManager.getSessionFile() };
      const run = () => execute(policy, { name: tool.name, id, params, context }, signal, onUpdate);
      return ['edit', 'write'].includes(tool.name)
        ? sdk.withFileMutationQueue(resolve(ctx.cwd, params.path), run) : run();
    } });
  }
  registerHostTools(pi);
  pi.on('before_agent_start', selectTools);
  // The lab never uses Pi's interactive !command path. It must not provide a
  // second, unsandboxed execution route through RPC.
  if (!native) pi.on('user_bash', () => { throw new Error('Use the sandboxed bash tool'); });
  pi.on('session_start', (_event, ctx) => {
    selectTools();
    installRequestGuard(ctx.modelRegistry.runtime, process.env.AGENT_LAB_PI_POLICY,
      process.env.AGENT_LAB_PI_REQUEST_JOURNAL, process.env.AGENT_LAB_PI_THREAD_ID);
    const context = {};
    if (process.env.AGENT_LAB_PI_COMPACTION_TOKENS !== undefined) {
      try {
        context.context_policy = compactionPolicy(sdk, ctx, Number(process.env.AGENT_LAB_PI_COMPACTION_TOKENS));
      } catch (error) {
        context.context_error = error.message;
      }
    }
    writeFileSync(process.env.AGENT_LAB_PI_POLICY + '.ready', JSON.stringify({
      pid: process.pid, nonce: process.env.AGENT_LAB_PI_NONCE, request_guard: 'pre-dispatch-v1',
      ...context,
      tools: pi.getAllTools().map(tool => ({name: tool.name, description: tool.description})),
    }));
  });
}
