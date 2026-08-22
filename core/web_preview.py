"""Generate and serve browser previews for exported X3D files."""

from __future__ import annotations

import atexit
import functools
import gzip
import hashlib
import html
import http.client
import http.server
import os
import re
import shutil
import socketserver
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path, PurePosixPath
from typing import Optional


LOG_PREFIX = "[GAMEEXPORT] "
X3DOM_JS_URL = "https://www.x3dom.org/release/x3dom.js"
X3DOM_CSS_URL = "https://www.x3dom.org/release/x3dom.css"
PREVIEW_MARKER = "GameEngineExportWB Web Preview"
PREVIEW_HOST = "127.0.0.1"
PREVIEW_PORT_START = 8000
PREVIEW_PORT_END = 9000
PREVIEW_IDLE_TIMEOUT_SECONDS = 15 * 60
WEB_ASSET_DIR = ".gee_web_assets"

SCENE_RE = re.compile(
    r"<(?:[A-Za-z_][\w.-]*:)?Scene\b[^>]*>.*?</(?:[A-Za-z_][\w.-]*:)?Scene>",
    re.DOTALL,
)
EMPTY_X3D_ELEMENT_RE = re.compile(r"<([A-Za-z_][\w.:-]*)([^<>]*?)\s*/>")
X3D_URL_ATTRIBUTE_RE = re.compile(
    r"(\b(?:backUrl|bottomUrl|frontUrl|leftUrl|rightUrl|topUrl|url)\b\s*=\s*)([\"'])(.*?)\2",
    re.IGNORECASE | re.DOTALL,
)
MFSTRING_ITEM_RE = re.compile(r"([\"'])(.*?)\1")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
NAVIGATION_INFO_TAG_RE = re.compile(
    r"<(?:[A-Za-z_][\w.-]*:)?NavigationInfo\b[^>]*>",
    re.IGNORECASE,
)
HEADLIGHT_ATTRIBUTE_RE = re.compile(
    r"\s+headlight\s*=\s*(?:\"[^\"]*\"|'[^']*')",
    re.IGNORECASE,
)
SCENE_LIGHT_TAG_RE = re.compile(
    r"<\s*(?:DirectionalLight|PointLight|SpotLight)\b",
    re.IGNORECASE,
)

_active_server = None
_active_server_lock = threading.RLock()


def generate_x3dom_preview(
    x3d_path: Path,
    html_path: Optional[Path] = None,
    title: Optional[str] = None,
) -> Path:
    """Create an index.html page that displays an exported X3D scene with X3DOM."""
    x3d_file = Path(x3d_path).resolve()
    if not x3d_file.is_file():
        raise FileNotFoundError(str(x3d_file))

    target = Path(html_path).resolve() if html_path is not None else x3d_file.with_name("index.html")
    target.parent.mkdir(parents=True, exist_ok=True)

    _log_debug("Web preview HTML generation started")
    _log_debug("Web preview X3D source: " + x3d_file.name)
    scene_markup = extract_scene_markup(_read_x3d_text(x3d_file))

    # X3D exporters normally emit relative asset URLs. This extra pass handles
    # old exports and hand-edited files that contain file:// or absolute paths.
    # External local files are copied under the served folder before rewriting.
    scene_markup = make_scene_urls_http_safe(
        scene_markup,
        source_dir=x3d_file.parent,
        preview_dir=target.parent,
    )
    scene_markup = apply_web_preview_lighting(scene_markup)

    page_title = title or (x3d_file.stem + " Web Preview")
    target.write_text(_build_preview_html(scene_markup, page_title, x3d_file.name), encoding="utf-8")
    _log_debug("Web preview HTML generated: " + target.name)
    return target


def open_preview(html_path: Path) -> bool:
    """Serve the preview over HTTP and open it in a new browser tab."""
    server = start_preview_server(html_path)
    _log_debug("Web preview URL opening: " + server.url)
    opened = bool(webbrowser.open(server.url, new=2, autoraise=True))
    if opened:
        _log_info("Web preview URL opened: " + server.url)
    else:
        _log_warning("Browser did not confirm web preview open: " + server.url)
    return opened


def start_preview_server(
    html_path: Path,
    port_start: int = PREVIEW_PORT_START,
    port_end: int = PREVIEW_PORT_END,
    idle_timeout: float = PREVIEW_IDLE_TIMEOUT_SECONDS,
) -> "LocalPreviewServer":
    """Start or reuse the local HTTP server for one preview folder."""
    global _active_server

    html_file = Path(html_path).resolve()
    if not html_file.is_file():
        raise FileNotFoundError(str(html_file))
    if int(port_start) < 1 or int(port_end) > 65535 or int(port_start) > int(port_end):
        raise ValueError("Invalid web preview port range")

    served_folder = html_file.parent
    with _active_server_lock:
        current = _active_server

    # Reuse a live server when another preview is generated in the same folder.
    # The file is read per HTTP request, so the browser receives the new content.
    if current is not None and current.is_running and current.served_folder == served_folder:
        current.set_entry_file(html_file)
        current.touch()
        _log_debug("Web preview server reused on port " + str(current.port))
        return current

    # Only one preview server is needed by this Workbench module. Replacing it
    # also closes access to a folder that is no longer the active preview.
    if current is not None:
        current.stop("replaced by a new preview")

    server = LocalPreviewServer(
        html_file=html_file,
        port_start=int(port_start),
        port_end=int(port_end),
        idle_timeout=float(idle_timeout),
    )
    server.start()
    with _active_server_lock:
        _active_server = server
    return server


def stop_preview_server(reason: str = "requested") -> None:
    """Stop the active preview server, if one exists."""
    with _active_server_lock:
        server = _active_server
    if server is not None:
        server.stop(reason)


def get_active_preview_url() -> Optional[str]:
    """Return the active HTTP preview URL without creating a server."""
    with _active_server_lock:
        server = _active_server
    if server is None or not server.is_running:
        return None
    return server.url


def extract_scene_markup(x3d_content: str) -> str:
    """Return the Scene element from an X3D document."""
    match = SCENE_RE.search(x3d_content)
    if not match:
        raise ValueError("No X3D Scene node found for web preview")
    return html_safe_x3d_markup(match.group(0).strip())


def html_safe_x3d_markup(x3d_markup: str) -> str:
    """Convert XML-style self-closing X3D tags to HTML-safe explicit tags."""
    previous = None
    current = x3d_markup
    while previous != current:
        previous = current
        current = EMPTY_X3D_ELEMENT_RE.sub(r"<\1\2></\1>", current)
    return current


def make_scene_urls_http_safe(scene_markup: str, source_dir: Path, preview_dir: Path) -> str:
    """Rewrite local absolute X3D asset references as served relative URLs."""
    source_root = Path(source_dir).resolve()
    preview_root = Path(preview_dir).resolve()
    rewrite_count = 0

    def replace_attribute(match: re.Match) -> str:
        nonlocal rewrite_count
        raw_value = html.unescape(match.group(3))
        new_value, changed = _rewrite_mfstring_urls(raw_value, source_root, preview_root)
        if changed:
            rewrite_count += 1
        escaped_value = html.escape(new_value, quote=True)
        return match.group(1) + match.group(2) + escaped_value + match.group(2)

    result = X3D_URL_ATTRIBUTE_RE.sub(replace_attribute, scene_markup)
    if rewrite_count:
        _log_debug("Web preview URL attributes normalized: " + str(rewrite_count))
    else:
        _log_debug("Web preview URL attributes already HTTP compatible")
    return result


def apply_web_preview_lighting(scene_markup: str) -> str:
    """Enable a camera fill light only when the X3D has no scene lights."""
    scene_light_count = len(SCENE_LIGHT_TAG_RE.findall(scene_markup))
    if scene_light_count:
        _log_debug(
            "Web preview camera headlight preserved; scene lights detected: "
            + str(scene_light_count)
        )
        return scene_markup

    changed = False

    def replace_navigation(match: re.Match) -> str:
        nonlocal changed
        tag = match.group(0)
        without_headlight = HEADLIGHT_ATTRIBUTE_RE.sub("", tag)
        self_closing = without_headlight.rstrip().endswith("/>")
        if self_closing:
            base = without_headlight.rstrip()[:-2].rstrip()
            ending = " />"
        else:
            base = without_headlight.rstrip()[:-1].rstrip()
            ending = ">"
        changed = True
        return base + ' headlight="true"' + ending

    # A camera headlight is limited to unlit previews. This keeps dark legacy
    # files visible without overexposing scenes that already contain lights.
    result = NAVIGATION_INFO_TAG_RE.sub(replace_navigation, scene_markup, count=1)
    if changed:
        _log_debug("Web preview camera headlight enabled for interior visibility")
    else:
        # X3D defaults headlight to true when NavigationInfo is absent, so no
        # fallback light node is needed in this case.
        _log_debug("Web preview uses default camera headlight; NavigationInfo not found")
    return result


def _rewrite_mfstring_urls(value: str, source_root: Path, preview_root: Path):
    """Rewrite every quoted item of an X3D MFString URL value."""
    changed = False

    def replace_item(match: re.Match) -> str:
        nonlocal changed
        old_reference = match.group(2)
        new_reference = _rewrite_asset_reference(old_reference, source_root, preview_root)
        if new_reference != old_reference:
            changed = True
        return match.group(1) + new_reference + match.group(1)

    if MFSTRING_ITEM_RE.search(value):
        return MFSTRING_ITEM_RE.sub(replace_item, value), changed

    # X3D URL fields should be MFString values, but accepting a plain string
    # keeps the preview useful with older or manually edited exporters.
    new_value = _rewrite_asset_reference(value, source_root, preview_root)
    return new_value, new_value != value


def _rewrite_asset_reference(reference: str, source_root: Path, preview_root: Path) -> str:
    """Return an HTTP-safe URL for one local or remote asset reference."""
    clean = str(reference or "").strip()
    if not clean:
        return clean

    lowered = clean.lower()
    if lowered.startswith(("http://", "https://", "data:", "blob:")) or clean.startswith("#"):
        return clean

    local_path = None
    if lowered.startswith("file:"):
        local_path = _path_from_file_uri(clean)
    elif WINDOWS_ABSOLUTE_RE.match(clean) or os.path.isabs(clean):
        local_path = Path(clean)
    else:
        # Relative X3D assets remain relative when HTML is generated next to
        # the X3D. If HTML is elsewhere, copy only references that exist.
        normalized = clean.replace("\\", "/")
        candidate_text = urllib.parse.unquote(urllib.parse.urlsplit(normalized).path)
        candidate = (source_root / candidate_text).resolve()
        if source_root == preview_root and _path_is_inside(candidate, preview_root):
            return normalized
        if not candidate.is_file():
            return normalized
        local_path = candidate

    resolved = Path(local_path).resolve()
    if resolved.is_file():
        if _path_is_inside(resolved, preview_root):
            relative = resolved.relative_to(preview_root).as_posix()
            _log_debug("Web preview local URL made relative: " + relative)
            return urllib.parse.quote(relative, safe="/")
        return _copy_external_asset(resolved, preview_root)

    # Never retain file:// even when its target is missing. A relative missing
    # URL gives a clear HTTP 404 and avoids reintroducing a file security origin.
    fallback_name = resolved.name or "missing_asset"
    _log_warning("Web preview local asset not found: " + (resolved.name or "missing_asset"))
    return urllib.parse.quote(fallback_name, safe="")


def _path_from_file_uri(uri: str) -> Path:
    """Convert a file URI to a local path on Windows or POSIX."""
    parsed = urllib.parse.urlsplit(uri)
    path_text = urllib.parse.unquote(parsed.path)
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        path_text = "//" + parsed.netloc + path_text
    elif WINDOWS_ABSOLUTE_RE.match(path_text[1:]):
        path_text = path_text[1:]
    return Path(path_text)


def _copy_external_asset(source: Path, preview_root: Path) -> str:
    """Copy an external local asset under the folder exposed by HTTP."""
    digest = hashlib.sha1(str(source).encode("utf-8", errors="replace")).hexdigest()[:10]
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", source.name) or "asset"
    asset_dir = preview_root / WEB_ASSET_DIR
    asset_dir.mkdir(parents=True, exist_ok=True)
    target = asset_dir / (digest + "_" + safe_name)
    shutil.copy2(str(source), str(target))
    relative = target.relative_to(preview_root).as_posix()
    _log_debug("Web preview asset copied: " + source.name + " -> " + relative)
    return urllib.parse.quote(relative, safe="/")


def _path_is_inside(path: Path, root: Path) -> bool:
    """Return True when path resolves inside root, including root itself."""
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except (OSError, ValueError):
        return False


class _PreviewRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Serve one fixed directory and reject resolved paths outside it."""

    def __init__(self, *args, directory=None, **kwargs):
        self._preview_root = Path(directory or os.getcwd()).resolve()
        super().__init__(*args, directory=str(self._preview_root), **kwargs)

    def do_GET(self):
        self._note_request()
        super().do_GET()

    def do_HEAD(self):
        self._note_request()
        super().do_HEAD()

    def translate_path(self, path):
        # SimpleHTTPRequestHandler already blocks normal parent traversal. The
        # resolved containment check below also blocks symlinks leaving the root.
        url_path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        parts = [
            part
            for part in PurePosixPath(url_path).parts
            if part not in ("/", "", ".", "..")
        ]
        candidate = self._preview_root.joinpath(*parts).resolve()
        if not _path_is_inside(candidate, self._preview_root):
            _log_warning("Web preview rejected path outside served folder: " + url_path)
            return str(self._preview_root / "__gee_forbidden_path__")
        return str(candidate)

    def end_headers(self):
        # Export output changes frequently; disabling cache keeps repeated
        # previews synchronized with the most recent X3D export.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, format_text, *args):
        _log_debug("Web preview HTTP: " + (format_text % args))

    def _note_request(self):
        owner = getattr(self.server, "gee_preview_owner", None)
        if owner is not None:
            owner.touch()


class _PreviewHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """HTTP server whose request threads cannot keep FreeCAD alive."""

    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False


class LocalPreviewServer:
    """Manage one background HTTP server and its automatic shutdown."""

    def __init__(self, html_file: Path, port_start: int, port_end: int, idle_timeout: float):
        self.html_file = Path(html_file).resolve()
        self.served_folder = self.html_file.parent
        self.idle_timeout = max(0.0, float(idle_timeout))
        self._last_activity = time.monotonic()
        self._state_lock = threading.RLock()
        self._stopped = False
        self._thread = None
        self._watchdog_thread = None
        self._watchdog_stop = threading.Event()
        self._httpd = self._bind_first_available_port(port_start, port_end)
        self._httpd.gee_preview_owner = self
        self.port = int(self._httpd.server_address[1])

    @property
    def url(self) -> str:
        quoted_name = urllib.parse.quote(self.html_file.name)
        return "http://{host}:{port}/{name}".format(
            host=PREVIEW_HOST,
            port=self.port,
            name=quoted_name,
        )

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return not self._stopped and self._thread is not None and self._thread.is_alive()

    def set_entry_file(self, html_file: Path) -> None:
        candidate = Path(html_file).resolve()
        if candidate.parent != self.served_folder or not candidate.is_file():
            raise ValueError("Preview entry file must be inside the served folder")
        with self._state_lock:
            self.html_file = candidate

    def start(self) -> None:
        """Start request and watchdog threads without blocking FreeCAD."""
        with self._state_lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._httpd.serve_forever,
                kwargs={"poll_interval": 0.2},
                name="GameExportWebPreviewHTTP",
                daemon=True,
            )
            self._thread.start()

        # Confirm one real HTTP exchange before opening the browser. On Windows,
        # a client can occasionally connect before the new thread enters its
        # request loop, so a bounded retry prevents a blank first browser tab.
        self._wait_until_ready()

        with self._state_lock:
            if self.idle_timeout > 0.0:
                self._watchdog_thread = threading.Thread(
                    target=self._watch_idle_timeout,
                    name="GameExportWebPreviewWatchdog",
                    daemon=True,
                )
                self._watchdog_thread.start()

        _log_info("Web preview server started")
        _log_debug("Web preview server port: " + str(self.port))
        _log_debug("Web preview served folder: " + self.served_folder.name)
        _log_debug("Web preview server URL: " + self.url)

    def touch(self) -> None:
        with self._state_lock:
            self._last_activity = time.monotonic()

    def stop(self, reason: str = "requested") -> None:
        """Stop request processing and release the selected TCP port."""
        with self._state_lock:
            if self._stopped:
                return
            self._stopped = True
            server_thread = self._thread
            watchdog_thread = self._watchdog_thread
            self._watchdog_stop.set()

        _log_debug("Web preview server closing: " + str(reason))
        if server_thread is not None and server_thread.is_alive():
            self._httpd.shutdown()
        self._httpd.server_close()

        current_thread = threading.current_thread()
        if server_thread is not None and server_thread is not current_thread:
            server_thread.join(timeout=2.0)
        if watchdog_thread is not None and watchdog_thread is not current_thread:
            watchdog_thread.join(timeout=2.0)

        _forget_server(self)
        _log_info("Web preview server stopped: " + str(reason))

    def _bind_first_available_port(self, port_start: int, port_end: int):
        handler_factory = functools.partial(
            _PreviewRequestHandler,
            directory=str(self.served_folder),
        )
        last_error = None
        for port in range(int(port_start), int(port_end) + 1):
            try:
                return _PreviewHTTPServer((PREVIEW_HOST, port), handler_factory)
            except OSError as exc:
                last_error = exc
                _log_debug("Web preview port unavailable: " + str(port))
        raise RuntimeError(
            "No free local HTTP port in range {0}-{1}: {2}".format(
                port_start,
                port_end,
                last_error,
            )
        )

    def _wait_until_ready(self) -> None:
        """Wait briefly until the background request loop answers HTTP."""
        deadline = time.monotonic() + 3.0
        last_error = None
        request_path = "/" + urllib.parse.quote(self.html_file.name)
        while time.monotonic() < deadline:
            connection = http.client.HTTPConnection(PREVIEW_HOST, self.port, timeout=0.5)
            try:
                connection.request("HEAD", request_path)
                response = connection.getresponse()
                response.read()
                if response.status < 500:
                    _log_debug("Web preview server readiness check passed")
                    return
                last_error = RuntimeError("HTTP status " + str(response.status))
            except (OSError, http.client.HTTPException) as exc:
                last_error = exc
                time.sleep(0.05)
            finally:
                connection.close()
        self.stop("startup failed")
        raise RuntimeError("Web preview server did not become ready: " + str(last_error))

    def _watch_idle_timeout(self) -> None:
        # A short periodic wait makes shutdown responsive without busy polling.
        check_interval = min(5.0, max(0.25, self.idle_timeout / 4.0))
        while not self._watchdog_stop.wait(check_interval):
            with self._state_lock:
                idle_for = time.monotonic() - self._last_activity
            if idle_for >= self.idle_timeout:
                self.stop("idle timeout")
                return


def _forget_server(server: LocalPreviewServer) -> None:
    """Remove a stopped server from the module registry."""
    global _active_server
    with _active_server_lock:
        if _active_server is server:
            _active_server = None


def _read_x3d_text(x3d_file: Path) -> str:
    data = x3d_file.read_bytes()
    if data[:2] == b"\x1f\x8b" or x3d_file.suffix.lower() == ".x3dz":
        data = gzip.decompress(data)
    return data.decode("utf-8")


def _build_preview_html(scene_markup: str, title: str, source_name: str) -> str:
    safe_title = html.escape(title, quote=True)
    safe_source = html.escape(source_name, quote=True)
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="generator" content="GameEngineExportWB">
  <title>{title}</title>
  <link rel="stylesheet" href="{css_url}">
  <script src="{js_url}"></script>
  <style>
    html,
    body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #111827;
      color: #e5e7eb;
      font-family: Arial, sans-serif;
    }}

    .gee-web-preview {{
      display: flex;
      flex-direction: column;
      width: 100vw;
      height: 100vh;
    }}

    .gee-web-preview__bar {{
      flex: 0 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 32px;
      padding: 6px 10px;
      background: #1f2937;
      border-bottom: 1px solid #374151;
      font-size: 13px;
      line-height: 18px;
      box-sizing: border-box;
    }}

    .gee-web-preview__source {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .gee-web-preview__status {{
      flex: 0 0 auto;
      color: #93c5fd;
      white-space: nowrap;
    }}

    .gee-web-preview__scene {{
      flex: 1 1 auto;
      min-height: 0;
    }}

    x3d {{
      display: block;
      width: 100%;
      height: 100%;
      border: 0;
    }}
  </style>
</head>
<body>
  <!-- {marker}: generated from {source} -->
  <div class="gee-web-preview">
    <div class="gee-web-preview__bar">
      <span class="gee-web-preview__source">{source}</span>
      <span id="gee-web-preview-status" class="gee-web-preview__status">Loading X3DOM...</span>
    </div>
    <div class="gee-web-preview__scene">
      <x3d id="gee-x3d-preview" showStat="false" showLog="false" width="100%" height="100%">
{scene}
      </x3d>
    </div>
  </div>
  <script>
    (function () {{
      var statusNode = document.getElementById("gee-web-preview-status");

      function setStatus(text, isError) {{
        if (!statusNode) {{
          return;
        }}
        statusNode.textContent = text;
        statusNode.style.color = isError ? "#fca5a5" : "#93c5fd";
      }}

      window.addEventListener("error", function (event) {{
        if (String(event.filename || "").indexOf("x3dom") >= 0) {{
          setStatus("X3DOM failed to load", true);
        }}
      }});

      window.addEventListener("load", function () {{
        var x3dNode = document.getElementById("gee-x3d-preview");
        var sceneNode = x3dNode ? (x3dNode.querySelector("scene") || x3dNode.querySelector("Scene")) : null;
        var shapeCount = x3dNode ? x3dNode.querySelectorAll("shape, Shape").length : 0;

        if (!window.x3dom) {{
          setStatus("X3DOM not loaded. Check internet access.", true);
          return;
        }}
        if (!sceneNode) {{
          setStatus("No Scene node found in generated HTML", true);
          return;
        }}
        if (shapeCount < 1) {{
          setStatus("Scene loaded, but no Shape nodes found", true);
          return;
        }}
        try {{
          if (window.x3dom.reload) {{
            window.x3dom.reload();
          }}
        }} catch (exc) {{
          setStatus("X3DOM reload failed", true);
          return;
        }}
        setStatus("Scene ready (" + shapeCount + " shapes)", false);
      }});
    }}());
  </script>
</body>
</html>
""".format(
        title=safe_title,
        source=safe_source,
        css_url=X3DOM_CSS_URL,
        js_url=X3DOM_JS_URL,
        marker=PREVIEW_MARKER,
        scene=_indent_scene(scene_markup),
    )


def _indent_scene(scene_markup: str) -> str:
    return "\n".join("        " + line for line in scene_markup.splitlines())


def _write_log(level: str, message: str) -> None:
    """Write to the FreeCAD console and fall back to stdout in tests."""
    line = LOG_PREFIX + "[" + level + "] " + str(message) + "\n"
    try:
        FreeCAD = __import__("FreeCAD")
        if level == "WARN":
            FreeCAD.Console.PrintWarning(line)
        elif level == "ERROR":
            FreeCAD.Console.PrintError(line)
        else:
            FreeCAD.Console.PrintMessage(line)
    except Exception:
        print(line.rstrip())


def _log_debug(message: str) -> None:
    _write_log("DEBUG", message)


def _log_info(message: str) -> None:
    _write_log("INFO", message)


def _log_warning(message: str) -> None:
    _write_log("WARN", message)


# atexit covers normal FreeCAD shutdown. Daemon request threads provide a final
# safety net if the embedded Python runtime exits before callbacks are completed.
atexit.register(stop_preview_server, "FreeCAD/Python shutdown")


__all__ = [
    "LocalPreviewServer",
    "generate_x3dom_preview",
    "open_preview",
    "start_preview_server",
    "stop_preview_server",
    "get_active_preview_url",
    "extract_scene_markup",
    "html_safe_x3d_markup",
    "make_scene_urls_http_safe",
    "apply_web_preview_lighting",
]
