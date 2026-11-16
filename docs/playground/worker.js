// Runs diagr itself in the browser: Pyodide (CPython on WebAssembly) with PyYAML, and the diagr package the docs
// build zips next to this file. One request at a time; the page only sends the latest edit.
//
// The page names the Pyodide release (?pyodide=) and where in Cache Storage a memory snapshot of Python is kept, taken
// once diagr is imported (?cache=, ?snapshot=). Starting from the snapshot skips most of Python's start-up; without
// one, Python starts in full and the snapshot is taken for next time. With ?job=snapshot the worker only takes it.
const params = new URL(import.meta.url).searchParams;
const PYODIDE = params.get("pyodide");
const CACHE = params.get("cache");
const SNAPSHOT = self.caches && CACHE ? params.get("snapshot") : null;
const JOB = params.get("job");

// PyYAML is unpacked from its wheel: loadPackage leaves state behind that a snapshot can't hold. Its C extension is
// left out, so YAML is parsed in Python, as diagr's safe_load does anyway.
const SETUP = `
import glob, os, sys
for f in glob.glob("/lib/play/yaml/_yaml*.so"):
    os.remove(f)
sys.path.insert(0, "/lib/play")
import yaml, play
play.build("id: warm\\nnodes:\\n  a: {}\\n", "html")
`;

async function get(url, as) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r[as]();
}

async function saved() {
  if (!SNAPSHOT) return null;
  const hit = await (await caches.open(CACHE)).match(SNAPSHOT);
  if (!hit) return null;
  return new Uint8Array(await new Response(hit.body.pipeThrough(new DecompressionStream("gzip"))).arrayBuffer());
}

// Compressed in full before it is stored, so the entry never exists half written; older snapshots go once it's in.
async function keep(snapshot) {
  const zipped = await new Response(new Blob([snapshot]).stream().pipeThrough(new CompressionStream("gzip"))).blob();
  const cache = await caches.open(CACHE);
  await cache.put(SNAPSHOT, new Response(zipped));
  for (const old of await cache.keys()) if (old.url !== SNAPSHOT) await cache.delete(old);
}

async function forget() {
  await (await caches.open(CACHE)).delete(SNAPSHOT);
}

// The snapshot holds Python's memory but not its files, so diagr's files are unpacked again after a restore.
function install(py, [zip, bridge]) {
  py.unpackArchive(zip, "zip", { extractDir: "/lib/play" });
  py.FS.writeFile("/lib/play/play.py", bridge);
}

async function start() {
  const pyodide = import(PYODIDE + "pyodide.mjs");
  const diagr = Promise.all([
    get(new URL("diagr.zip", import.meta.url), "arrayBuffer"),
    get(new URL("play.py", import.meta.url), "text"),
  ]);
  const snapshot = saved().catch(() => null);
  const { loadPyodide } = await pyodide;

  const from = await snapshot;
  if (from && JOB) return null;
  if (from) {
    try {
      const py = await loadPyodide({ indexURL: PYODIDE, _loadSnapshot: from });
      install(py, await diagr);
      return py.pyimport("play");
    } catch (e) {
      await forget().catch(() => {});
    }
  }

  const wheel = get(PYODIDE + "pyodide-lock.json", "json").then((lock) =>
    get(PYODIDE + lock.packages.pyyaml.file_name, "arrayBuffer")
  );
  const py = await loadPyodide({ indexURL: PYODIDE, _makeSnapshot: !!SNAPSHOT });
  py.unpackArchive(await wheel, "zip", { extractDir: "/lib/play" });
  install(py, await diagr);
  py.runPython(SETUP);
  // Taken before anything on this side holds a Python object, which a snapshot can't hold either.
  const stored = SNAPSHOT ? keep(py.makeMemorySnapshot()) : Promise.resolve();
  if (JOB) {
    await stored;
    return null;
  }
  stored.catch(() => {});
  return py.pyimport("play");
}

const ready = start();

if (JOB) {
  ready.finally(() => {
    postMessage({ type: "done" });
    close();
  });
} else {
  ready.then(
    () => postMessage({ type: "ready" }),
    (e) => postMessage({ type: "failed", text: String((e && e.message) || e) })
  );
}

onmessage = async (e) => {
  const m = e.data;
  const play = await ready;
  const started = performance.now();
  let result;
  try {
    result = JSON.parse(play.build(m.source, m.want, m.view || "", !!m.contrast));
  } catch (err) {
    result = { crash: String((err && err.message) || err) };
  }
  postMessage({ type: "result", id: m.id, kind: m.kind, want: m.want, ms: performance.now() - started, result });
};
