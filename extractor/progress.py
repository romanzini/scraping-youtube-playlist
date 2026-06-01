"""
Controle de progresso: registra quais URLs já foram processadas,
quais falharam e guarda os resultados extraídos.

Arquivo de estado: output/progress.json
Estrutura:
{
  "processed": ["url1", ...],
  "failed": {"url2": {"error": "...", "failed_at": "..."}},
  "results": [
    {
      "url": "...",
      "reel_id": "...",
      "songs": [{"song": "...", "artist": "...", "confidence": "..."}],
      "caption": "...",
      "processed_at": "..."
    }
  ]
}
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ProgressTracker:
    def __init__(self, progress_file: Path):
        self.progress_file = progress_file
        self._data = self._load()

    def _load(self) -> dict:
        if self.progress_file.exists():
            with open(self.progress_file, encoding="utf-8") as f:
                data = json.load(f)
            logger.info(
                f"Progresso carregado: {len(data.get('processed', []))} processados, "
                f"{len(data.get('failed', {}))} falhados"
            )
            return data
        return {"processed": [], "failed": {}, "results": []}

    def _save(self):
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.progress_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # Consultas                                                            #
    # ------------------------------------------------------------------ #

    def is_processed(self, url: str) -> bool:
        return url in self._data["processed"]

    def is_failed(self, url: str) -> bool:
        return url in self._data.get("failed", {})

    @property
    def processed_count(self) -> int:
        return len(self._data["processed"])

    @property
    def failed_count(self) -> int:
        return len(self._data.get("failed", {}))

    @property
    def results(self) -> list:
        return self._data["results"]

    def get_failed_urls(self) -> list[str]:
        return list(self._data.get("failed", {}).keys())

    # ------------------------------------------------------------------ #
    # Atualizações                                                         #
    # ------------------------------------------------------------------ #

    def mark_success(
        self,
        url: str,
        reel_id: str,
        songs: list[dict],
        caption: str = "",
        raw_ocr_frames: list[str] | None = None,
    ):
        """Registra URL como processada com sucesso."""
        result = {
            "url": url,
            "reel_id": reel_id,
            "songs": songs,
            "songs_count": len(songs),
            "caption": caption,
            "raw_ocr_frames": raw_ocr_frames or [],
            "processed_at": datetime.now().isoformat(),
        }

        if url not in self._data["processed"]:
            self._data["processed"].append(url)

        existing = next(
            (r for r in self._data["results"] if r["url"] == url), None
        )
        if existing:
            existing.update(result)
        else:
            self._data["results"].append(result)

        self._data.setdefault("failed", {}).pop(url, None)
        self._save()

    def mark_failed(self, url: str, error: str):
        """Registra URL como falhada."""
        self._data.setdefault("failed", {})[url] = {
            "error": error,
            "failed_at": datetime.now().isoformat(),
        }
        self._save()

    def reset_failed(self):
        """Limpa todos os registros de falha para permitir reprocessamento."""
        count = len(self._data.get("failed", {}))
        self._data["failed"] = {}
        self._save()
        logger.info(f"{count} URLs falhadas liberadas para reprocessamento")

    def reset_url(self, url: str):
        """Remove uma URL específica do progresso para reprocessamento individual."""
        self._data["processed"] = [
            u for u in self._data["processed"] if u != url
        ]
        self._data["results"] = [
            r for r in self._data["results"] if r["url"] != url
        ]
        self._data.setdefault("failed", {}).pop(url, None)
        self._save()
        logger.info(f"URL resetada para reprocessamento: {url}")
