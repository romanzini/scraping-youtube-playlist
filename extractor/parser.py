"""
Parser de texto OCR para a conta @lembradessesom.

Formato identificado: cada frame mostra uma lista enumerada progressiva:
  01 DRIVE
  THE CARS
  02 TIEDAFTERTIME
  CYNDI LAUPER
  ...

Estratégia:
1. Detecta linhas com padrão "NN TÍTULO" (número + nome da música)
2. A linha seguinte (sem número) é o artista
3. Usa o frame com mais entradas como fonte principal
4. Deduplicação via normalização de texto
"""

import logging
import re
import unicodedata
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Padrões                                                              #
# ------------------------------------------------------------------ #

# Linha de música numerada: "01 DRIVE", "02 TIME AFTER TIME"
# Também trata artefatos comuns: "U9" (→09), "0b" (→03), "9b" (→03)
_NUMBERED_SONG_RE = re.compile(r"^\s*([0O][0-9]|[0-9]{1,2}|[UuOo][0-9])\s+(.+)$")

def _parse_number(raw: str) -> int:
    """Converte número OCR potencialmente corrompido em int."""
    # Substitui letras comuns mal-lidas por dígitos
    cleaned = raw.strip().upper().replace("U", "0").replace("O", "0").replace("B", "8")
    try:
        return int(cleaned)
    except ValueError:
        return -1

# Labels explícitos como fallback
_SONG_LABELS = r"m[uú]sica|m[uú]s\.|song|t[ií]tulo|faixa"
_ARTIST_LABELS = r"artista|cantor(?:a)?|banda|int[eé]rprete|artist|feat\.?|por"
_SONG_RE = re.compile(rf"(?:{_SONG_LABELS})\s*[:\-–]\s*(.+)", re.IGNORECASE)
_ARTIST_RE = re.compile(rf"(?:{_ARTIST_LABELS})\s*[:\-–]\s*(.+)", re.IGNORECASE)

# Separador simples
_SEPARATOR_RE = re.compile(r"^(.+?)\s*[–\-]\s*(.+)$")

# Linhas de ruído
_IGNORE_RE = re.compile(
    r"lembradessesom|lembradesse|instagram|tiktok|youtube|facebook|spotify"
    r"|@\w+|#\w+|^ver mais|^curtir|^compartilhar|^salvar|^seguir",
    re.IGNORECASE,
)
_NOISE_RE = re.compile(r"^[\d\s\W]{0,3}$")


# ------------------------------------------------------------------ #
# Normalização                                                          #
# ------------------------------------------------------------------ #


def _normalize(text: str) -> str:
    """Para comparação/deduplicação: sem acentos, minúsculas, sem espaços extras, sem pontuação."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    # Remove tudo que não seja letra/número/espaço
    clean = re.sub(r"[^a-z0-9 ]", "", ascii_only.lower())
    return re.sub(r"\s+", " ", clean).strip()


def _title_case(text: str) -> str:
    """Converte ALL CAPS para Title Case."""
    if text.isupper() and len(text) > 2:
        return text.title()
    return text


# ------------------------------------------------------------------ #
# Parser principal                                                      #
# ------------------------------------------------------------------ #


class SongParser:
    def parse_frames(
        self, frame_texts: list[str], caption: str = ""
    ) -> list[dict]:
        """
        Recebe textos OCR de múltiplos frames e retorna lista de músicas
        deduplicadas, priorizando os frames com mais entradas.

        Retorna:
        [{"song": str, "artist": str, "confidence": str}, ...]
        """
        if not frame_texts:
            return []

        # Extrai músicas de cada frame
        frame_results: list[list[dict]] = []
        for text in frame_texts:
            results = self._parse_numbered_list(text)
            if not results:
                results = self._parse_fallback(text)
            frame_results.append(results)

        # Usa o frame com mais músicas como base para a ordem final
        best_frame_results = max(frame_results, key=len, default=[])
        logger.debug(f"Melhor frame tem {len(best_frame_results)} músicas")

        # Coleta TODOS os resultados para deduplicação e enriquecimento
        all_results: list[dict] = []
        for results in frame_results:
            all_results.extend(results)

        # Deduplicação global (mantém melhor variante de cada música)
        deduped = self._deduplicate(all_results)

        if not deduped:
            logger.warning("Nenhuma música encontrada nos frames")

        return deduped

    # ------------------------------------------------------------------ #
    # Privado                                                              #
    # ------------------------------------------------------------------ #

    def _parse_numbered_list(self, text: str) -> list[dict]:
        """
        Analisa o padrão de lista numerada:
          01 TITLE
          ARTIST
          02 TITLE2
          ARTIST2

        Também lida com artistas 'órfãos' (artista aparece mas o número/título
        foi mal-lido pelo OCR, ex: KENNY ROGERS sem "09 YOU AND I").
        """
        lines = self._clean_lines(text)
        results = []
        used_indices: set[int] = set()

        i = 0
        while i < len(lines):
            m = _NUMBERED_SONG_RE.match(lines[i])
            if m:
                num = _parse_number(m.group(1))
                song_raw = m.group(2).strip()
                artist_raw = ""
                used_indices.add(i)

                # Próxima linha é o artista (se não for numerada)
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if not _NUMBERED_SONG_RE.match(next_line):
                        artist_raw = next_line
                        used_indices.add(i + 1)
                        i += 1  # pula a linha do artista

                if song_raw:
                    results.append(
                        {
                            "number": num,
                            "song": _title_case(song_raw),
                            "artist": _title_case(artist_raw),
                            "confidence": "medium" if artist_raw else "low",
                        }
                    )
            i += 1

        # Detecta artistas 'órfãos': linhas não usadas que parecem ser artistas
        # (aparecem entre duas entradas numeradas ou ao final)
        if results:
            for j, line in enumerate(lines):
                if j in used_indices:
                    continue
                # Linha limpa que parece um nome de artista (letras, sem número)
                if re.match(r"^[A-Za-z\u00C0-\u024F]", line) and len(line) > 2:
                    # Qual músico seria este? Olha o número que antecede (implícito)
                    # Encontra o slot numérico vazio mais próximo (resultados sem artista)
                    for r in results:
                        if not r["artist"]:
                            r["artist"] = _title_case(line)
                            used_indices.add(j)
                            break

        # Remove campo 'number' interno antes de retornar
        for r in results:
            r.pop("number", None)

        return results

    def _parse_fallback(self, text: str) -> list[dict]:
        """Fallback quando não há lista numerada."""
        lines = self._clean_lines(text)
        if not lines:
            return []

        # Labels explícitos
        song, artist = self._extract_labeled(lines)
        if song:
            return [{"song": song, "artist": artist, "confidence": "high" if artist else "medium"}]

        # Separador
        for line in lines:
            m = _SEPARATOR_RE.match(line)
            if m:
                p1, p2 = m.group(1).strip(), m.group(2).strip()
                if len(p1) > 2 and len(p2) > 2:
                    return [{"song": _title_case(p1), "artist": _title_case(p2), "confidence": "medium"}]

        # Primeiras duas linhas
        meaningful = [l for l in lines if len(l) > 3]
        if len(meaningful) >= 2:
            return [{"song": _title_case(meaningful[0]), "artist": _title_case(meaningful[1]), "confidence": "low"}]
        if len(meaningful) == 1:
            return [{"song": _title_case(meaningful[0]), "artist": "", "confidence": "low"}]

        return []

    def _clean_lines(self, text: str) -> list[str]:
        lines = []
        for raw in text.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if _IGNORE_RE.search(line):
                continue
            if _NOISE_RE.match(line):
                continue
            line = re.sub(r"[^\x20-\x7E\u00C0-\u024F\u1E00-\u1EFF]", "", line).strip()
            if len(line) > 1:
                lines.append(line)
        return lines

    def _extract_labeled(self, lines: list[str]) -> tuple[str, str]:
        song = ""
        artist = ""
        for line in lines:
            if not song:
                m = _SONG_RE.search(line)
                if m:
                    song = m.group(1).strip()
            if not artist:
                m = _ARTIST_RE.search(line)
                if m:
                    artist = m.group(1).strip()
            if song and artist:
                break
        return song, artist

    def _deduplicate(self, results: list[dict]) -> list[dict]:
        """Remove duplicatas usando normalização e prefixo compartilhado."""
        if not results:
            return []

        priority = {"high": 0, "medium": 1, "low": 2}
        sorted_results = sorted(results, key=lambda r: priority.get(r["confidence"], 3))

        seen: set[str] = set()
        unique = []

        for r in sorted_results:
            song_raw = r.get("song", "")
            norm = _normalize(song_raw)

            # Filtra entradas de ruído
            if not norm or len(norm) < 3:
                continue
            # Filtra artefatos que começam com ' ou [ (ruídos do logo)
            if song_raw.startswith(("'", "[", "|")):
                continue

            already = False
            for s in seen:
                if _similar(norm, s):
                    already = True
                    break

            if not already:
                seen.add(norm)
                unique.append(r)

        return unique


def _similar(a: str, b: str, threshold: float = 0.68) -> bool:
    if a == b:
        return True
    # Um contém o outro (ex: "drive" in "01 drivea")
    if a in b or b in a:
        return True
    # Similaridade fuzzy via SequenceMatcher
    ratio = SequenceMatcher(None, a, b).ratio()
    return ratio >= threshold
