// Runs diagr itself in the browser: Pyodide (CPython on WebAssembly) with PyYAML, and the diagr package the docs
// build zips next to this file. One request at a time; the page only sends the latest edit. The page names the
// Pyodide release to load (?pyodide=), as it also fetches it ahead of time from the other docs pages.
const PYODIDE = new URL(import.meta.url).searchParams.get("pyodide");

async function start() {
  const { loadPyodide } = await import(PYODIDE + "pyodide.mjs");
  const py = await loadPyodide({ indexURL: PYODIDE });
  postMessage({ type: "status", text: "Loading diagr" });
  const get = async (name, as) => {
    const r = await fetch(new URL(name, import.meta.url));
    if (!r.ok) throw new Error(`${name}: ${r.status}`);
    return r[as]();
  };
  const [, zip, bridge] = await Promise.all([
    py.loadPackage("pyyaml", { messageCallback: () => {} }),
    get("diagr.zip", "arrayBuffer"),
    get("play.py", "text"),
  ]);
  py.unpackArchive(zip, "zip", { extractDir: "/lib/play" });
  py.FS.writeFile("/lib/play/play.py", bridge);
  py.runPython("import sys; sys.path.insert(0, '/lib/play')");
  const play = py.pyimport("play");
  play.build("id: warm\nnodes:\n  a: {}\n", "light");
  return play;
}

const ready = start();

ready.then(
  () => postMessage({ type: "ready" }),
  (e) => postMessage({ type: "failed", text: String((e && e.message) || e) })
);

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
