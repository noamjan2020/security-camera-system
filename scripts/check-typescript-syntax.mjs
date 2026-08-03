import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

async function loadTypeScript() {
  try {
    return await import("typescript");
  } catch {
    const root = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
    return await import(pathToFileURL(join(root, "typescript", "lib", "typescript.js")).href);
  }
}

function walk(directory) {
  const files = [];
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    const info = statSync(path);
    if (info.isDirectory()) files.push(...walk(path));
    else if (path.endsWith(".ts")) files.push(path);
  }
  return files;
}

const root = resolve(new URL("..", import.meta.url).pathname);
const ts = await loadTypeScript();
const files = [
  ...walk(join(root, "backend", "signaling-server", "src")),
  ...walk(join(root, "backend", "supabase", "functions")),
];
let failed = false;
for (const file of files) {
  const source = readFileSync(file, "utf8");
  const sourceFile = ts.createSourceFile(
    file,
    source,
    ts.ScriptTarget.ES2022,
    true,
    ts.ScriptKind.TS,
  );
  for (const diagnostic of sourceFile.parseDiagnostics ?? []) {
    if (diagnostic.category !== ts.DiagnosticCategory.Error) continue;
    failed = true;
    const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n");
    const position = diagnostic.start == null ? "" : `:${source.slice(0, diagnostic.start).split("\n").length}`;
    console.error(`${relative(root, file)}${position}: ${message}`);
  }
}
if (failed) process.exit(1);
console.log(`TypeScript syntax checks passed: ${files.length} files`);
