"""
Extração de texto via EasyOCR.

Otimizações para CPU:
- Redimensiona frames para largura máxima configurável (menos pixels = mais rápido)
- Aumenta contraste para facilitar leitura de texto overlay
- EasyOCR inicializado de forma lazy (carregamento único)
"""

import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

logger = logging.getLogger(__name__)

_easyocr_reader = None


def _get_reader(languages: list[str], gpu: bool):
    global _easyocr_reader
    import easyocr  # lazy import

    if _easyocr_reader is None:
        logger.info("Inicializando EasyOCR (primeiro uso pode demorar alguns segundos)...")
        _easyocr_reader = easyocr.Reader(languages, gpu=gpu, verbose=False)
        logger.info("EasyOCR pronto.")
    return _easyocr_reader


class OCRExtractor:
    def __init__(
        self,
        languages: list[str] | None = None,
        confidence_threshold: float = 0.3,
        gpu: bool = True,
        max_width: int = 720,
    ):
        self.languages = languages or ["pt", "en"]
        self.confidence_threshold = confidence_threshold
        self.gpu = gpu
        self.max_width = max_width

    # ------------------------------------------------------------------ #
    # Público                                                              #
    # ------------------------------------------------------------------ #

    def extract(self, image_path: Path) -> list[dict]:
        """
        Extrai blocos de texto da imagem.
        Retorna [{"text": str, "confidence": float, "bbox": list}, ...]
        """
        img = self._preprocess(image_path)
        reader = _get_reader(self.languages, self.gpu)
        raw_results = reader.readtext(img)

        blocks = []
        for bbox, text, confidence in raw_results:
            text = text.strip()
            if text and confidence >= self.confidence_threshold:
                blocks.append(
                    {
                        "text": text,
                        "confidence": round(confidence, 3),
                        "bbox": [list(map(float, pt)) for pt in bbox],
                    }
                )

        # Ordena de cima para baixo pelo Y médio do bbox
        blocks.sort(key=lambda b: sum(pt[1] for pt in b["bbox"]) / 4)
        return blocks

    def get_full_text(self, image_path: Path) -> str:
        """Retorna todo o texto detectado, linha por linha."""
        blocks = self.extract(image_path)
        return "\n".join(b["text"] for b in blocks)

    # ------------------------------------------------------------------ #
    # Privado                                                              #
    # ------------------------------------------------------------------ #

    def _preprocess(self, image_path: Path) -> np.ndarray:
        """
        Preprocessa a imagem:
        1. Abre com PIL
        2. Redimensiona mantendo aspect ratio (limita largura a max_width)
        3. Aumenta contraste e nitidez
        4. Retorna numpy array para EasyOCR
        """
        img = Image.open(image_path).convert("RGB")

        # Redimensiona se necessário (mantém aspect ratio)
        w, h = img.size
        if w > self.max_width:
            scale = self.max_width / w
            new_w = self.max_width
            new_h = int(h * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        # Contraste e nitidez melhoram leitura de texto overlay
        img = ImageEnhance.Contrast(img).enhance(1.5)
        img = ImageEnhance.Sharpness(img).enhance(2.0)

        return np.array(img)
