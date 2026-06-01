"""
CLI para buscar URLs do YouTube para as músicas extraídas.

Uso:
  uv run extractor-youtube                        # busca todas (confidence>=medium)
  uv run extractor-youtube --limit 20             # testa com 20 buscas
  uv run extractor-youtube --min-confidence low   # inclui baixa confiança também
  uv run extractor-youtube --delay 1.0            # intervalo maior entre buscas
  uv run extractor-youtube --retry-not-found      # retenta entradas que falharam
  uv run extractor-youtube --stats                # exibe estatísticas e sai
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import RESULTS_FILE

LOG_FILE = Path(__file__).parent.parent / "output" / "extractor.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("extractor.youtube")

YOUTUBE_SONGS_FILE = RESULTS_FILE.parent / "youtube_songs.json"


def _print_stats(input_path: Path):
    data = json.loads(input_path.read_text(encoding="utf-8"))
    total_songs = 0
    with_url = 0
    medium_songs = 0
    for rec in data:
        for s in rec.get("songs", []):
            total_songs += 1
            if s.get("confidence") in ("medium", "high"):
                medium_songs += 1
            if s.get("youtube_url"):
                with_url += 1

    flat_path = YOUTUBE_SONGS_FILE
    flat_count = 0
    if flat_path.exists():
        flat_count = len(json.loads(flat_path.read_text(encoding="utf-8")))

    print(
        f"\n{'='*55}\n"
        f"  Reels processados    : {len(data)}\n"
        f"  Total de músicas     : {total_songs}\n"
        f"  Confidence >= medium : {medium_songs}\n"
        f"  Com youtube_url      : {with_url}\n"
        f"  Músicas únicas (flat): {flat_count}\n"
        f"{'='*55}\n"
    )


def main():
    ap = argparse.ArgumentParser(
        description="Busca URLs do YouTube para as músicas extraídas"
    )
    ap.add_argument(
        "--input",
        type=Path,
        default=RESULTS_FILE,
        help=f"Arquivo JSON de entrada (padrão: {RESULTS_FILE})",
    )
    ap.add_argument(
        "--min-confidence",
        choices=["low", "medium", "high"],
        default="medium",
        help="Confiança mínima das músicas a buscar (padrão: medium)",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=0.8,
        help="Intervalo em segundos entre buscas (padrão: 0.8)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limite de novas buscas a fazer nesta sessão (0 = sem limite)",
    )
    ap.add_argument(
        "--stats",
        action="store_true",
        help="Exibe estatísticas e sai",
    )
    ap.add_argument(
        "--retry-not-found",
        action="store_true",
        help="Retenta músicas que falharam com queries limpas (remove junk OCR)",
    )
    args = ap.parse_args()

    if not args.input.exists():
        logger.error(f"Arquivo não encontrado: {args.input}")
        sys.exit(1)

    if args.stats:
        _print_stats(args.input)
        return

    from . import youtube_search as ys

    logger.info("=" * 60)

    if args.retry_not_found:
        logger.info("Retry de músicas não encontradas")
        logger.info("=" * 60)
        logger.info(f"Entrada: {args.input}")
        logger.info(f"Delay: {args.delay}s")
        if args.limit:
            logger.info(f"Limite: {args.limit} buscas")

        stats = ys.retry_not_found(
            input_path=args.input,
            results_path=args.input,
            flat_output_path=YOUTUBE_SONGS_FILE,
            delay=args.delay,
            max_searches=args.limit,
        )

        logger.info("=" * 60)
        logger.info(
            f"Retry concluído: {stats['recovered']} recuperados / "
            f"{stats['tried']} tentativas / "
            f"{stats['still_failed']} ainda sem URL"
        )
        _print_stats(args.input)
        return

    logger.info("Busca YouTube iniciada")
    logger.info("=" * 60)
    logger.info(f"Entrada: {args.input}")
    logger.info(f"Confidence mínima: {args.min_confidence}")
    logger.info(f"Delay: {args.delay}s")
    if args.limit:
        logger.info(f"Limite: {args.limit} buscas")

    stats = ys.enrich_with_youtube(
        input_path=args.input,
        results_path=args.input,          # atualiza in-place
        flat_output_path=YOUTUBE_SONGS_FILE,
        min_confidence=args.min_confidence,
        delay=args.delay,
        max_searches=args.limit,
    )

    logger.info("=" * 60)
    logger.info(
        f"Concluído: {stats['found']} encontrados / "
        f"{stats['searched']} buscas novas / "
        f"{stats['skipped_cache']} do cache / "
        f"{stats['errors']} não encontrados"
    )
    _print_stats(args.input)


if __name__ == "__main__":
    main()
