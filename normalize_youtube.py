"""
Normaliza os títulos/artistas em youtube_songs.json via MusicBrainz.

Uso:
  uv run python normalize_youtube.py
  uv run python normalize_youtube.py --limit 50   # testa com 50
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from extractor.normalizer import MusicBrainzNormalizer

YOUTUBE_SONGS = Path(__file__).parent / "output" / "youtube_songs.json"
LOG_FILE = Path(__file__).parent / "output" / "normalize.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("normalize")


def save(songs: list, path: Path):
    path.write_text(json.dumps(songs, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Normaliza youtube_songs.json via MusicBrainz")
    ap.add_argument("--limit", type=int, default=0, help="Limita número de buscas (0 = todas)")
    ap.add_argument("--input", type=Path, default=YOUTUBE_SONGS)
    args = ap.parse_args()

    songs: list[dict] = json.loads(args.input.read_text(encoding="utf-8"))

    to_normalize = [s for s in songs if not s.get("normalized")]
    logger.info(f"Total: {len(songs)} | já normalizados: {len(songs) - len(to_normalize)} | a fazer: {len(to_normalize)}")

    if args.limit:
        to_normalize = to_normalize[: args.limit]
        logger.info(f"Limite: {args.limit}")

    normalizer = MusicBrainzNormalizer()

    # Índice para atualização in-place
    key_map: dict[tuple[str, str], int] = {}
    for i, s in enumerate(songs):
        key_map[(s["song"].lower().strip(), s["artist"].lower().strip())] = i

    done = skipped = failed = 0

    for idx, song in enumerate(to_normalize, 1):
        logger.info(f"[{idx}/{len(to_normalize)}] {song['song']!r} / {song['artist']!r}")
        try:
            result = normalizer.normalize_song(song["song"], song["artist"])
        except Exception as e:
            logger.warning(f"  Erro: {e}")
            failed += 1
            continue

        orig_key = (song["song"].lower().strip(), song["artist"].lower().strip())
        pos = key_map.get(orig_key)

        if pos is None:
            logger.warning(f"  Chave não encontrada no índice: {orig_key}")
            failed += 1
            continue

        entry = songs[pos]
        entry["song"] = result["song"]
        entry["artist"] = result["artist"]
        entry["mb_id"] = result.get("mb_id", "")
        entry["normalized"] = result.get("normalized", False)

        if result.get("normalized"):
            logger.info(f"  → {result['song']!r} / {result['artist']!r} (score={result.get('mb_score',0)})")
            done += 1
        else:
            logger.info(f"  → Não encontrado no MB, mantendo pré-limpo: {result['song']!r}")
            skipped += 1

        # Salva progresso a cada 10 entradas
        if idx % 10 == 0:
            save(songs, args.input)
            logger.info(f"  Progresso salvo ({idx}/{len(to_normalize)})")

    save(songs, args.input)

    logger.info("=" * 55)
    logger.info(f"Concluído: {done} normalizados | {skipped} não encontrados no MB | {failed} erros")
    logger.info(f"Total com normalized=True: {sum(1 for s in songs if s.get('normalized'))}/{len(songs)}")


if __name__ == "__main__":
    main()
