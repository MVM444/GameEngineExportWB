"""Streaming diagnostics for large X3D and X3DZ files.

Descripcion: analiza tamano, geometria, luces, nombres DEF/USE y mallas
repetidas sin cargar el archivo X3D completo en memoria.
Fecha y hora: 2026-08-13 17:35 America/Costa_Rica.
Instrucciones clave:
- Mantener codigo y mensajes en ASCII.
- No modificar el X3D analizado.
- Usar lectura incremental para archivos grandes.
- Generar reportes JSON y Markdown junto al X3D.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import xml.sax
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple


ANALYZER_VERSION = "2026-08-13-streaming-v1"
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?")
INTEGER_RE = re.compile(r"-?\d+")
GEOMETRY_TAGS = {
    "IndexedFaceSet",
    "IndexedTriangleSet",
    "IndexedTriangleStripSet",
    "IndexedTriangleFanSet",
    "TriangleSet",
    "TriangleStripSet",
    "TriangleFanSet",
    "IndexedLineSet",
    "LineSet",
    "PointSet",
}
PAYLOAD_FIELDS = {
    "coordIndex",
    "normalIndex",
    "colorIndex",
    "texCoordIndex",
    "index",
    "point",
    "vector",
    "color",
}
CONTEXT_TAGS = {"Transform", "Group", "Collision", "Switch", "Shape"}
LIGHT_TAGS = {"PointLight", "SpotLight", "DirectionalLight"}


class AnalysisCancelled(RuntimeError):
    pass


def _local_name(name: str) -> str:
    return str(name or "").split(":", 1)[-1]


def _count_numeric_tokens(value: str) -> int:
    return sum(1 for _ in NUMBER_RE.finditer(value or ""))


def _indexed_face_metrics(value: str) -> Tuple[int, int, int]:
    """Return vertex-index count, polygon count and triangle equivalent."""
    indices = 0
    polygons = 0
    triangles = 0
    face_vertices = 0
    for match in INTEGER_RE.finditer(value or ""):
        number = int(match.group(0))
        if number == -1:
            if face_vertices:
                polygons += 1
                triangles += max(face_vertices - 2, 0)
                indices += face_vertices
                face_vertices = 0
        else:
            face_vertices += 1
    if face_vertices:
        polygons += 1
        triangles += max(face_vertices - 2, 0)
        indices += face_vertices
    return indices, polygons, triangles


def _update_text_hash(digest, field_name: str, value: str) -> None:
    digest.update(field_name.encode("ascii", errors="ignore"))
    digest.update(b"\x00")
    text = value or ""
    chunk_size = 1024 * 1024
    for offset in range(0, len(text), chunk_size):
        digest.update(text[offset : offset + chunk_size].encode("utf-8", errors="replace"))
    digest.update(b"\x00")


class _CountingReader:
    def __init__(self, stream, total_hint: int, progress_callback=None):
        self.stream = stream
        self.total_hint = int(total_hint or 0)
        self.progress_callback = progress_callback
        self.bytes_read = 0
        self._last_progress = 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.bytes_read += len(data or b"")
        if (
            self.progress_callback is not None
            and (self.bytes_read - self._last_progress >= 4 * 1024 * 1024 or not data)
        ):
            self._last_progress = self.bytes_read
            keep_going = self.progress_callback(self.bytes_read, self.total_hint)
            if keep_going is False:
                raise AnalysisCancelled("X3D analysis cancelled")
        return data

    def close(self):
        return self.stream.close()


class _OwnedGzipReader:
    """Close both the gzip decoder and its explicitly owned source file."""

    def __init__(self, raw):
        self.raw = raw
        self.gzip_stream = gzip.GzipFile(fileobj=raw, mode="rb")

    def read(self, size=-1):
        return self.gzip_stream.read(size)

    def close(self):
        try:
            self.gzip_stream.close()
        finally:
            self.raw.close()


class _X3DHandler(xml.sax.handler.ContentHandler):
    def __init__(self):
        super().__init__()
        self.element_counts = Counter()
        self.def_counts = Counter()
        self.use_counts = Counter()
        self.light_counts = Counter()
        self.light_radius = defaultdict(list)
        self.light_intensity = defaultdict(list)
        self.stack = []
        self.geometry_stack = []
        self.geometry_records = []
        self.total_payload_chars = 0
        self.shape_count = 0

    def startElement(self, name, attrs):  # noqa: N802
        tag = _local_name(name)
        attrs_dict = {str(key): str(attrs.getValue(key)) for key in attrs.getNames()}
        node_def = attrs_dict.get("DEF", "")
        node_use = attrs_dict.get("USE", "")
        self.element_counts[tag] += 1
        if tag == "Shape":
            self.shape_count += 1
        if node_def:
            self.def_counts[node_def] += 1
        if node_use:
            self.use_counts[node_use] += 1

        context_defs = [
            item[1]
            for item in self.stack
            if item[0] in CONTEXT_TAGS and item[1]
        ]
        self.stack.append((tag, node_def))

        if tag in LIGHT_TAGS:
            self.light_counts[tag] += 1
            radius = attrs_dict.get("radius")
            intensity = attrs_dict.get("intensity")
            try:
                if radius is not None:
                    self.light_radius[tag].append(float(radius))
            except (TypeError, ValueError):
                pass
            try:
                if intensity is not None:
                    self.light_intensity[tag].append(float(intensity))
            except (TypeError, ValueError):
                pass

        if tag in GEOMETRY_TAGS:
            record = {
                "ordinal": len(self.geometry_records) + len(self.geometry_stack) + 1,
                "type": tag,
                "def": node_def,
                "context": " > ".join(context_defs[-5:]),
                "payload_chars": 0,
                "vertices": 0,
                "normals": 0,
                "texture_coordinates": 0,
                "colors": 0,
                "vertex_indices": 0,
                "polygons": 0,
                "triangles": 0,
                "digest_state": hashlib.sha256(),
            }
            self.geometry_stack.append(record)

        if self.geometry_stack:
            record = self.geometry_stack[-1]
            for field_name in PAYLOAD_FIELDS:
                value = attrs_dict.get(field_name)
                if value is None:
                    continue
                length = len(value)
                record["payload_chars"] += length
                self.total_payload_chars += length
                _update_text_hash(record["digest_state"], tag + "." + field_name, value)

            if tag == "Coordinate" and "point" in attrs_dict:
                record["vertices"] += _count_numeric_tokens(attrs_dict["point"]) // 3
            elif tag == "Normal" and "vector" in attrs_dict:
                record["normals"] += _count_numeric_tokens(attrs_dict["vector"]) // 3
            elif tag == "TextureCoordinate" and "point" in attrs_dict:
                record["texture_coordinates"] += _count_numeric_tokens(attrs_dict["point"]) // 2
            elif tag == "Color" and "color" in attrs_dict:
                record["colors"] += _count_numeric_tokens(attrs_dict["color"]) // 3
            elif tag == "ColorRGBA" and "color" in attrs_dict:
                record["colors"] += _count_numeric_tokens(attrs_dict["color"]) // 4

            if tag == "IndexedFaceSet" and "coordIndex" in attrs_dict:
                indices, polygons, triangles = _indexed_face_metrics(attrs_dict["coordIndex"])
                record["vertex_indices"] += indices
                record["polygons"] += polygons
                record["triangles"] += triangles
            elif tag == "IndexedTriangleSet" and "index" in attrs_dict:
                index_count = sum(1 for _ in INTEGER_RE.finditer(attrs_dict["index"]))
                record["vertex_indices"] += index_count
                record["triangles"] += index_count // 3

    def endElement(self, name):  # noqa: N802
        tag = _local_name(name)
        if tag in GEOMETRY_TAGS and self.geometry_stack:
            record = self.geometry_stack.pop()
            record["geometry_hash"] = record.pop("digest_state").hexdigest()
            self.geometry_records.append(record)
        if self.stack:
            self.stack.pop()


def _open_x3d_stream(path: Path):
    raw = path.open("rb")
    magic = raw.read(2)
    raw.seek(0)
    if magic == b"\x1f\x8b":
        return _OwnedGzipReader(raw), True
    return raw, False


def _configure_parser(handler):
    parser = xml.sax.make_parser()
    parser.setContentHandler(handler)
    for feature in (
        xml.sax.handler.feature_external_ges,
        xml.sax.handler.feature_external_pes,
    ):
        try:
            parser.setFeature(feature, False)
        except (xml.sax.SAXNotRecognizedException, xml.sax.SAXNotSupportedException):
            pass
    return parser


def _duplicate_geometry_groups(records: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped = defaultdict(list)
    for record in records:
        digest = str(record.get("geometry_hash", "") or "")
        if digest:
            grouped[digest].append(record)

    result = []
    for digest, items in grouped.items():
        if len(items) < 2:
            continue
        ordered = sorted(items, key=lambda item: int(item.get("ordinal", 0)))
        sizes = [int(item.get("payload_chars", 0) or 0) for item in ordered]
        reusable_size = min(sizes) if sizes else 0
        result.append(
            {
                "geometry_hash": digest,
                "occurrences": len(ordered),
                "payload_chars_total": sum(sizes),
                "estimated_repeated_payload_chars": reusable_size * (len(ordered) - 1),
                "defs": [str(item.get("def", "") or "") for item in ordered],
                "contexts": [str(item.get("context", "") or "") for item in ordered],
                "geometry_type": str(ordered[0].get("type", "") or ""),
                "vertices_each": int(ordered[0].get("vertices", 0) or 0),
                "triangles_each": int(ordered[0].get("triangles", 0) or 0),
            }
        )
    result.sort(
        key=lambda item: int(item.get("estimated_repeated_payload_chars", 0)),
        reverse=True,
    )
    return result


def analyze_x3d(
    path,
    top_n: int = 20,
    progress_callback: Optional[Callable[[int, int], bool]] = None,
) -> Dict[str, object]:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(str(file_path))

    compressed_size = file_path.stat().st_size
    stream, is_gzip = _open_x3d_stream(file_path)
    reader = _CountingReader(
        stream,
        0 if is_gzip else compressed_size,
        progress_callback=progress_callback,
    )
    handler = _X3DHandler()
    parser = _configure_parser(handler)
    try:
        parser.parse(reader)
    finally:
        reader.close()

    records = sorted(
        handler.geometry_records,
        key=lambda item: int(item.get("payload_chars", 0) or 0),
        reverse=True,
    )
    duplicates = _duplicate_geometry_groups(handler.geometry_records)
    duplicate_defs = [
        {"name": name, "occurrences": count}
        for name, count in handler.def_counts.most_common()
        if count > 1
    ]
    unresolved_uses = [
        {"name": name, "occurrences": count}
        for name, count in handler.use_counts.items()
        if name not in handler.def_counts
    ]

    total_triangles = sum(int(item.get("triangles", 0) or 0) for item in records)
    total_vertices = sum(int(item.get("vertices", 0) or 0) for item in records)
    repeated_payload = sum(
        int(item.get("estimated_repeated_payload_chars", 0) or 0)
        for item in duplicates
    )
    uncompressed_bytes = int(reader.bytes_read)
    payload_chars = int(handler.total_payload_chars)

    return {
        "analyzer_version": ANALYZER_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "file": {
            # Reports are designed to be shareable. Keep the compatibility
            # key but store only the portable file name, never a user path.
            "path": file_path.name,
            "name": file_path.name,
            "gzip": bool(is_gzip),
            "size_bytes": int(compressed_size),
            "uncompressed_bytes_read": uncompressed_bytes,
        },
        "summary": {
            "shapes": int(handler.shape_count),
            "geometry_nodes": len(handler.geometry_records),
            "vertices": total_vertices,
            "triangles_approx": total_triangles,
            "geometry_payload_chars": payload_chars,
            "geometry_payload_percent_of_uncompressed": (
                100.0 * payload_chars / uncompressed_bytes if uncompressed_bytes else 0.0
            ),
            "duplicate_def_names": len(duplicate_defs),
            "duplicate_geometry_groups": len(duplicates),
            "estimated_repeated_geometry_chars": repeated_payload,
            "estimated_repeated_geometry_percent_of_uncompressed": (
                100.0 * repeated_payload / uncompressed_bytes if uncompressed_bytes else 0.0
            ),
        },
        "lights": {
            "counts": dict(sorted(handler.light_counts.items())),
            "radius": {
                key: _number_summary(values)
                for key, values in sorted(handler.light_radius.items())
            },
            "intensity": {
                key: _number_summary(values)
                for key, values in sorted(handler.light_intensity.items())
            },
        },
        "elements": dict(handler.element_counts.most_common()),
        "duplicate_defs": duplicate_defs,
        "unresolved_uses": unresolved_uses,
        "largest_geometry": [_public_geometry_record(item) for item in records[: max(1, int(top_n))]],
        "duplicate_geometry": duplicates[: max(1, int(top_n))],
    }


def _number_summary(values: Iterable[float]) -> Dict[str, object]:
    numbers = [float(value) for value in values]
    if not numbers:
        return {"count": 0}
    counts = Counter(numbers)
    return {
        "count": len(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "average": sum(numbers) / len(numbers),
        "values": [
            {"value": value, "occurrences": count}
            for value, count in sorted(counts.items())
        ],
    }


def _public_geometry_record(record: Dict[str, object]) -> Dict[str, object]:
    return {
        key: value
        for key, value in record.items()
        if key != "digest_state"
    }


def _format_bytes(value: int) -> str:
    number = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024.0 or unit == "GB":
            return f"{number:.2f} {unit}"
        number /= 1024.0
    return f"{number:.2f} GB"


def _format_int(value) -> str:
    return f"{int(value or 0):,}"


def report_paths(x3d_path) -> Tuple[Path, Path]:
    path = Path(x3d_path)
    base = path.with_suffix("")
    return (
        base.with_name(base.name + ".gee.analysis.json"),
        base.with_name(base.name + ".gee.analysis.md"),
    )


def write_reports(report: Dict[str, object], x3d_path) -> Tuple[Path, Path]:
    json_path, markdown_path = report_paths(x3d_path)
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def _markdown_report(report: Dict[str, object]) -> str:
    file_info = report.get("file", {})
    summary = report.get("summary", {})
    lights = report.get("lights", {})
    lines = [
        "# Analisis X3D",
        "",
        f"- Archivo: `{file_info.get('path', '')}`",
        f"- Tamano: {_format_bytes(file_info.get('size_bytes', 0))}",
        f"- Lectura sin comprimir: {_format_bytes(file_info.get('uncompressed_bytes_read', 0))}",
        f"- Shapes: {_format_int(summary.get('shapes', 0))}",
        f"- Nodos geometricos: {_format_int(summary.get('geometry_nodes', 0))}",
        f"- Vertices: {_format_int(summary.get('vertices', 0))}",
        f"- Triangulos aproximados: {_format_int(summary.get('triangles_approx', 0))}",
        f"- Carga geometrica textual: {float(summary.get('geometry_payload_percent_of_uncompressed', 0.0)):.2f}%",
        f"- Grupos de geometria repetida: {_format_int(summary.get('duplicate_geometry_groups', 0))}",
        f"- Repeticion geometrica estimada: {_format_bytes(summary.get('estimated_repeated_geometry_chars', 0))}",
        f"- Nombres DEF duplicados: {_format_int(summary.get('duplicate_def_names', 0))}",
        "",
        "## Luces",
        "",
    ]
    counts = lights.get("counts", {}) if isinstance(lights, dict) else {}
    if counts:
        for name, count in counts.items():
            lines.append(f"- {name}: {_format_int(count)}")
    else:
        lines.append("- No se detectaron luces.")

    radius = lights.get("radius", {}) if isinstance(lights, dict) else {}
    intensity = lights.get("intensity", {}) if isinstance(lights, dict) else {}
    for light_name in sorted(set(radius) | set(intensity)):
        radius_info = radius.get(light_name, {})
        intensity_info = intensity.get(light_name, {})
        if radius_info.get("count"):
            lines.append(
                "- Radio "
                + light_name
                + ": promedio "
                + f"{float(radius_info.get('average', 0.0)):.3f} m"
                + ", rango "
                + f"{float(radius_info.get('min', 0.0)):.3f} - "
                + f"{float(radius_info.get('max', 0.0)):.3f} m"
            )
        if intensity_info.get("count"):
            lines.append(
                "- Intensidad "
                + light_name
                + ": promedio "
                + f"{float(intensity_info.get('average', 0.0)):.3f}"
                + ", rango "
                + f"{float(intensity_info.get('min', 0.0)):.3f} - "
                + f"{float(intensity_info.get('max', 0.0)):.3f}"
            )

    payload_percent = float(
        summary.get("geometry_payload_percent_of_uncompressed", 0.0) or 0.0
    )
    repeated_percent = float(
        summary.get("estimated_repeated_geometry_percent_of_uncompressed", 0.0)
        or 0.0
    )
    lines.extend(["", "## Diagnostico automatico", ""])
    if payload_percent >= 50.0:
        lines.append(
            "- La mayor parte del archivo es geometria textual: coordenadas, "
            "indices, normales y datos asociados."
        )
    else:
        lines.append(
            "- La geometria textual no supera la mitad del archivo; revise tambien "
            "materiales, metadatos y otros nodos en el JSON."
        )
    if repeated_percent >= 5.0:
        lines.append(
            "- Hay una cantidad significativa de geometria identica repetida. "
            "Esto es compatible con enlaces exportados como copias completas de la malla."
        )
    elif summary.get("duplicate_geometry_groups", 0):
        lines.append(
            "- Se encontraron mallas identicas repetidas, pero su peso estimado no "
            "domina el archivo."
        )
    else:
        lines.append("- No se detectaron bloques geometricos identicos repetidos.")
    if summary.get("duplicate_def_names", 0):
        lines.append(
            "- Existen nombres DEF duplicados; esto puede producir advertencias de X3D."
        )

    lines.extend(
        [
            "",
            "## Geometrias mas pesadas",
            "",
            "| # | Tipo | DEF | Contexto | Vertices | Triangulos | Carga textual |",
            "|---:|---|---|---|---:|---:|---:|",
        ]
    )
    for index, item in enumerate(report.get("largest_geometry", []) or [], 1):
        lines.append(
            "| "
            + str(index)
            + " | "
            + str(item.get("type", ""))
            + " | `"
            + str(item.get("def", "") or "-")
            + "` | "
            + str(item.get("context", "") or "-").replace("|", "/")
            + " | "
            + _format_int(item.get("vertices", 0))
            + " | "
            + _format_int(item.get("triangles", 0))
            + " | "
            + _format_bytes(item.get("payload_chars", 0))
            + " |"
        )

    lines.extend(["", "## Geometrias repetidas", ""])
    duplicates = report.get("duplicate_geometry", []) or []
    if not duplicates:
        lines.append("No se detectaron bloques geometricos identicos repetidos.")
    else:
        lines.extend(
            [
                "| # | Tipo | Repeticiones | Vertices c/u | Triangulos c/u | Repeticion estimada | Contextos |",
                "|---:|---|---:|---:|---:|---:|---|",
            ]
        )
        for index, item in enumerate(duplicates, 1):
            contexts = "; ".join(item.get("contexts", []) or []) or "-"
            lines.append(
                "| "
                + str(index)
                + " | "
                + str(item.get("geometry_type", ""))
                + " | "
                + _format_int(item.get("occurrences", 0))
                + " | "
                + _format_int(item.get("vertices_each", 0))
                + " | "
                + _format_int(item.get("triangles_each", 0))
                + " | "
                + _format_bytes(item.get("estimated_repeated_payload_chars", 0))
                + " | "
                + contexts.replace("|", "/")
                + " |"
            )

    duplicate_defs = report.get("duplicate_defs", []) or []
    lines.extend(["", "## Integridad DEF/USE", ""])
    if duplicate_defs:
        for item in duplicate_defs:
            lines.append(
                "- DEF duplicado: `"
                + str(item.get("name", ""))
                + "` ("
                + _format_int(item.get("occurrences", 0))
                + ")"
            )
    else:
        lines.append("- Todos los nombres DEF son unicos.")
    unresolved = report.get("unresolved_uses", []) or []
    if unresolved:
        for item in unresolved:
            lines.append(
                "- USE sin DEF: `"
                + str(item.get("name", ""))
                + "` ("
                + _format_int(item.get("occurrences", 0))
                + ")"
            )
    else:
        lines.append("- No se detectaron referencias USE sin DEF.")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "ANALYZER_VERSION",
    "AnalysisCancelled",
    "analyze_x3d",
    "report_paths",
    "write_reports",
]
