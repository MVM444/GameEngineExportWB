"""Tests for X3DOM web preview generation."""

from __future__ import annotations

import gzip
import socket
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from GameEngineExportWB.core import web_preview


SAMPLE_X3D = """<?xml version="1.0" encoding="utf-8"?>
<X3D profile="Immersive" version="3.3">
  <head>
    <meta name="generator" content="FreeCAD" />
  </head>
  <Scene>
    <Background backUrl="&quot;Sample_assets/skies/back.png&quot;" />
    <NavigationInfo DEF="GameExport_Navigation" type="&quot;WALK&quot;" headlight="false" />
    <Viewpoint DEF="GameExport_Viewpoint" position="0 1.6 6" />
    <Transform DEF="Model">
      <Shape>
        <Appearance>
          <ImageTexture url="&quot;Sample_assets/textures/grass.png&quot;" />
        </Appearance>
        <Box />
      </Shape>
    </Transform>
  </Scene>
</X3D>
"""


class WebPreviewTests(unittest.TestCase):
    def test_extract_scene_markup(self):
        scene = web_preview.extract_scene_markup(SAMPLE_X3D)

        self.assertTrue(scene.startswith("<Scene>"))
        self.assertIn("Sample_assets/textures/grass.png", scene)
        self.assertNotIn("<head>", scene)
        self.assertIn("<Box></Box>", scene)
        self.assertIn("<ImageTexture url=\"&quot;Sample_assets/textures/grass.png&quot;\"></ImageTexture>", scene)
        self.assertIn("GameExport_Navigation", scene)
        self.assertIn("GameExport_Viewpoint", scene)
        self.assertNotIn("<Box />", scene)

    def test_generate_index_html_next_to_x3d(self):
        with tempfile.TemporaryDirectory() as tmp:
            x3d_path = Path(tmp) / "Sample.x3d"
            x3d_path.write_text(SAMPLE_X3D, encoding="utf-8")

            html_path = web_preview.generate_x3dom_preview(x3d_path)
            html_text = html_path.read_text(encoding="utf-8")

        self.assertEqual("index.html", html_path.name)
        self.assertIn(web_preview.PREVIEW_MARKER, html_text)
        self.assertIn(web_preview.X3DOM_JS_URL, html_text)
        self.assertIn("<x3d", html_text)
        self.assertIn("<Scene>", html_text)
        self.assertIn("gee-web-preview-status", html_text)
        self.assertIn("Sample_assets/textures/grass.png", html_text)
        self.assertIn("GameExport_Navigation", html_text)
        self.assertIn("GameExport_Viewpoint", html_text)
        self.assertIn('headlight="true"', html_text)
        self.assertNotIn('headlight="false"', html_text)
        self.assertLess(html_text.index("GameExport_Navigation"), html_text.index("GameExport_Viewpoint"))
        self.assertLess(html_text.index("GameExport_Viewpoint"), html_text.index('DEF="Model"'))
        self.assertNotIn("file://", html_text)

    def test_generate_preview_from_gzip_x3dz(self):
        with tempfile.TemporaryDirectory() as tmp:
            x3dz_path = Path(tmp) / "Sample.x3dz"
            x3dz_path.write_bytes(gzip.compress(SAMPLE_X3D.encode("utf-8")))

            html_path = web_preview.generate_x3dom_preview(x3dz_path)
            html_text = html_path.read_text(encoding="utf-8")

        self.assertIn("<Scene>", html_text)
        self.assertIn("Sample_assets/skies/back.png", html_text)

    def test_absolute_file_asset_is_copied_and_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output"
            output_dir.mkdir()
            external_texture = root / "external grass.png"
            external_texture.write_bytes(b"texture")
            x3d_text = SAMPLE_X3D.replace(
                "Sample_assets/textures/grass.png",
                external_texture.resolve().as_uri(),
            )
            x3d_path = output_dir / "Sample.x3d"
            x3d_path.write_text(x3d_text, encoding="utf-8")

            html_path = web_preview.generate_x3dom_preview(x3d_path)
            html_text = html_path.read_text(encoding="utf-8")
            copied_assets = list((output_dir / web_preview.WEB_ASSET_DIR).glob("*"))

        self.assertNotIn("file://", html_text)
        self.assertIn(web_preview.WEB_ASSET_DIR, html_text)
        self.assertEqual(1, len(copied_assets))

    def test_web_lighting_replaces_headlight_without_changing_navigation(self):
        scene = web_preview.extract_scene_markup(SAMPLE_X3D)

        result = web_preview.apply_web_preview_lighting(scene)

        self.assertEqual(1, result.count('headlight="true"'))
        self.assertNotIn('headlight="false"', result)
        self.assertIn('type="&quot;WALK&quot;"', result)
        self.assertIn('position="0 1.6 6"', result)
        self.assertLess(result.index("GameExport_Navigation"), result.index("GameExport_Viewpoint"))

    def test_web_lighting_preserves_headlight_when_scene_has_lights(self):
        scene = web_preview.extract_scene_markup(SAMPLE_X3D)
        scene = scene.replace("<Viewpoint", '<PointLight on="true"></PointLight><Viewpoint', 1)

        result = web_preview.apply_web_preview_lighting(scene)

        self.assertIn('headlight="false"', result)
        self.assertNotIn('headlight="true"', result)
        self.assertIn('<PointLight on="true"></PointLight>', result)

    def test_server_uses_http_and_serves_only_preview_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preview_dir = root / "preview"
            preview_dir.mkdir()
            html_path = preview_dir / "index.html"
            html_path.write_text("<html><body>served</body></html>", encoding="utf-8")
            outside_path = root / "outside.txt"
            outside_path.write_text("private", encoding="utf-8")

            server = web_preview.start_preview_server(html_path, idle_timeout=0)
            try:
                with urllib.request.urlopen(server.url, timeout=3.0) as response:
                    body = response.read().decode("utf-8")
                escaped_url = server.url.replace("index.html", "../outside.txt")
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(escaped_url, timeout=3.0)
            finally:
                web_preview.stop_preview_server("unit test")

        self.assertTrue(server.url.startswith("http://127.0.0.1:"))
        self.assertNotIn("file://", server.url)
        self.assertIn("served", body)
        self.assertEqual(404, error.exception.code)

    def test_occupied_port_uses_next_available_port(self):
        first_port = self._find_two_consecutive_free_ports()
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind((web_preview.PREVIEW_HOST, first_port))
        blocker.listen(1)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                html_path = Path(tmp) / "index.html"
                html_path.write_text("preview", encoding="utf-8")
                server = web_preview.start_preview_server(
                    html_path,
                    port_start=first_port,
                    port_end=first_port + 1,
                    idle_timeout=0,
                )
                try:
                    self.assertEqual(first_port + 1, server.port)
                finally:
                    web_preview.stop_preview_server("unit test")
        finally:
            blocker.close()

    def test_open_preview_opens_new_tab_with_http_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "index.html"
            html_path.write_text("preview", encoding="utf-8")
            with mock.patch.object(web_preview.webbrowser, "open", return_value=True) as browser_open:
                try:
                    opened = web_preview.open_preview(html_path)
                    active_url = web_preview.get_active_preview_url()
                finally:
                    web_preview.stop_preview_server("unit test")

        self.assertTrue(opened)
        self.assertTrue(active_url.startswith("http://127.0.0.1:"))
        browser_open.assert_called_once_with(active_url, new=2, autoraise=True)

    def test_server_reuses_folder_and_stops_after_idle_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            preview_dir = Path(tmp)
            first_html = preview_dir / "index.html"
            second_html = preview_dir / "alternate.html"
            first_html.write_text("first", encoding="utf-8")
            second_html.write_text("second", encoding="utf-8")

            first_server = web_preview.start_preview_server(first_html, idle_timeout=0.35)
            second_server = web_preview.start_preview_server(second_html, idle_timeout=0.35)
            self.assertIs(first_server, second_server)
            self.assertTrue(second_server.url.endswith("/alternate.html"))

            deadline = time.monotonic() + 2.0
            while second_server.is_running and time.monotonic() < deadline:
                time.sleep(0.05)

        self.assertFalse(second_server.is_running)
        self.assertIsNone(web_preview.get_active_preview_url())

    @staticmethod
    def _find_two_consecutive_free_ports():
        for port in range(web_preview.PREVIEW_PORT_START, web_preview.PREVIEW_PORT_END):
            first = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            second = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                first.bind((web_preview.PREVIEW_HOST, port))
                second.bind((web_preview.PREVIEW_HOST, port + 1))
                return port
            except OSError:
                continue
            finally:
                first.close()
                second.close()
        raise RuntimeError("No two consecutive test ports available")


if __name__ == "__main__":
    unittest.main()
