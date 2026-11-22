"""Recupera una cartella Drops da un export del localStorage e riscarica le tracce.

Uso:
    python3 recover_folder.py EXPORT.json "jacopino" "/percorso/destinazione" [--dry-run]

L'export si ottiene dal browser dell'utente (chiavi `drops*` del localStorage).
Per ogni traccia: usa l'URL sorgente salvato; se manca, cerca "Artista - Titolo" su YouTube.
Scarica MP3 320k con yt-dlp + ffmpeg. Scrive report.csv con esito di ogni traccia.
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path


def load_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def track_key(t: dict) -> str:
    return str(t.get("id") or t.get("job_id") or "")


def source_url(t: dict) -> str:
    return t.get("sourceUrl") or t.get("source_url") or t.get("url") or ""


def collect_tracks(export: dict, folder_name: str) -> list[dict]:
    # Più cartelle separate da virgola: "jacopino,jacopino dance".
    targets = {n.strip().lower() for n in folder_name.split(",") if n.strip()}
    # Indice di tutte le tracce note (history, queue, drops_downloads) per risolvere riferimenti per id.
    index: dict[str, dict] = {}
    for key, raw in export.items():
        data = load_json(raw)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and track_key(item):
                    index.setdefault(track_key(item), item)

    found: list[dict] = []
    folder_hit = False
    for key in ("drops.folders.v1", "drops.indexed.folders.v1"):
        folders = load_json(export.get(key)) or []
        for folder in folders if isinstance(folders, list) else []:
            if not isinstance(folder, dict):
                continue
            if str(folder.get("name", "")).strip().lower() not in targets:
                continue
            folder_hit = True
            for t in folder.get("tracks") or folder.get("trackIds") or []:
                if isinstance(t, dict):
                    # La cronologia ha sourceUrl; la cartella no: unisci per id.
                    found.append({**t, **{k: v for k, v in index.get(track_key(t), {}).items() if v}})
                elif isinstance(t, (str, int)) and str(t) in index:
                    found.append(index[str(t)])
    if not folder_hit:
        names = set()
        for key in ("drops.folders.v1", "drops.indexed.folders.v1"):
            for f in load_json(export.get(key)) or []:
                if isinstance(f, dict):
                    names.add(str(f.get("name")))
        sys.exit(f"Cartella '{folder_name}' non trovata. Cartelle presenti: {sorted(names)}")

    # Dedup per URL o artista+titolo.
    seen, unique = set(), []
    for t in found:
        sig = (source_url(t) or f"{t.get('artist')}|{t.get('title')}").lower()
        if sig not in seen:
            seen.add(sig)
            unique.append(t)
    return unique


def safe_name(t: dict) -> str:
    artist = (t.get("artist") or t.get("artist_name") or "").strip()
    title = (t.get("title") or t.get("fileName") or t.get("file_name") or "").strip()
    title = re.sub(r"\.(mp3|wav|flac|m4a)$", "", title, flags=re.I)
    if artist and title and not title.lower().startswith(artist.lower()):
        name = f"{artist} - {title}"
    else:
        name = title or artist or track_key(t) or "traccia"
    return re.sub(r'[\\/:*?"<>|]+', "_", name)[:180]


def download(t: dict, dest: Path, dry: bool) -> tuple[str, str]:
    name = safe_name(t)
    if any(dest.glob(f"{glob_escape(name)}.*")):
        return "gia_presente", name
    url = source_url(t)
    if not url:
        query = name.replace(" - ", " ")
        if not query.strip():
            return "senza_dati", name
        url = f"ytsearch1:{query}"
    if dry:
        return "dry_run", f"{name} <- {url}"
    targets = [("ok", url)]
    # Se l'URL originale è morto, ritenta con ricerca per nome.
    if not url.startswith("ytsearch") and name:
        targets.append(("ok_da_ricerca", f"ytsearch1:{name.replace(' - ', ' ')}"))
    err = "errore sconosciuto"
    for status, target in targets:
        # Stessi client a cascata di downloader.py: aggirano i 403 di YouTube.
        for tier in PLAYER_TIERS:
            cmd = [
                "yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3", "--audio-quality", "320K",
                "--embed-metadata", "--retries", "3", "--extractor-args", tier,
                "-o", str(dest / f"{name}.%(ext)s"), target,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                return status, name
            err = (r.stderr.strip().splitlines() or [err])[-1]
    return "errore", f"{name}: {err[:200]}"


PLAYER_TIERS = (
    "youtube:player_client=mweb,tv,web_creator",
    "youtube:player_client=mweb,android",
    "youtube:player_client=android,ios",
)


def glob_escape(s: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", s)


def main() -> None:
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    export = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    folder, dest = sys.argv[2], Path(sys.argv[3]).expanduser()
    dry = "--dry-run" in sys.argv
    dest.mkdir(parents=True, exist_ok=True)
    tracks = collect_tracks(export, folder)
    print(f"{len(tracks)} tracce nella cartella '{folder}'")
    rows = []
    for i, t in enumerate(tracks, 1):
        status, info = download(t, dest, dry)
        print(f"[{i}/{len(tracks)}] {status}: {info}", flush=True)
        rows.append({"n": i, "esito": status, "traccia": info, "url": source_url(t)})
    report = dest / ("report_dry_run.csv" if dry else "report.csv")
    with report.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["n", "esito", "traccia", "url"])
        w.writeheader()
        w.writerows(rows)
    ok = sum(r["esito"].startswith("ok") or r["esito"] == "gia_presente" for r in rows)
    print(f"Fatto: {ok}/{len(rows)} recuperate. Report: {report}")


if __name__ == "__main__":
    main()
