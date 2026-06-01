"""
Downloader de vídeos de reels do Instagram via yt-dlp.
Baixa o vídeo na menor qualidade disponível, extrai frames com OpenCV
e depois apaga o vídeo para economizar espaço em disco.
"""

import logging
import shutil
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
import yt_dlp

logger = logging.getLogger(__name__)


def _reel_id(url: str) -> str:
    """Extrai o ID do reel da URL. Ex: .../reel/ABC123/ → ABC123"""
    return url.rstrip("/").split("/")[-1]


class InstagramDownloader:
    def __init__(
        self,
        frames_dir: Path,
        delay: float = 3.0,
        retries: int = 3,
        frame_interval_sec: float = 2.0,
        cookies_from_browser: str | None = None,
        cookies_file: Path | None = None,
    ):
        """
        frames_dir           : diretório onde os frames serão salvos (subpastas por reel_id)
        delay                : pausa entre requisições para evitar bloqueio
        retries              : número de tentativas em caso de erro
        frame_interval_sec   : intervalo em segundos entre frames extraídos do vídeo
        cookies_from_browser : nome do browser cujos cookies serão usados (ex: "chrome", "firefox")
                               Funciona apenas quando o browser roda no mesmo sistema (Linux nativo).
        cookies_file         : caminho para arquivo de cookies no formato Netscape/Mozilla
                               (gerado por extensões como "Get cookies.txt LOCALLY").
                               Preferido ao cookies_from_browser quando rodando via WSL.
        """
        self.frames_dir = frames_dir
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.retries = retries
        self.frame_interval_sec = frame_interval_sec
        self.cookies_from_browser = cookies_from_browser
        self.cookies_file = cookies_file

    # ------------------------------------------------------------------ #
    # Público                                                              #
    # ------------------------------------------------------------------ #

    def fetch(self, url: str) -> dict:
        """
        Baixa o vídeo, extrai frames e apaga o vídeo.

        Retorna:
        {
          "reel_id"    : str,
          "frames"     : [Path, ...],   # caminhos dos frames extraídos
          "caption"    : str,           # descrição/legenda do post
          "title"      : str,
          "duration"   : float | None,  # duração em segundos
        }
        """
        rid = _reel_id(url)
        reel_frames_dir = self.frames_dir / rid

        # Se já foi processado (frames existem), reaproveita
        if reel_frames_dir.exists() and any(reel_frames_dir.iterdir()):
            frames = sorted(reel_frames_dir.glob("*.jpg"))
            logger.info(f"Frames já existem para {rid}: {len(frames)} frames")
            return {
                "reel_id": rid,
                "frames": frames,
                "caption": "",
                "title": "",
                "duration": None,
            }

        reel_frames_dir.mkdir(parents=True, exist_ok=True)

        last_error = None
        info = {}
        for attempt in range(1, self.retries + 1):
            try:
                info = self._extract_info(url)
                break
            except Exception as e:
                last_error = e
                logger.warning(f"Tentativa {attempt}/{self.retries} para {rid}: {e}")
                if attempt < self.retries:
                    time.sleep(self.delay * attempt)
        else:
            raise RuntimeError(
                f"Falha ao extrair info de {url} após {self.retries} tentativas: {last_error}"
            )

        # Baixa o vídeo em diretório temporário
        frames = []
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = self._download_video(url, Path(tmpdir))
            if video_path:
                frames = self._extract_frames(video_path, reel_frames_dir)

        if not frames:
            raise ValueError(f"Nenhum frame extraído para {rid}")

        time.sleep(self.delay)

        return {
            "reel_id": rid,
            "frames": frames,
            "caption": info.get("description") or info.get("title") or "",
            "title": info.get("title") or "",
            "duration": info.get("duration"),
        }

    # ------------------------------------------------------------------ #
    # Privado                                                              #
    # ------------------------------------------------------------------ #

    def _apply_cookie_opts(self, ydl_opts: dict) -> None:
        """Aplica opções de cookies ao dict de opções do yt-dlp.

        Prioridade:
          1. cookies_file  — arquivo Netscape exportado manualmente (recomendado no WSL)
          2. cookies_from_browser — lê direto do browser (só funciona em Linux nativo)
        """
        if self.cookies_file:
            ydl_opts["cookiefile"] = str(self.cookies_file)
        elif self.cookies_from_browser:
            ydl_opts["cookiesfrombrowser"] = (self.cookies_from_browser,)

    def _extract_info(self, url: str) -> dict:
        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
        self._apply_cookie_opts(ydl_opts)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return info or {}

    def _download_video(self, url: str, dest_dir: Path) -> Path | None:
        """Baixa o vídeo na menor qualidade disponível."""
        ydl_opts = {
            # Menor qualidade para economizar banda
            "format": "worst[ext=mp4]/worst/bestvideo[height<=480]+bestaudio/best[height<=480]/best",
            "outtmpl": str(dest_dir / "video.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        self._apply_cookie_opts(ydl_opts)
        logger.debug(f"Baixando vídeo de {url}...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Encontra o arquivo baixado
        video_files = list(dest_dir.glob("video.*"))
        if not video_files:
            return None
        video_path = video_files[0]
        logger.debug(f"Vídeo baixado: {video_path.name} ({video_path.stat().st_size // 1024}KB)")
        return video_path

    def _extract_frames(self, video_path: Path, output_dir: Path) -> list[Path]:
        """Extrai frames do vídeo em intervalos regulares."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Não foi possível abrir o vídeo: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps

        frame_step = max(1, int(fps * self.frame_interval_sec))
        saved = []
        frame_idx = 0
        frame_num = 0

        logger.debug(
            f"Vídeo: {duration:.1f}s | {fps:.1f}fps | "
            f"Extraindo 1 frame a cada {self.frame_interval_sec}s"
        )

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % frame_step == 0:
                out_path = output_dir / f"frame_{frame_num:04d}.jpg"
                cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                saved.append(out_path)
                frame_num += 1
            frame_idx += 1

        cap.release()
        logger.info(f"Frames extraídos: {len(saved)} (de {duration:.1f}s de vídeo)")
        return saved
