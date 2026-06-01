"""
Script principal do extrator de músicas do Instagram (@lembradessesom).

Fluxo:
  1. Lê URLs do arquivo de input
  2. Para cada URL pendente:
     a. Baixa o vídeo (menor qualidade)
     b. Extrai frames a cada N segundos via OpenCV
     c. Aplica OCR em cada frame
     d. Parseia texto → lista de {song, artist}
     e. Opcionalmente normaliza títulos via MusicBrainz API
     f. Salva no progress.json e no extracted_songs.json

Uso:
  uv run extractor                        # processa URLs pendentes
  uv run extractor --normalize            # ativa normalização via MusicBrainz
  uv run extractor --retry-failed         # reprocessa URLs falhadas
  uv run extractor --reset-url <url>      # reprocessa URL específica
  uv run extractor --stats                # exibe estatísticas
  uv run extractor --no-gpu               # desativa GPU no EasyOCR
  uv run extractor --limit 5              # processa apenas 5 URLs
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import (
    INPUT_FILE,
    PROGRESS_FILE,
    RESULTS_FILE,
    FRAMES_DIR,
    REQUEST_DELAY,
    OCR_LANGUAGES,
    OCR_CONFIDENCE_THRESHOLD,
    OCR_MAX_WIDTH,
    YTDLP_RETRIES,
    FRAME_INTERVAL_SEC,
)
from .downloader import InstagramDownloader
from .normalizer import MusicBrainzNormalizer
from .ocr import OCRExtractor
from .parser import SongParser
from .progress import ProgressTracker

# ------------------------------------------------------------------ #
# Logging                                                              #
# ------------------------------------------------------------------ #

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
logger = logging.getLogger("extractor")


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #


def load_urls(filepath: Path) -> list[str]:
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def save_results(results: list, filepath: Path):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"Resultados salvos: {filepath} ({len(results)} registros)")


def print_stats(progress: ProgressTracker, total: int):
    processed = progress.processed_count
    failed = progress.failed_count
    pending = total - processed
    print(
        f"\n{'='*55}\n"
        f"  Total de URLs     : {total}\n"
        f"  Processados       : {processed}\n"
        f"  Falhados          : {failed}\n"
        f"  Pendentes         : {max(0, pending - failed)}\n"
        f"  Total de músicas  : {sum(len(r.get('songs', [])) for r in progress.results)}\n"
        f"{'='*55}\n"
    )


# ------------------------------------------------------------------ #
# Processamento                                                         #
# ------------------------------------------------------------------ #


def process_urls(
    urls: list[str],
    progress: ProgressTracker,
    downloader: InstagramDownloader,
    ocr: OCRExtractor,
    parser: SongParser,
    normalizer: MusicBrainzNormalizer | None = None,
):
    total = len(urls)
    logger.info(f"Iniciando processamento de {total} URL(s)...")
    success = 0
    fail = 0

    for i, url in enumerate(urls, 1):
        logger.info(f"[{i}/{total}] {url}")

        try:
            # 1. Baixa vídeo e extrai frames
            data = downloader.fetch(url)
            frames: list[Path] = data["frames"]
            caption: str = data["caption"]
            reel_id: str = data["reel_id"]
            logger.info(
                f"  {len(frames)} frames | duração: {data.get('duration') or '?'}s"
            )
            logger.info(f"  Caption: {caption[:120]!r}")

            # 2. OCR em cada frame
            frame_texts = []
            for frame_path in frames:
                text = ocr.get_full_text(frame_path)
                if text.strip():
                    frame_texts.append(text)
                    logger.debug(f"  Frame {frame_path.name}: {text[:80]!r}")

            logger.info(f"  Frames com texto: {len(frame_texts)}/{len(frames)}")

            # 3. Parse → lista de músicas (OCR bruto)
            songs = parser.parse_frames(frame_texts, caption=caption)
            logger.info(f"  Músicas OCR: {len(songs)}")
            for s in songs:
                logger.info(
                    f"    - {s['song']!r} / {s['artist']!r} [{s['confidence']}]"
                )

            # 4. Normalização via MusicBrainz (opcional)
            if normalizer and songs:
                logger.info("  Normalizando via MusicBrainz...")
                songs = normalizer.normalize_batch(songs)
                logger.info(f"  Músicas normalizadas: {len(songs)}")
                for s in songs:
                    mb = f"score={s.get('mb_score',0)}"
                    logger.info(
                        f"    - {s['song']!r} / {s['artist']!r} [{mb}]"
                    )

            # 5. Registra progresso
            progress.mark_success(
                url=url,
                reel_id=reel_id,
                songs=songs,
                caption=caption,
                raw_ocr_frames=frame_texts,
            )
            success += 1

        except Exception as exc:
            logger.error(f"  ERRO: {exc}", exc_info=True)
            progress.mark_failed(url, str(exc))
            fail += 1

    logger.info(f"Lote concluído: {success} OK | {fail} erros")
    return success, fail


# ------------------------------------------------------------------ #
# Entrypoint                                                           #
# ------------------------------------------------------------------ #


def main():
    ap = argparse.ArgumentParser(description="Extrator de músicas – @lembradessesom")
    ap.add_argument(
        "--retry-failed",
        action="store_true",
        help="Reprocessa todas as URLs que falharam",
    )
    ap.add_argument(
        "--reset-url",
        metavar="URL",
        help="Remove URL específica do progresso para reprocessamento",
    )
    ap.add_argument(
        "--stats",
        action="store_true",
        help="Exibe estatísticas e sai",
    )
    ap.add_argument(
        "--no-gpu",
        action="store_true",
        help="Desativa GPU no EasyOCR (usa CPU)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limita número de URLs a processar (0 = todas)",
    )
    ap.add_argument(
        "--normalize",
        action="store_true",
        help="Normaliza títulos via MusicBrainz API após extração OCR",
    )
    ap.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        default=None,
        help="Usa cookies do browser para acessar reels restritos (ex: chrome, firefox)",
    )
    ap.add_argument(
        "--cookies",
        metavar="FILE",
        default=None,
        help=(
            "Arquivo de cookies no formato Netscape/Mozilla "
            "(gerado por extensões como 'Get cookies.txt LOCALLY'). "
            "Recomendado ao rodar via WSL com Chrome/Firefox no Windows."
        ),
    )
    args = ap.parse_args()

    logger.info("=" * 60)
    logger.info("Extrator lembradessesom iniciado")
    logger.info("=" * 60)

    all_urls = load_urls(INPUT_FILE)
    logger.info(f"Arquivo de entrada: {INPUT_FILE} ({len(all_urls)} URLs)")

    progress = ProgressTracker(PROGRESS_FILE)

    if args.stats:
        print_stats(progress, len(all_urls))
        return

    if args.reset_url:
        progress.reset_url(args.reset_url)

    if args.retry_failed:
        progress.reset_failed()

    downloader = InstagramDownloader(
        frames_dir=FRAMES_DIR,
        delay=REQUEST_DELAY,
        retries=YTDLP_RETRIES,
        frame_interval_sec=FRAME_INTERVAL_SEC,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=Path(args.cookies) if args.cookies else None,
    )
    if args.cookies:
        logger.info(f"Cookies de arquivo: {args.cookies}")
    elif args.cookies_from_browser:
        logger.info(f"Cookies do browser: {args.cookies_from_browser}")
    ocr = OCRExtractor(
        languages=OCR_LANGUAGES,
        confidence_threshold=OCR_CONFIDENCE_THRESHOLD,
        gpu=not args.no_gpu,
        max_width=OCR_MAX_WIDTH,
    )
    parser = SongParser()
    normalizer = MusicBrainzNormalizer() if args.normalize else None
    if normalizer:
        logger.info("Normalização MusicBrainz ativada")

    pending = [u for u in all_urls if not progress.is_processed(u)]
    logger.info(
        f"Status: {progress.processed_count} processados | "
        f"{len(pending)} pendentes | "
        f"{progress.failed_count} falhados"
    )

    if not pending:
        logger.info("Nenhuma URL pendente. Use --retry-failed para reprocessar erros.")
        print_stats(progress, len(all_urls))
        return

    if args.limit:
        pending = pending[: args.limit]
        logger.info(f"Limite: {args.limit} URLs")

    process_urls(pending, progress, downloader, ocr, parser, normalizer=normalizer)

    save_results(progress.results, RESULTS_FILE)
    print_stats(progress, len(all_urls))


if __name__ == "__main__":
    main()
