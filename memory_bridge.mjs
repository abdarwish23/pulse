// Optional: use an external JavaScript memory module instead of Pulse's built-in memory.
// Enable with "memory_backend": "bridge" and "memory_module": "/path/to/memory.mjs" in config.json.
// The module must export loadMemory(), remember(args), recall(query), updateFact(args) and forget(args).
// Usage: node memory_bridge.mjs <list|remember|recall|update|forget> <path to memory.mjs>  (JSON args on stdin)
import { pathToFileURL } from 'node:url';

const [op, modPath] = process.argv.slice(2);
if (!modPath) {
  process.stderr.write('memory module path required\n');
  process.exit(2);
}
const mem = await import(pathToFileURL(modPath).href);

let input = '';
for await (const chunk of process.stdin) input += chunk;
const args = input.trim() ? JSON.parse(input) : {};

const ops = {
  list: async () => ({ entities: await mem.loadMemory() }),
  remember: async () => ({ message: await mem.remember(args) }),
  recall: async () => ({ message: await mem.recall(args.query || '') }),
  update: async () => ({ message: await mem.updateFact(args) }),
  forget: async () => ({ message: await mem.forget(args) }),
};

if (!ops[op]) {
  process.stderr.write(`unknown op ${op}\n`);
  process.exit(2);
}
process.stdout.write(JSON.stringify(await ops[op]()));
