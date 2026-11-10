(function () {
  // The playground page: a YAML editor, diagr running in a web worker (see playground/worker.js), and the player or
  // the static image of the last good build. The source lives in the URL, so a link reopens the same diagram.
  var CM = "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.21/";
  var STORE = "diagr-playground";
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

  function fromHash() {
    var m = /[#&]s=([A-Za-z0-9_-]+)/.exec(location.hash);
    return m ? decode(m[1]).catch(function () { return null; }) : Promise.resolve(null);
  }

  function stored() {
    try {
      return localStorage.getItem(STORE);
    } catch (e) {
      return null;
    }
  }

  function store(text) {
    try {
      localStorage.setItem(STORE, text);
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
      worker = new Worker(new URL(root.dataset.worker, location.href), { type: "module" });
      workerState = "starting";
    }

    function want() {
      return state.mode === "player" ? "html" : scheme();
    }

    function build() {
      clearTimeout(timer);
      var text = source();
      store(text);
      encode(text).then(function (code) {
        history.replaceState(null, "", "#s=" + code);
      });
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

    // A new frame loads behind the old one and replaces it once drawn, so editing doesn't flash.
    function player(html) {
      var old = stage.querySelector("iframe, img");
      var frame = document.createElement("iframe");
      frame.className = "dg-play__frame is-loading";
      frame.title = "Diagram preview";
      frame.addEventListener("load", function () {
        dress(frame);
        frame.classList.remove("is-loading");
        stage.querySelectorAll("iframe, img").forEach(function (el) {
          if (el !== frame) el.remove();
        });
      }, { once: true });
      frame.srcdoc = html;
      stage.appendChild(frame);
      if (!old) hideEmpty();
    }

    function image(svg, which) {
      var img = document.createElement("img");
      img.className = "dg-play__image";
      img.alt = "Diagram preview, " + which;
      var url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
      img.onload = function () {
        stage.querySelectorAll("iframe, img").forEach(function (el) {
          if (el !== img) el.remove();
        });
        URL.revokeObjectURL(url);
      };
      img.src = url;
      stage.appendChild(img);
      hideEmpty();
    }

    function hideEmpty() {
      var empty = $("dg-play-empty");
      if (empty) empty.remove();
    }

    function download(which) {
      var id = send({ kind: "download", source: source(), want: which, view: state.view, contrast: state.contrast });
      downloads[id] = function (r) {
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
      build();
    }

    modeButtons.forEach(function (b) {
      b.addEventListener("click", function () {
        state.mode = b.dataset.mode;
        modeButtons.forEach(function (o) { o.setAttribute("aria-pressed", String(o === b)); });
        build();
      });
    });

    contrastButton.addEventListener("click", function () {
      state.contrast = !state.contrast;
      contrastButton.setAttribute("aria-pressed", String(state.contrast));
      var frame = stage.querySelector("iframe:not(.is-loading)");
      if (state.mode === "player" && frame) dress(frame);
      else build();
    });

    viewSelect.addEventListener("change", function () {
      state.view = viewSelect.value;
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
      encode(source()).then(function (code) {
        var url = location.href.split("#")[0] + "#s=" + code;
        history.replaceState(null, "", url);
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

    var editorReady = codemirror().then(function (CodeMirror) {
      editor = CodeMirror.fromTextArea(textarea, {
        mode: "yaml",
        lineNumbers: true,
        indentUnit: 2,
        tabSize: 2,
        indentWithTabs: false,
        lineWrapping: false,
        extraKeys: {
          Tab: function (cm) {
            if (cm.somethingSelected()) cm.indentSelection("add");
            else cm.replaceSelection("  ", "end");
          },
          "Shift-Tab": function (cm) { cm.indentSelection("subtract"); },
        },
      });
      editor.on("change", later);
    }, function () {
      textarea.classList.add("is-plain");
      textarea.addEventListener("input", later);
    });

    Promise.all([fromHash(), examplesReady, editorReady]).then(function (got) {
      var text = got[0] || stored() || (got[1][0] && got[1][0].source) || "";
      setSource(text);
      if (editor) editor.clearHistory();
      build();
    });
  }

  init();
  if (window.document$ && typeof window.document$.subscribe === "function") window.document$.subscribe(init);
})();
