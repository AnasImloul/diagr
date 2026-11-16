(function () {
  // The playground page: a YAML editor, diagr running in a web worker (see playground/worker.js), and the player or
  // the static image of the last good build. The source lives in the URL, so a link reopens the same diagram.
  var CM = "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.21/";
  var PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
  var STORE = "diagr-playground";
  var SPLIT = "diagr-playground-split";
  var WAIT = 300;

  var worker = null;
  var workerState = "starting";

  function scheme() {
    return document.body.getAttribute("data-md-color-scheme") === "slate" ? "dark" : "light";
  }

  function load(tag, attrs) {
    return new Promise(function (resolve, reject) {
      var el = document.createElement(tag);
      Object.keys(attrs).forEach(function (k) {
        el.setAttribute(k, attrs[k]);
      });
      el.onload = resolve;
      el.onerror = reject;
      document.head.appendChild(el);
    });
  }

  function codemirror() {
    if (window.CodeMirror) return Promise.resolve(window.CodeMirror);
    return Promise.all([
      load("link", { rel: "stylesheet", href: CM + "codemirror.min.css" }),
      load("script", { src: CM + "codemirror.min.js" }),
    ])
      .then(function () {
        return load("script", { src: CM + "mode/yaml/yaml.min.js" });
      })
      .then(function () {
        return window.CodeMirror;
      });
  }

  function encode(text) {
    var stream = new Blob([text]).stream().pipeThrough(new CompressionStream("deflate-raw"));
    return new Response(stream).arrayBuffer().then(function (buf) {
      var bytes = new Uint8Array(buf);
      var bin = "";
      for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
      return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    });
  }

  function decode(code) {
    var bin = atob(code.replace(/-/g, "+").replace(/_/g, "/"));
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    var stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
    return new Response(stream).text();
  }

  // The hash holds the source and what the preview shows: #s=<source>&m=image&v=<view>&c=1, defaults left out.
  function fromHash() {
    var params = new URLSearchParams(location.hash.slice(1));
    var got = {
      mode: params.get("m") === "image" ? "image" : "player",
      view: params.get("v") || "",
      contrast: params.get("c") === "1",
    };
    var code = params.get("s");
    if (!code || !/^[A-Za-z0-9_-]+$/.test(code)) return Promise.resolve(got);
    return decode(code).then(
      function (text) { got.source = text; return got; },
      function () { return got; }
    );
  }

  function toHash(code, state) {
    var params = new URLSearchParams();
    params.set("s", code);
    if (state.mode !== "player") params.set("m", state.mode);
    if (state.view) params.set("v", state.view);
    if (state.contrast) params.set("c", "1");
    return "#" + params.toString();
  }

  function stored(key) {
    try {
      return localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function store(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (e) {}
  }

  function init() {
    var root = document.getElementById("dg-play");
    if (!root || root._dgBound) return;
    root._dgBound = true;

    var $ = function (id) { return document.getElementById(id); };
    var status = $("dg-play-status");
    var stage = $("dg-play-stage");
    var problemsList = $("dg-play-problems");
    var exampleSelect = $("dg-play-example");
    var viewSelect = $("dg-play-view");
    var contrastButton = $("dg-play-contrast");
    var modeButtons = root.querySelectorAll("[data-mode]");
    var textarea = $("dg-play-source");

    var state = { mode: "player", view: "", contrast: false };
    var editor = null;
    var marked = [];
    var timer = null;
    var seq = 0;
    var latest = 0;
    var busy = false;
    var queue = [];
    var shown = null;
    var pending = null;
    var keepPlace = true;
    var hashSeq = 0;
    var examples = [];

    function source() {
      return editor ? editor.getValue() : textarea.value;
    }

    function setSource(text) {
      if (editor) editor.setValue(text);
      else textarea.value = text;
    }

    function say(text, tone) {
      status.textContent = text;
      status.dataset.tone = tone || "";
    }

    // The worker takes one request at a time. A new build replaces a build still waiting; downloads wait their turn.
    function send(req) {
      req.id = ++seq;
      if (req.kind === "build") {
        latest = req.id;
        queue = queue.filter(function (q) { return q.kind !== "build"; });
      }
      queue.push(req);
      pump();
      return req.id;
    }

    function pump() {
      if (busy || workerState !== "ready" || !queue.length) return;
      busy = true;
      worker.postMessage(queue.shift());
    }

    var downloads = {};

    function onMessage(e) {
      var m = e.data;
      if (m.type === "status") return say(m.text);
      if (m.type === "ready") {
        workerState = "ready";
        say("Ready");
        pump();
        return;
      }
      if (m.type === "failed") {
        workerState = "failed";
        return say("Python did not start: " + m.text, "error");
      }
      busy = false;
      if (m.kind === "download") {
        var save = downloads[m.id];
        delete downloads[m.id];
        if (save) save(m.result);
      } else if (m.id === latest) {
        show(m.result, m.want, m.ms);
      }
      pump();
    }

    function startWorker() {
      if (worker) return;
      var url = new URL(root.dataset.worker, location.href);
      url.searchParams.set("pyodide", PYODIDE);
      worker = new Worker(url, { type: "module" });
      workerState = "starting";
    }

    function want() {
      return state.mode === "player" ? "html" : scheme();
    }

    // Encodings can finish out of order; only the latest one writes the address bar.
    function link(text) {
      var mine = ++hashSeq;
      return encode(text).then(function (code) {
        var url = location.href.split("#")[0] + toHash(code, state);
        if (mine === hashSeq) history.replaceState(null, "", url);
        return url;
      });
    }

    function build() {
      clearTimeout(timer);
      var text = source();
      store(STORE, text);
      link(text);
      if (workerState === "ready") say("Building");
      send({ kind: "build", source: text, want: want(), view: state.view, contrast: state.contrast });
    }

    function later() {
      clearTimeout(timer);
      timer = setTimeout(build, WAIT);
    }

    function problems(list) {
      marked.forEach(function (line) {
        if (editor) editor.removeLineClass(line, "background");
      });
      marked = [];
      problemsList.textContent = "";
      problemsList.hidden = !list.length;
      list.forEach(function (p) {
        var li = document.createElement("li");
        li.dataset.level = p.level;
        var where = document.createElement(p.line ? "button" : "span");
        where.className = "dg-play__where";
        where.textContent = p.line ? "Line " + p.line : p.level === "error" ? "Error" : "Warning";
        if (p.line) {
          where.type = "button";
          where.addEventListener("click", function () { jump(p.line, p.col); });
        }
        var text = document.createElement("span");
        text.textContent = p.message;
        li.append(where, text);
        problemsList.appendChild(li);
        if (p.line && editor) {
          var line = editor.getLineHandle(p.line - 1);
          if (line) {
            editor.addLineClass(line, "background", "dg-play__line--" + (p.level === "error" ? "error" : "warning"));
            marked.push(line);
          }
        }
      });
    }

    function jump(line, col) {
      if (editor) {
        editor.focus();
        editor.setCursor({ line: line - 1, ch: Math.max(0, (col || 1) - 1) });
        editor.scrollIntoView(null, 80);
        return;
      }
      var lines = textarea.value.split("\n");
      var at = lines.slice(0, line - 1).join("\n").length + (line > 1 ? 1 : 0) + Math.max(0, (col || 1) - 1);
      textarea.focus();
      textarea.setSelectionRange(at, at);
    }

    function show(r, kind, ms) {
      if (r.crash) {
        problems([{ level: "error", message: "diagr crashed: " + r.crash.trim().split("\n").pop() }]);
        console.error(r.crash);
        stage.classList.toggle("is-stale", !!shown);
        return say("diagr crashed, see the problems", "error");
      }
      var list = r.problems || [];
      problems(list);
      var errors = list.filter(function (p) { return p.level === "error"; }).length;
      var warnings = list.length - errors;
      if (r.out === undefined) {
        stage.classList.toggle("is-stale", !!shown);
        return say(errors + (errors === 1 ? " error" : " errors") + (shown ? ", showing the last good build" : ""), "error");
      }
      stage.classList.remove("is-stale");
      views(r.views, r.view);
      shown = { id: r.id, kind: kind };
      if (kind === "html") player(r.out);
      else image(r.out, kind);
      var note = warnings ? warnings + (warnings === 1 ? " warning" : " warnings") : "Built";
      say(note + " in " + Math.round(ms) + " ms", warnings ? "warning" : "");
    }

    function views(list, current) {
      var field = $("dg-play-view-field");
      field.hidden = list.length < 2;
      var keys = list.map(function (v) { return v.key + "\u0000" + v.title; }).join("\u0001");
      if (viewSelect.dataset.keys !== keys) {
        viewSelect.textContent = "";
        list.forEach(function (v) {
          var o = document.createElement("option");
          o.value = v.key;
          o.textContent = v.title;
          viewSelect.appendChild(o);
        });
        viewSelect.dataset.keys = keys;
      }
      viewSelect.value = current;
      state.view = current;
    }

    function dress(frame) {
      var doc = frame.contentDocument;
      if (!doc) return;
      var r = doc.documentElement;
      r.setAttribute("data-theme", scheme());
      if (state.contrast) r.setAttribute("data-contrast", "on");
      else r.removeAttribute("data-contrast");
      ["toggle", "contrast"].forEach(function (id) {
        var b = doc.getElementById(id);
        if (b) b.style.display = "none";
      });
    }

    // Where the reader is in the shown player: the scenario, the frame, whether it loops, the zoom and the scroll.
    function place() {
      var frame = stage.querySelector("iframe:not(.is-loading)");
      var win = frame && frame.contentWindow;
      if (!win) return null;
      var at = { y: win.scrollY };
      if (win.diagr) {
        at.scenario = win.diagr.scenario();
        at.frame = win.diagr.frame();
        at.looping = win.diagr.looping();
      }
      if (win.diagrZoom) at.zoom = win.diagrZoom.view();
      return at;
    }

    function restore(frame, at) {
      var win = frame.contentWindow;
      if (!at || !win) return;
      var d = win.diagr;
      if (d && at.scenario && d.scenarios.indexOf(at.scenario) >= 0) {
        d.scenario(at.scenario);
        d.seek(Math.min(at.frame, d.frames));
        if (at.looping) d.play();
      }
      if (win.diagrZoom && at.zoom) win.diagrZoom.view(at.zoom);
      win.scrollTo(0, at.y);
    }

    // The new preview loads behind the shown one and replaces it once drawn, so editing doesn't flash. A preview
    // still loading when a newer one arrives is dropped, so it can't land on top of the newer one.
    function swap(el) {
      if (pending) pending.remove();
      pending = el;
      stage.appendChild(el);
      hideEmpty();
    }

    function settle(el) {
      if (pending !== el) return;
      pending = null;
      stage.querySelectorAll("iframe, img").forEach(function (other) {
        if (other !== el) other.remove();
      });
    }

    function player(html) {
      var frame = document.createElement("iframe");
      frame.className = "dg-play__frame is-loading";
      frame.title = "Diagram preview";
      frame.addEventListener("load", function () {
        if (pending !== frame) return;
        dress(frame);
        restore(frame, keepPlace ? place() : null);
        keepPlace = true;
        frame.classList.remove("is-loading");
        settle(frame);
      }, { once: true });
      frame.srcdoc = html;
      swap(frame);
    }

    function image(svg, which) {
      var img = document.createElement("img");
      img.className = "dg-play__image is-loading";
      img.alt = "Diagram preview, " + which;
      var url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
      img.onload = img.onerror = function () {
        URL.revokeObjectURL(url);
        img.classList.remove("is-loading");
        settle(img);
      };
      img.src = url;
      swap(img);
    }

    function hideEmpty() {
      var empty = $("dg-play-empty");
      if (empty) empty.remove();
    }

    function download(which) {
      var id = send({ kind: "download", source: source(), want: which, view: state.view, contrast: state.contrast });
      downloads[id] = function (r) {
        if (r.crash) {
          console.error(r.crash);
          return say("diagr crashed while building the download, see the console", "error");
        }
        if (r.out === undefined) return say("Fix the errors to download", "error");
        var name = r.id + (which === "html" ? ".html" : "-" + which + ".svg");
        var type = which === "html" ? "text/html" : "image/svg+xml";
        var a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([r.out], { type: type }));
        a.download = name;
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
      };
    }

    function pick(text) {
      setSource(text);
      state.view = "";
      keepPlace = false;
      build();
    }

    function setMode(mode) {
      state.mode = mode;
      modeButtons.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.mode === mode)); });
    }

    function setContrast(on) {
      state.contrast = on;
      contrastButton.setAttribute("aria-pressed", String(on));
    }

    modeButtons.forEach(function (b) {
      b.addEventListener("click", function () {
        setMode(b.dataset.mode);
        build();
      });
    });

    contrastButton.addEventListener("click", function () {
      setContrast(!state.contrast);
      var frame = stage.querySelector("iframe:not(.is-loading)");
      if (state.mode === "player" && frame) {
        dress(frame);
        link(source());
      } else {
        build();
      }
    });

    viewSelect.addEventListener("change", function () {
      state.view = viewSelect.value;
      keepPlace = false;
      build();
    });

    exampleSelect.addEventListener("change", function () {
      var ex = examples[Number(exampleSelect.value)];
      if (ex) pick(ex.source);
      exampleSelect.value = "";
    });

    root.querySelectorAll("[data-download]").forEach(function (b) {
      b.addEventListener("click", function () { download(b.dataset.download); });
    });

    $("dg-play-share").addEventListener("click", function () {
      var button = this;
      link(source()).then(function (url) {
        return navigator.clipboard.writeText(url);
      }).then(function () {
        button.textContent = "Copied";
        setTimeout(function () { button.textContent = "Copy link"; }, 1600);
      }, function () {
        say("Couldn't copy: the link is in the address bar", "warning");
      });
    });

    new MutationObserver(function () {
      if (!root.isConnected) return;
      var frame = stage.querySelector("iframe:not(.is-loading)");
      if (state.mode === "player") {
        if (frame) dress(frame);
      } else {
        build();
      }
    }).observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });

    startWorker();
    worker.onmessage = onMessage;
    worker.onerror = function () {
      workerState = "failed";
      say("Python did not start in this browser", "error");
    };
    if (workerState === "ready") say("Ready");

    var examplesReady = fetch(new URL(root.dataset.examples, location.href))
      .then(function (r) { return r.json(); })
      .then(function (list) {
        examples = list;
        var none = document.createElement("option");
        none.value = "";
        none.textContent = "Choose an example";
        exampleSelect.appendChild(none);
        list.forEach(function (ex, i) {
          var o = document.createElement("option");
          o.value = String(i);
          o.textContent = ex.title;
          exampleSelect.appendChild(o);
        });
        exampleSelect.value = "";
        return list;
      })
      .catch(function () { return []; });

    // The split between the editor and the preview, as the editor's share of the width: drag the handle, or focus it
    // and use the arrow keys. A double-click puts it back.
    (function split() {
      var handle = $("dg-play-split");
      var panes = root.querySelector(".dg-play__panes");
      var START = 40;
      var MIN = 20;
      var MAX = 75;
      var dragging = false;

      function set(pct) {
        pct = Math.round(Math.min(MAX, Math.max(MIN, pct)) * 10) / 10;
        root.style.setProperty("--dg-play-split", pct + "%");
        handle.setAttribute("aria-valuenow", String(Math.round(pct)));
        return pct;
      }

      function done(pct) {
        store(SPLIT, String(pct));
        if (editor) editor.refresh();
      }

      var current = set(Number(stored(SPLIT)) || START);

      handle.addEventListener("pointerdown", function (e) {
        if (e.button !== 0) return;
        e.preventDefault();
        dragging = true;
        handle.setPointerCapture(e.pointerId);
        root.classList.add("is-resizing");
      });
      handle.addEventListener("pointermove", function (e) {
        if (!dragging) return;
        var box = panes.getBoundingClientRect();
        current = set(((e.clientX - box.left) / box.width) * 100);
      });
      ["pointerup", "pointercancel"].forEach(function (type) {
        handle.addEventListener(type, function () {
          if (!dragging) return;
          dragging = false;
          root.classList.remove("is-resizing");
          done(current);
        });
      });
      handle.addEventListener("dblclick", function () {
        current = set(START);
        done(current);
      });
      handle.addEventListener("keydown", function (e) {
        var moves = { ArrowLeft: current - 2, ArrowRight: current + 2, Home: MIN, End: MAX };
        if (!(e.key in moves)) return;
        e.preventDefault();
        current = set(moves[e.key]);
        done(current);
      });
    })();

    // Tab indents, so Escape then Tab is the way out of the editor for keyboard users.
    var leaving = false;

    var editorReady = codemirror().then(function (CodeMirror) {
      editor = CodeMirror.fromTextArea(textarea, {
        mode: "yaml",
        lineNumbers: true,
        indentUnit: 2,
        tabSize: 2,
        indentWithTabs: false,
        lineWrapping: false,
        screenReaderLabel: "Diagram YAML. Press Escape then Tab to leave the editor.",
        extraKeys: {
          Esc: function () { leaving = true; },
          Tab: function (cm) {
            if (cm.somethingSelected()) cm.indentSelection("add");
            else cm.replaceSelection("  ", "end");
          },
          "Shift-Tab": function (cm) { cm.indentSelection("subtract"); },
        },
      });
      editor.on("keydown", function (cm, e) {
        if (e.key === "Tab" && leaving) e.codemirrorIgnore = true;
        else if (e.key !== "Escape") leaving = false;
      });
      editor.on("blur", function () { leaving = false; });
      editor.on("change", later);
    }, function () {
      textarea.classList.add("is-plain");
      textarea.addEventListener("input", later);
    });

    Promise.all([fromHash(), examplesReady, editorReady]).then(function (got) {
      var linked = got[0];
      var text = linked.source || stored(STORE) || (got[1][0] && got[1][0].source) || "";
      if (linked.source) {
        setMode(linked.mode);
        setContrast(linked.contrast);
        state.view = linked.view;
      }
      setSource(text);
      if (editor) editor.clearHistory();
      build();
    });
  }

  // The playground fills the window under the header, whatever height the header has at this width.
  var header = document.querySelector(".md-header");
  if (header && window.ResizeObserver) {
    new ResizeObserver(function () {
      document.documentElement.style.setProperty("--dg-header-height", header.offsetHeight + "px");
    }).observe(header);
  }

  // Any other docs page fetches Python for the playground once the browser is idle, so the playground starts from the
  // browser's cache. jsDelivr lets browsers keep these files for a year: once they are cached these requests are
  // answered from disk without reaching the network, and if the cache was cleared they download them again. A visitor
  // saving data or on a slow connection is left alone.
  function warm() {
    if (document.getElementById("dg-play")) return;
    var net = navigator.connection;
    if (net && (net.saveData || /2g/.test(net.effectiveType || ""))) return;
    var get = function (name) {
      return fetch(PYODIDE + name, { priority: "low" }).then(function (r) {
        if (!r.ok) throw new Error(name + ": " + r.status);
        return r;
      });
    };
    get("pyodide-lock.json")
      .then(function (r) { return r.json(); })
      .then(function (lock) {
        var files = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip"];
        files.push(lock.packages.pyyaml.file_name);
        return Promise.all(files.map(function (name) {
          return get(name).then(function (r) { return r.arrayBuffer(); });
        }));
      })
      .catch(function () {});
  }

  function whenIdle() {
    if (window.requestIdleCallback) requestIdleCallback(warm, { timeout: 5000 });
    else setTimeout(warm, 2000);
  }

  if (document.readyState === "complete") whenIdle();
  else window.addEventListener("load", whenIdle, { once: true });

  init();
  if (window.document$ && typeof window.document$.subscribe === "function") window.document$.subscribe(init);
})();
