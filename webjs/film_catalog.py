"""Catalog and source resolver for the optional Film & Series Studio integration.

The page URL alone is not a video file; we use a provider library to expose
actual season/episode/translation choices. No DRM or access-control bypass.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


def validate_url(url: str) -> str:
    url = str(url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ("hdrezka.rest", "www.hdrezka.rest"):
        raise ValueError("Для каталога нужна HTTPS-ссылка с hdrezka.rest.")
    if parsed.username or parsed.password or parsed.port:
        raise ValueError("Неверный адрес.")
    if not parsed.path.endswith(".html"):
        raise ValueError("Укажи ссылку на страницу фильма или сериала, а не главную сайта.")
    return url


def get_client(url: str):
    try:
        from HdRezkaApi import HdRezkaApi
    except ImportError as exc:
        raise RuntimeError(
            "Не установлен HdRezkaApi. Выполни: .\\.venv\\Scripts\\python.exe -m pip install HdRezkaApi"
        ) from exc
    api = HdRezkaApi(validate_url(url))
    if not api.ok:
        raise RuntimeError("Сайт не отдал каталог: " + str(api.exception)[:350])
    return api


def catalog(url: str) -> dict:
    api = get_client(url)
    translations = getattr(api, "translators", {}) or {}
    voices = []
    if isinstance(translations, dict):
        for key, item in translations.items():
            if isinstance(item, dict):
                name = str(item.get("name", key))
                premium = bool(item.get("premium", False))
            else:
                name, premium = str(item), False
            voices.append({"id": str(key), "name": name, "premium": premium})

    seasons = []
    episode_info = getattr(api, "episodesInfo", None) or []
    if isinstance(episode_info, (list, tuple)):
        for entry in episode_info:
            if not isinstance(entry, dict):
                continue
            season_id = str(entry.get("season", "")).strip()
            if not season_id:
                continue
            episodes = []
            for item in entry.get("episodes") or []:
                if not isinstance(item, dict):
                    continue
                episode_id = str(item.get("episode", "")).strip()
                if episode_id:
                    episodes.append({
                        "id": episode_id,
                        "name": str(item.get("episode_text") or "Серия " + episode_id),
                        "voices": [
                            str(voice.get("translator_id")) for voice in item.get("translations", [])
                            if isinstance(voice, dict) and voice.get("translator_id") is not None
                        ],
                    })
            seasons.append({
                "id": season_id,
                "name": str(entry.get("season_text") or "Сезон " + season_id),
                "episodes": episodes,
            })

    if not seasons:
        series_info = getattr(api, "seriesInfo", None) or {}
        combined = {}
        if isinstance(series_info, dict):
            for voice_data in series_info.values():
                if not isinstance(voice_data, dict):
                    continue
                for season_id, episodes in (voice_data.get("episodes") or {}).items():
                    sid = str(season_id)
                    combined.setdefault(sid, set()).update(str(n) for n in episodes)
        for sid in sorted(combined, key=lambda s: int(s) if s.isdigit() else s):
            seasons.append({
                "id": sid,
                "name": "Сезон " + sid,
                "episodes": [
                    {"id": episode_id, "name": "Серия " + episode_id, "voices": []}
                    for episode_id in sorted(combined[sid], key=lambda s: int(s) if s.isdigit() else s)
                ],
            })

    return {
        "ok": True,
        "title": str(getattr(api, "name", "") or "Фильм / сериал"),
        "type": "series" if seasons else "movie",
        "source": "hdrezka.rest",
        "seasons": seasons,
        "voices": voices,
        "notice": "Доступность серий и озвучек зависит от сайта. Защищённые и недоступные потоки не обходятся.",
    }


def stream_url(url: str, season: str = "", episode: str = "", voice: str = "") -> tuple[str, str]:
    """Return best available accessible stream URL and its advertised resolution."""
    api = get_client(url)
    choices = catalog_from_client(api)
    voice_ids = {str(v["id"]) for v in choices}
    if voice and voice not in voice_ids:
        raise ValueError("Выбрана неизвестная озвучка.")
    kw = {"translation": voice} if voice else {}
    if season and episode:
        stream = api.getStream(str(season), str(episode), **kw)
    else:
        stream = api.getStream(**kw)
    videos = getattr(stream, "videos", {}) or {}
    if not isinstance(videos, dict) or not videos:
        raise RuntimeError("Для выбранной серии сайт не предоставил доступный видеопоток.")
    def height(label):
        match = re.search(r"(\d{3,4})", str(label))
        return int(match.group(1)) if match else 0
    for res in sorted(videos.keys(), key=height, reverse=True):
        candidates = videos[res]
        for video_url in candidates if isinstance(candidates, (list, tuple)) else [candidates]:
            value = str(video_url or "")
            parsed = urlparse(value)
            if parsed.scheme == "https" and parsed.hostname:
                return value, str(res)
    raise RuntimeError("Доступные видеопотоки отсутствуют или имеют неподдерживаемый адрес.")


def catalog_from_client(api) -> list[dict]:
    result = []
    for key, val in (getattr(api, "translators", {}) or {}).items():
        result.append({"id": str(key), "name": str(val.get("name", key)) if isinstance(val, dict) else str(val)})
    return result
