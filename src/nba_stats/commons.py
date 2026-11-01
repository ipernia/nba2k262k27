"""Consulta y valida assets con licencia individual en Wikimedia Commons."""

from __future__ import annotations

import csv
import html
import json
import logging
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class CommonsAssetError(RuntimeError):
    """Error al consultar o validar un recurso multimedia de Commons."""


class CommonsRequestError(CommonsAssetError):
    """Error transitorio al acceder a la API o a una imagen de Commons."""


@dataclass(frozen=True)
class CommonsAsset:
    """URL de imagen con página, licencia y atribución obtenidas de Commons."""

    file_title: str
    image_url: str
    page_url: str
    mime_type: str
    license_name: str
    attribution: str


class ReadableResponse(Protocol):
    """Interfaz mínima para respuestas HTTP consumibles."""

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


class ImageResponse(ReadableResponse, Protocol):
    """Respuesta HTTP de imagen con información para su validación."""

    @property
    def status(self) -> int | None: ...

    @property
    def url(self) -> str | None: ...

    @property
    def headers(self) -> Mapping[str, str]: ...


JsonOpener = Callable[[Request, float], ReadableResponse]
ImageOpener = Callable[[Request, float], ImageResponse]

_API_URL = "https://commons.wikimedia.org/w/api.php"
_LOGGER = logging.getLogger(__name__)
_USER_AGENT = (
    "NBA-Local-Stats/0.1 "
    "(https://github.com/ipernia/nba2k262k27; read-only asset metadata)"
)
_CC_LICENSE_PATTERN = re.compile(r"CC BY(?:-SA)?(?: \d+(?:\.\d+)?)?$", re.IGNORECASE)
_TAG_PATTERN = re.compile(r"<[^>]*>")


def fetch_commons_asset(
    file_title: str,
    *,
    timeout_seconds: float = 20,
    max_attempts: int = 3,
    retry_delay_seconds: float = 2,
    json_opener: JsonOpener | None = None,
    image_opener: ImageOpener | None = None,
) -> CommonsAsset:
    """Obtiene metadatos de licencia y verifica el enlace directo a la imagen.

    Solo acepta imágenes con licencia CC0, CC BY, CC BY-SA o dominio público.
    No busca ni decide a qué jugador/equipo corresponde el archivo: esa
    asociación debe revisarse y registrarse manualmente en el manifiesto.
    """
    normalized_title = _normalize_file_title(file_title)
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds debe ser mayor que cero.")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise ValueError("max_attempts debe ser un entero mayor que cero.")
    if max_attempts < 1:
        raise ValueError("max_attempts debe ser un entero mayor que cero.")
    if (
        isinstance(retry_delay_seconds, bool)
        or not isinstance(retry_delay_seconds, (int, float))
        or not math.isfinite(retry_delay_seconds)
        or retry_delay_seconds < 0
    ):
        raise ValueError("retry_delay_seconds debe ser finito y no negativo.")
    if json_opener is None:
        json_opener = _open_json
    if image_opener is None:
        image_opener = _open_image

    params = urlencode(
        {
            "action": "query",
            "titles": normalized_title,
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "format": "json",
        }
    )
    request = Request(
        f"{_API_URL}?{params}",
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    payload = _request_json(
        request,
        normalized_title,
        timeout_seconds,
        max_attempts,
        retry_delay_seconds,
        json_opener,
    )

    if not isinstance(payload, Mapping):
        raise CommonsAssetError("Commons devolvió una respuesta JSON inválida.")
    query = payload.get("query")
    pages = query.get("pages", {}) if isinstance(query, Mapping) else {}
    if not isinstance(pages, Mapping):
        raise CommonsAssetError("Commons devolvió una lista de archivos inválida.")
    page = next(iter(pages.values()), None)
    if not isinstance(page, Mapping) or "missing" in page:
        raise CommonsAssetError(f"El archivo no existe en Commons: {normalized_title}")
    image_infos = page.get("imageinfo")
    if not isinstance(image_infos, list) or not image_infos:
        raise CommonsAssetError(
            f"Commons no devolvió información de imagen para {normalized_title}."
        )
    info = image_infos[0]
    if not isinstance(info, Mapping):
        raise CommonsAssetError("Commons devolvió metadatos de imagen inválidos.")

    image_url = _canonical_image_url(info.get("url"))
    mime_type = info.get("mime")
    supported_mime_types = {
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/svg+xml",
        "image/webp",
    }
    if (
        not isinstance(mime_type, str)
        or mime_type.casefold() not in supported_mime_types
    ):
        raise CommonsAssetError(
            f"El formato de imagen no está admitido (MIME: {mime_type!r})."
        )
    metadata = info.get("extmetadata", {})
    if not isinstance(metadata, Mapping):
        raise CommonsAssetError("Commons no devolvió metadatos de licencia válidos.")
    license_name = _metadata_text(metadata.get("LicenseShortName"))
    if not _is_allowed_license(license_name):
        raise CommonsAssetError(
            f"Licencia no aprobada o no disponible para {normalized_title}: "
            f"{license_name or 'sin licencia'}."
        )
    attribution = _metadata_text(metadata.get("Artist"))
    if not attribution:
        attribution = _metadata_text(metadata.get("Credit"))
    if not attribution:
        raise CommonsAssetError(
            f"Commons no proporciona atribución para {normalized_title}."
        )

    title = page.get("title")
    if not isinstance(title, str):
        title = normalized_title
    page_url = "https://commons.wikimedia.org/wiki/" + quote(
        title.replace(" ", "_"), safe=":_()!,.-"
    )
    _verify_direct_image(
        image_url,
        mime_type,
        timeout_seconds,
        max_attempts,
        retry_delay_seconds,
        image_opener,
    )
    return CommonsAsset(
        file_title=title,
        image_url=image_url,
        page_url=page_url,
        mime_type=mime_type,
        license_name=license_name,
        attribution=attribution,
    )


def load_asset_manifest(path: Path) -> list[dict[str, str]]:
    """Carga las asociaciones revisadas manualmente del manifiesto Commons."""
    required_columns = {
        "ASSET_TYPE",
        "ENTITY_ID",
        "SEASON_ID",
        "EDITION",
        "FILE_TITLE",
    }
    if not path.exists():
        raise CommonsAssetError(f"No existe el manifiesto de imágenes: {path}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if (
                reader.fieldnames is None
                or not required_columns.issubset(reader.fieldnames)
                or len(set(reader.fieldnames)) != len(reader.fieldnames)
            ):
                raise CommonsAssetError(
                    f"El manifiesto {path} debe contener las columnas: "
                    + ", ".join(sorted(required_columns))
                )
            rows: list[dict[str, str]] = []
            seen: set[tuple[str, str, str, str]] = set()
            for index, raw_row in enumerate(reader, start=2):
                if None in raw_row or any(
                    raw_row.get(column) is None for column in required_columns
                ):
                    raise CommonsAssetError(
                        f"Columnas o valores incompletos en {path}, línea {index}."
                    )
                row = {key: (value or "").strip() for key, value in raw_row.items()}
                asset_type = row["ASSET_TYPE"].upper()
                if asset_type not in {"JERSEY", "PLAYER_FACE", "TEAM_LOGO"}:
                    raise CommonsAssetError(
                        f"Tipo de asset no admitido en {path}, línea {index}."
                    )
                if not row["ENTITY_ID"] or not row["FILE_TITLE"]:
                    raise CommonsAssetError(
                        f"Falta ENTITY_ID o FILE_TITLE en {path}, línea {index}."
                    )
                if not row["ENTITY_ID"].isdigit():
                    raise CommonsAssetError(
                        f"ENTITY_ID inválido ({path}, línea {index})."
                    )
                if asset_type == "JERSEY":
                    if (
                        not re.fullmatch(r"\d{4}-\d{2}", row["SEASON_ID"])
                        or (int(row["SEASON_ID"][:4]) + 1) % 100
                        != int(row["SEASON_ID"][-2:])
                        or not row["EDITION"]
                    ):
                        raise CommonsAssetError(
                            f"SEASON_ID o EDITION inválido ({path}, línea {index})."
                        )
                elif row["SEASON_ID"] or row["EDITION"]:
                    raise CommonsAssetError(
                        f"{asset_type} no debe tener temporada ni edición "
                        f"({path}, línea {index})."
                    )
                key = (
                    asset_type,
                    row["ENTITY_ID"],
                    row["SEASON_ID"],
                    row["EDITION"].upper(),
                )
                if key in seen:
                    raise CommonsAssetError(
                        f"Asset duplicado en {path}, línea {index}: {key}."
                    )
                seen.add(key)
                row["ASSET_TYPE"] = asset_type
                row["EDITION"] = row["EDITION"].upper()
                row["FILE_TITLE"] = _normalize_file_title(row["FILE_TITLE"])
                rows.append(row)
            return rows
    except (OSError, UnicodeError, csv.Error) as error:
        raise CommonsAssetError(
            f"No se pudo leer el manifiesto de imágenes {path}: {error}"
        ) from error


def _normalize_file_title(file_title: str) -> str:
    if not isinstance(file_title, str):
        raise CommonsAssetError("FILE_TITLE debe ser texto.")
    title = file_title.strip().replace("_", " ")
    if not title:
        raise CommonsAssetError("FILE_TITLE no puede estar vacío.")
    if not title.lower().startswith("file:"):
        title = f"File:{title}"
    return title


def _canonical_image_url(value: object) -> str:
    if not isinstance(value, str):
        raise CommonsAssetError("Commons no devolvió una URL directa de imagen.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != "upload.wikimedia.org"
        or not parsed.path.startswith("/")
    ):
        raise CommonsAssetError(
            "La URL de imagen no pertenece al servidor HTTPS de Wikimedia."
        )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _metadata_text(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    raw_value = value.get("value")
    if not isinstance(raw_value, str):
        return ""
    return html.unescape(_TAG_PATTERN.sub("", raw_value)).strip()


def _is_allowed_license(license_name: str) -> bool:
    if license_name.casefold() in {"cc0", "public domain"}:
        return True
    return bool(_CC_LICENSE_PATTERN.fullmatch(license_name.strip()))


def _verify_direct_image(
    image_url: str,
    expected_mime_type: str,
    timeout_seconds: float,
    max_attempts: int,
    retry_delay_seconds: float,
    image_opener: ImageOpener,
) -> None:
    request = Request(
        image_url,
        headers={"User-Agent": _USER_AGENT, "Range": "bytes=0-63"},
    )
    for attempt in range(1, max_attempts + 1):
        try:
            response = image_opener(request, timeout_seconds)
            try:
                status = response.status
                final_url = response.url
                content_type = response.headers.get("Content-Type", "")
                prefix = response.read(64)
            finally:
                _close_response(response)
        except (OSError, URLError) as error:
            if attempt == max_attempts:
                raise CommonsRequestError(
                    f"No se pudo comprobar la URL directa de la imagen tras "
                    f"{max_attempts} intentos: {error}"
                ) from error
            time.sleep(retry_delay_seconds)
            continue
        if status in (429, 500, 502, 503, 504):
            if attempt == max_attempts:
                raise CommonsRequestError(
                    f"Commons devolvió HTTP {status} al comprobar la imagen "
                    f"tras {max_attempts} intentos."
                )
            time.sleep(retry_delay_seconds)
            continue
        break
    else:
        raise CommonsRequestError("No se pudo validar la URL de imagen.")
    if status not in (200, 206):
        raise CommonsAssetError(f"URL de imagen no accesible (HTTP {status}).")
    if final_url and urlsplit(final_url).hostname != "upload.wikimedia.org":
        raise CommonsAssetError("La URL de imagen redirige fuera de Wikimedia.")
    if not content_type.casefold().startswith(expected_mime_type.casefold()):
        raise CommonsAssetError(
            f"El servidor no devolvió el MIME esperado {expected_mime_type!r}."
        )
    if not prefix:
        raise CommonsAssetError("La URL devolvió una imagen vacía.")
    if not _has_expected_signature(expected_mime_type, prefix):
        raise CommonsAssetError(
            f"El contenido no coincide con el formato {expected_mime_type!r}."
        )


def _has_expected_signature(mime_type: str, prefix: bytes) -> bool:
    if mime_type == "image/jpeg":
        return prefix.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return prefix.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/gif":
        return prefix.startswith((b"GIF87a", b"GIF89a"))
    if mime_type == "image/webp":
        return prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"
    if mime_type == "image/svg+xml":
        start = prefix.lstrip().lower()
        return start.startswith(b"<svg") or (
            start.startswith(b"<?xml") and b"<svg" in start
        )
    return False


def _close_response(response: ReadableResponse) -> None:
    try:
        response.close()
    except OSError as error:
        _LOGGER.warning("No se pudo cerrar una respuesta HTTP de Commons: %s", error)


def _request_json(
    request: Request,
    file_title: str,
    timeout_seconds: float,
    max_attempts: int,
    retry_delay_seconds: float,
    json_opener: JsonOpener,
) -> Mapping[str, object]:
    for attempt in range(1, max_attempts + 1):
        try:
            response = json_opener(request, timeout_seconds)
            try:
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                _close_response(response)
        except (OSError, UnicodeError, json.JSONDecodeError, URLError) as error:
            if attempt == max_attempts:
                raise CommonsRequestError(
                    f"No se pudieron consultar los metadatos de Commons para "
                    f"{file_title} tras {max_attempts} intentos: {error}"
                ) from error
            time.sleep(retry_delay_seconds)
            continue
        if isinstance(payload, Mapping):
            return payload
        raise CommonsAssetError("Commons devolvió una respuesta JSON inválida.")
    raise CommonsRequestError(f"No se obtuvo respuesta de Commons para {file_title}.")


def _open_json(request: Request, timeout_seconds: float) -> ReadableResponse:
    return urlopen(request, timeout=timeout_seconds)


def _open_image(request: Request, timeout_seconds: float) -> ImageResponse:
    return urlopen(request, timeout=timeout_seconds)
