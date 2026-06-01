"""
Normalização de músicas via MusicBrainz API (gratuita, sem autenticação).

Dado um título com artefatos de OCR (ex: "TIEDAFTERTIME") e um artista
(ex: "CYNDI LAUPER"), busca no MusicBrainz o título canônico correto.

Rate limiting respeitado: máx. 1 req/segundo conforme termos de uso.
https://musicbrainz.org/doc/MusicBrainz_API

Endpoint usado:
  GET https://musicbrainz.org/ws/2/recording
  ?query=artist:"{artist}" AND recording:"{song}"
  &fmt=json&limit=5
"""

import logging
import time
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

import requests

logger = logging.getLogger(__name__)

MB_BASE = "https://musicbrainz.org/ws/2/recording"
MB_HEADERS = {
    "User-Agent": "lembradessesom-extractor/0.1 (scraping@local)",
    "Accept": "application/json",
}
MB_RATE_LIMIT = 1.1  # segundos entre requisições (API exige max 1/s)

# Correções heurísticas de OCR (ordem importa: mais específico primeiro)
# Cada entrada: (padrão regex, substituição) — aplicados em UPPERCASE
_OCR_FIXES = [
    # Concatenações conhecidas de palavras
    (r"WHATSLOVE",              "WHAT'S LOVE"),
    (r"WHATS\b",                "WHAT'S"),
    (r"WITHIT\b",               "WITH IT"),
    (r"NOMORELONELYWICHTS\b",   "NO MORE LONELY NIGHTS"),  # must come before NOMORELONELY
    (r"NOMORELONELYNIQHTS\b",   "NO MORE LONELY NIGHTS"),
    (r"NOMORELONELY\b",         "NO MORE LONELY"),
    (r"NOMORE\b",               "NO MORE"),
    (r"EBONYEYES\b",            "EBONY EYES"),
    (r"YOUANDI\b",              "YOU AND I"),
    (r"DANCINGINTHEDARK",       "DANCING IN THE DARK"),
    (r"INTHENIGHT\b",           "IN THE NIGHT"),
    # Fragmentos de "the" embutidos
    (r"INTHEDARK\b",            "IN THE DARK"),
    (r"RTHE\b",                 " THE"),
    (r"NTHE\b",                 " THE"),
    (r"INTHE\b",                "IN THE"),
    # OCR confunde "nights" com variações
    (r"WICHTS\b",               "NIGHTS"),
    (r"NIQHTS\b",               "NIGHTS"),
    # Artefatos de OCR de letras no final (ex: "Drivea" → "Drive")
    # Remove sufixo de 1-2 letras minúsculas / OCR noise depois da última palavra
    (r"([A-Z]{3,})[a-z]{1,2}\b", r"\1"),
]

# Palavras que o OCR frequentemente concatena por falta de espaço
_SPLIT_PATTERNS = [
    # Prefixos comuns que aparecem grudados
    (r"(?<=[a-z])(?=[A-Z])", " "),  # camelCase residual
]


def _pre_clean(title: str) -> str:
    """Aplica correções heurísticas de OCR antes de enviar à API."""
    t = title.upper()
    for pattern, replacement in _OCR_FIXES:
        t = re.sub(pattern, replacement, t)
    return re.sub(r"\s+", " ", t).strip().title()


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_ = nfkd.encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^a-z0-9 ]", "", ascii_.lower())
    return re.sub(r"\s+", " ", clean).strip()  # collapse multiple spaces


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


class MusicBrainzNormalizer:
    def __init__(self, delay: float = MB_RATE_LIMIT):
        self.delay = delay
        self._last_request: float = 0.0

    # ------------------------------------------------------------------ #
    # Público                                                              #
    # ------------------------------------------------------------------ #

    def normalize_song(self, raw_song: str, raw_artist: str) -> dict:
        """
        Busca no MusicBrainz o título e artista canônicos.

        Retorna:
        {
          "song"         : str,   # título normalizado
          "artist"       : str,   # artista normalizado
          "mb_score"     : int,   # score de relevância (0-100)
          "mb_id"        : str,   # MusicBrainz recording ID
          "normalized"   : bool,  # True se encontrou no MB
          "raw_song"     : str,   # título original do OCR
          "raw_artist"   : str,   # artista original do OCR
        }
        """
        cleaned_song = _pre_clean(raw_song)
        cleaned_artist = _normalize(raw_artist).title()

        logger.debug(f"Normalizando: {raw_song!r} / {raw_artist!r}")
        logger.debug(f"  Pre-cleaned: {cleaned_song!r} / {cleaned_artist!r}")

        # Tentativa 1: artista + título (mais preciso)
        result = self._search(cleaned_song, cleaned_artist, query_title=cleaned_song,
                              title_sim_threshold=0.50)

        # Tentativa 2: busca top tracks do artista e escolhe a mais similar ao OCR
        # Só usada se o resultado tiver similaridade de título >= 0.7 (evita matches fracos)
        artist_sim_result = None
        if not result and cleaned_artist:
            candidate = self._search_by_artist_similarity(cleaned_song, cleaned_artist)
            if candidate and _similarity(cleaned_song, candidate["song"]) >= 0.70:
                result = candidate
            else:
                artist_sim_result = candidate  # guarda para desempate posterior

        # Tentativa 3: só pelo título (sem restrição de artista)
        # Limit=100 para garantir que versões populares (ex: Rick James pos.17,
        # Paul McCartney em posições variáveis) estejam presentes; candidatos
        # são ranqueados por similaridade de artista, não pela ordem do MB.
        title_only_result = None
        if not result:
            title_only_result = self._search(
                cleaned_song, "", limit=100, query_title=cleaned_song,
                title_sim_threshold=0.55,
                validate_artist=cleaned_artist,
                validate_artist_threshold=0.55,
            )

        # Desempate: se temos resultado do artista (fraco) e do título, prefere o
        # com maior similaridade ao título OCR pré-limpo
        if not result:
            if title_only_result and artist_sim_result:
                sim_a = _similarity(cleaned_song, artist_sim_result["song"])
                sim_t = _similarity(cleaned_song, title_only_result["song"])
                result = title_only_result if sim_t >= sim_a else artist_sim_result
            elif title_only_result:
                result = title_only_result
            elif artist_sim_result:
                result = artist_sim_result

        base = {
            "raw_song": raw_song,
            "raw_artist": raw_artist,
        }

        if result:
            base.update(
                {
                    "song": result["song"],
                    "artist": result["artist"],
                    "mb_score": result["score"],
                    "mb_id": result["id"],
                    "normalized": True,
                }
            )
        else:
            # Não encontrou: mantém o título pré-limpo como melhor esforço
            base.update(
                {
                    "song": cleaned_song,
                    "artist": cleaned_artist,
                    "mb_score": 0,
                    "mb_id": "",
                    "normalized": False,
                }
            )

        return base

    def normalize_batch(self, songs: list[dict]) -> list[dict]:
        """Normaliza lista de músicas, respeitando o rate limit, e deduplicada pós-normalização."""
        results = []
        for i, s in enumerate(songs):
            logger.info(
                f"  [{i+1}/{len(songs)}] Normalizando: {s['song']!r} / {s['artist']!r}"
            )
            normalized = self.normalize_song(s["song"], s["artist"])
            normalized["confidence"] = s.get("confidence", "")
            results.append(normalized)

        # Deduplicação pós-normalização: remove duplicatas pelo título normalizado
        seen: set[str] = set()
        unique = []
        for r in results:
            key = _normalize(r.get("song", ""))
            if key and key not in seen:
                seen.add(key)
                unique.append(r)
            else:
                logger.debug(f"  Dedup pós-norm: removendo duplicata {r.get('song')!r}")

        return unique

    # ------------------------------------------------------------------ #
    # Privado                                                              #
    # ------------------------------------------------------------------ #

    def _search(
        self, song: str, artist: str, limit: int = 5, query_title: str = "",
        title_sim_threshold: float = 0.50,
        validate_artist: str = "",
        validate_artist_threshold: float = 0.40,
    ) -> Optional[dict]:
        """
        Busca no MusicBrainz e retorna o melhor resultado.

        query_title: título pré-limpo para validar similaridade com resultado.
        title_sim_threshold: limiar mínimo de similaridade de título (0-1).
        validate_artist: se fornecido, valida similaridade do artista retornado
                         (útil quando a busca não usa restrição de artista).
        """
        self._rate_limit()

        parts = []
        if artist:
            parts.append(f'artist:"{artist}"')
        if song:
            parts.append(f'recording:"{song}"')
        query = " AND ".join(parts) if parts else song

        params = {"query": query, "fmt": "json", "limit": limit}

        try:
            resp = None
            for attempt in range(3):
                try:
                    resp = requests.get(
                        MB_BASE, params=params, headers=MB_HEADERS, timeout=20
                    )
                    resp.raise_for_status()
                    break
                except requests.exceptions.Timeout:
                    if attempt < 2:
                        logger.debug(f"  Timeout (tentativa {attempt+1}/3), aguardando...")
                        time.sleep(2 ** attempt)
                    else:
                        raise
            data = resp.json() if resp else {}
        except Exception as e:
            logger.warning(f"MusicBrainz error: {e}")
            return None

        recordings = data.get("recordings", [])
        if not recordings:
            return None

        # Collect all candidates that pass score, artist, and title filters.
        # When validate_artist is active we pick the candidate with the highest
        # artist similarity rather than the first one (MB ordering can surface
        # wrong artists whose names happen to share common substrings with the OCR text).
        candidates: list[tuple[float, dict]] = []  # (artist_sim, record_dict)

        for rec in recordings:
            mb_score = int(rec.get("score", 0))
            if mb_score < 50:
                break  # results are sorted by score desc

            artist_credits = rec.get("artist-credit", [])
            artist_name = (
                artist_credits[0].get("artist", {}).get("name", "")
                if artist_credits
                else ""
            )
            recording_title = rec.get("title", "")

            # Validação de artista (busca com artista explícito)
            if artist and _similarity(artist, artist_name) < 0.5:
                logger.debug(
                    f"  Artista muito diferente: {artist!r} vs {artist_name!r} — skipping"
                )
                continue

            # Validação de título
            if query_title:
                title_sim = _similarity(query_title, recording_title)
                if title_sim < title_sim_threshold:
                    logger.debug(
                        f"  Título muito diferente: {query_title!r} vs {recording_title!r}"
                        f" (sim={title_sim:.2f}) — skipping"
                    )
                    continue

            # Validação de artista pós-resultado (busca sem restrição de artista)
            if validate_artist and not artist:
                art_sim = _similarity(validate_artist, artist_name)
                if art_sim < validate_artist_threshold:
                    logger.debug(
                        f"  Artista pós-validação falhou: {validate_artist!r} vs {artist_name!r}"
                        f" (sim={art_sim:.2f}) — skipping"
                    )
                    continue
                # Accumulate; will pick best artist-sim below
                candidates.append((art_sim, {
                    "song": recording_title,
                    "artist": artist_name,
                    "score": mb_score,
                    "id": rec.get("id", ""),
                }))
            else:
                # Without validate_artist, return first passing result (original behaviour)
                return {
                    "song": recording_title,
                    "artist": artist_name,
                    "score": mb_score,
                    "id": rec.get("id", ""),
                }

        if candidates:
            # Return the candidate whose artist name best matches the OCR artist
            candidates.sort(key=lambda x: x[0], reverse=True)
            logger.debug(
                f"  Best validate_artist candidate: {candidates[0][1]['artist']!r}"
                f" (sim={candidates[0][0]:.2f})"
            )
            return candidates[0][1]

        return None

    def _search_by_artist_similarity(
        self, query_title: str, artist: str, limit: int = 100, min_sim: float = 0.5
    ) -> Optional[dict]:
        """
        Busca as top N tracks do artista e retorna a com maior similaridade ao
        query_title. Útil quando o título OCR está muito corrompido para busca direta.

        Tenta com artista completo primeiro; se falhar, tenta com a primeira parte
        do nome (antes de '&', 'feat.', ' and ').
        """
        # Gera variantes do nome do artista para tentar
        artist_variants = [artist]
        # 1) Parte principal antes de feat/&/and (ex: "Rick James & Smokey Robinson" → "Rick James")
        short = re.split(
            r"\s*[&/]\s*|\s+feat\.?\s+|\s+and\s+|\s{2,}", artist, flags=re.IGNORECASE
        )[0].strip()
        if short and short != artist:
            artist_variants.append(short)
        # 2) Primeiras duas palavras — útil quando _normalize colapsou separadores
        #    e o artista OCR ficou "Rick James Shokey Robinson" (sem separador)
        words = artist.split()
        if len(words) >= 3:
            two_word = " ".join(words[:2])
            if two_word not in artist_variants:
                artist_variants.append(two_word)

        for artist_query in artist_variants:
            result = self._artist_top_tracks(query_title, artist_query, artist, limit, min_sim)
            if result:
                return result

        return None

    def _artist_top_tracks(
        self, query_title: str, artist_query: str, original_artist: str,
        limit: int, min_sim: float
    ) -> Optional[dict]:
        """Busca top N tracks por artista (até 100) e seleciona a mais similar ao título."""
        self._rate_limit()

        params = {
            "query": f'artist:"{artist_query}"',
            "fmt": "json",
            "limit": limit,
        }

        try:
            resp = requests.get(
                MB_BASE, params=params, headers=MB_HEADERS, timeout=20
            )
            resp.raise_for_status()
            recordings = resp.json().get("recordings", [])
        except Exception as e:
            logger.warning(f"MusicBrainz (artist search) error: {e}")
            return None

        if not recordings:
            return None

        # Calcula similaridade de cada título com o OCR
        best_rec = None
        best_sim = 0.0
        for rec in recordings:
            mb_score = int(rec.get("score", 0))
            if mb_score < 50:
                continue
            title = rec.get("title", "")
            sim = _similarity(query_title, title)
            logger.debug(f"  artist-sim: {query_title!r} vs {title!r} → {sim:.2f}")
            if sim > best_sim:
                best_sim = sim
                best_rec = rec

        if best_rec is None or best_sim < min_sim:
            logger.debug(f"  Melhor similaridade muito baixa ({best_sim:.2f}) para {artist_query!r}")
            return None

        artist_credits = best_rec.get("artist-credit", [])
        artist_name = (
            artist_credits[0].get("artist", {}).get("name", "")
            if artist_credits
            else ""
        )

        # Validação de artista contra o artista original (relaxada: 0.4)
        if _similarity(original_artist, artist_name) < 0.4:
            logger.debug(f"  Artista muito diferente (artist-sim): {original_artist!r} vs {artist_name!r}")
            return None

        return {
            "song": best_rec.get("title", ""),
            "artist": artist_name,
            "score": int(best_rec.get("score", 0)),
            "id": best_rec.get("id", ""),
        }

    def _rate_limit(self):
        """Aguarda se necessário para não ultrapassar 1 req/s."""
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()
