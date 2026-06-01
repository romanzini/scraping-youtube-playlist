"""
Busca URLs do YouTube para cada música extraída.

Usa yt-dlp ytsearch — sem API key necessária.

Fluxo:
  1. Lê extracted_songs.json
  2. Para cada música elegível, busca no YouTube
  3. Deduplica buscas pelo par (song, artist)
  4. Adiciona campo youtube_url em cada entrada do JSON
  5. Salva extracted_songs.json atualizado + youtube_songs.json (lista plana)
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional

import yt_dlp

logger = logging.getLogger(__name__)

YT_DELAY = 0.8  # segundos entre buscas (evita rate-limit do YouTube)

# Padrões que indicam ruído de OCR, não músicas reais.
# Qualquer título que bata num desses padrões é ignorado.
_NOISE_PATTERNS = [
    re.compile(r"^\d{4}$"),                          # só ano: "1983"
    re.compile(r"músicas?\b", re.I),                 # "Músicas", "Música Nacional"
    re.compile(r"\bnacionais?\b", re.I),             # "Nacionais"
    re.compile(r"\binternacionais?\b", re.I),        # "Internacionais"
    re.compile(r"\bsucessos?\b", re.I),              # "Sucessos"
    re.compile(r"\bhits?\b", re.I),                  # "Hits"
    re.compile(r"\btrilhas?\b", re.I),               # "Trilhas"
    re.compile(r"\bcompartilhe\b", re.I),            # "Compartilhe o vídeo"
    re.compile(r"\bsegue\b", re.I),                  # "eme segue para mais"
    re.compile(r"\bvídeo\b", re.I),                  # "vídeo"
    re.compile(r"^\W+$"),                            # só pontuação / símbolos
]


def _is_noise(song_entry: dict) -> bool:
    """Retorna True se a entrada parece ruído de OCR, não uma música real."""
    title = song_entry.get("song", "").strip()
    artist = song_entry.get("artist", "").strip()

    # Títulos muito curtos (1 palavra ≤ 2 chars) são geralmente ruído
    if len(title) <= 2:
        return True

    # Checa padrões de ruído no título ou artista
    for pat in _NOISE_PATTERNS:
        if pat.search(title) or pat.search(artist):
            return True

    # Artista que parece ser na verdade uma descrição do vídeo
    if re.search(r"\banos?\b|\bsaiba\b|\bclique\b|\bcurtiu\b|\btinha\b", artist, re.I):
        return True

    return False


def _build_query(song: dict) -> str:
    """Monta a query de busca a partir dos campos da música."""
    title = song.get("song", "").strip()
    artist = song.get("artist", "").strip()
    if artist:
        return f"{artist} {title}"
    return title


def _strip_ocr_junk(text: str) -> str:
    """Remove caracteres OCR espúrios do início do texto (ex: '{', '04;', '1Occ ')."""
    # Remove prefixos numérico/simbólicos como "04; ", "1", "0J6) "
    cleaned = re.sub(r"^[\W\d]+", "", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def _tail_words(title: str, n: int) -> str:
    """Retorna as últimas n palavras do título (limpas de pontuação nas bordas)."""
    words = [re.sub(r"^[^\w]+|[^\w]+$", "", w) for w in title.split()]
    words = [w for w in words if len(w) >= 2]
    tail = words[-n:] if len(words) >= n else words
    return " ".join(tail)


def _retry_queries(song_entry: dict) -> list[str]:
    """
    Gera variantes de query para músicas que falharam na busca original.
    Estratégia principal: usar as últimas N palavras do título — a corrupção OCR
    tende a concentrar-se nas primeiras palavras/letras de cada bloco de texto.

    Retorna lista de queries a tentar, da mais específica para a mais genérica.
    """
    title_raw = song_entry.get("song", "").strip()
    artist_raw = song_entry.get("artist", "").strip()

    artist_clean = _strip_ocr_junk(artist_raw)
    title_words = [w for w in title_raw.split() if len(re.sub(r"[^\w]", "", w)) >= 2]
    n_words = len(title_words)

    variants: list[str] = []

    # Variantes com cauda do título (últimas 4, 3, 2 palavras)
    for tail_n in (4, 3, 2):
        if n_words >= tail_n:
            tail = _tail_words(title_raw, tail_n)
            for artist in _artist_variants(artist_raw, artist_clean):
                q = f"{artist} {tail}".strip()
                if q not in variants:
                    variants.append(q)

    return variants


def _artist_variants(artist_raw: str, artist_clean: str) -> list[str]:
    """Retorna variantes do nome do artista a usar nas queries (sem duplicatas)."""
    seen: list[str] = []
    for a in (artist_raw, artist_clean):
        if a and a not in seen:
            seen.append(a)
    return seen


def search_youtube(query: str) -> Optional[str]:
    """
    Retorna a URL do primeiro resultado do YouTube para a query que contenha vídeo (não apenas áudio).
    Usa yt-dlp ytsearch — sem download, sem API key.
    Filtra apenas vídeos com streams de vídeo (height > 0), excluindo conteúdo apenas de áudio.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 15,
    }
    try:
        # Busca os primeiros 5 resultados para ter opções caso o primeiro seja apenas áudio
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch5:{query}", download=False)
            if result and result.get("entries"):
                for entry in result["entries"]:
                    video_id = entry.get("id", "")
                    if not video_id:
                        continue
                    
                    # Extrai informações completas do vídeo para verificar se tem stream de vídeo
                    try:
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        video_info = ydl.extract_info(video_url, download=False)
                        
                        # Verifica se o vídeo tem dimensões (altura/largura)
                        # Vídeos apenas de áudio geralmente não têm essas propriedades ou têm height=0
                        has_video = False
                        
                        # Verifica propriedades principais do vídeo
                        if video_info.get("height") and video_info.get("height") > 0:
                            has_video = True
                        elif video_info.get("width") and video_info.get("width") > 0:
                            has_video = True
                        
                        # Verifica se existe algum formato com vídeo
                        if not has_video and video_info.get("formats"):
                            for fmt in video_info["formats"]:
                                if fmt.get("vcodec") and fmt.get("vcodec") != "none":
                                    if fmt.get("height") and fmt.get("height") > 0:
                                        has_video = True
                                        break
                        
                        if has_video:
                            logger.debug(f"Vídeo com imagem encontrado: {video_url}")
                            return video_url
                        else:
                            logger.debug(f"Pulando vídeo apenas de áudio: {video_url}")
                            
                    except Exception as ve:
                        logger.debug(f"Erro ao verificar vídeo {video_id}: {ve}")
                        continue
                        
    except Exception as e:
        logger.warning(f"YouTube search error for {query!r}: {e}")
    return None


class _SearchLimitReached(Exception):
    pass


def retry_not_found(
    input_path: Path,
    results_path: Path,
    flat_output_path: Path,
    delay: float = YT_DELAY,
    max_searches: int = 0,
) -> dict:
    """
    Retenta músicas que falharam (youtube_url == "") com queries limpas.
    Tenta até 3 variantes por entrada: artista+título limpo, artista limpo+título limpo,
    e artista limpo sozinho (para títulos muito garbled).

    Retorna estatísticas: {tried, recovered, still_failed}
    """
    import json

    data = json.loads(input_path.read_text(encoding="utf-8"))

    stats = {"tried": 0, "recovered": 0, "still_failed": 0}
    seen_keys: set[tuple[str, str]] = set()

    # Cache de recuperações desta sessão: query_original → url
    recovery_cache: dict[tuple[str, str], Optional[str]] = {}

    try:
        for rec_idx, rec in enumerate(data):
            dirty = False
            for song_entry in rec.get("songs", []):
                # Só processa entradas com youtube_url vazio (tentativa anterior falhou)
                if song_entry.get("youtube_url") != "":
                    continue

                key = (
                    _norm_key(song_entry.get("song", "")),
                    _norm_key(song_entry.get("artist", "")),
                )

                # Se já recuperamos (ou confirmamos falha) esta chave nesta sessão
                if key in recovery_cache:
                    result = recovery_cache[key]
                    song_entry["youtube_url"] = result or ""
                    if result:
                        dirty = True
                    continue

                if key in seen_keys:
                    continue
                seen_keys.add(key)

                if max_searches and stats["tried"] >= max_searches:
                    raise _SearchLimitReached

                variants = _retry_queries(song_entry)
                if not variants:
                    recovery_cache[key] = None
                    stats["still_failed"] += 1
                    continue

                found_url = None
                for variant in variants:
                    stats["tried"] += 1
                    logger.info(
                        f"Retry [{stats['tried']}] "
                        f"{song_entry.get('artist','')} | {song_entry.get('song','')} "
                        f"→ {variant!r}"
                    )
                    url = search_youtube(variant)
                    time.sleep(delay)
                    if url:
                        found_url = url
                        logger.info(f"  ✓ Recuperado: {url}")
                        break
                    else:
                        logger.debug(f"  ✗ Variante falhou: {variant!r}")

                recovery_cache[key] = found_url
                if found_url:
                    song_entry["youtube_url"] = found_url
                    dirty = True
                    stats["recovered"] += 1
                else:
                    stats["still_failed"] += 1
                    logger.warning(
                        f"  Sem URL para: {song_entry.get('artist','')} | "
                        f"{song_entry.get('song','')}"
                    )

            if dirty and rec_idx % 10 == 9:
                _save_json(data, results_path)

    except _SearchLimitReached:
        logger.info(f"Limite de {max_searches} buscas atingido — parando.")

    _save_json(data, results_path)

    flat = _build_flat_list(data, min_rank=1)
    _save_json(flat, flat_output_path)
    logger.info(f"youtube_songs.json atualizado: {len(flat)} entradas → {flat_output_path}")

    return stats


def enrich_with_youtube(
    input_path: Path,
    results_path: Path,
    flat_output_path: Path,
    min_confidence: str = "medium",
    delay: float = YT_DELAY,
    max_searches: int = 0,  # 0 = sem limite
) -> dict:
    """
    Lê o extracted_songs.json, busca YouTube para cada música elegível,
    atualiza os registros com youtube_url e salva dois arquivos:
      - results_path    : extracted_songs.json atualizado (in-place)
      - flat_output_path: youtube_songs.json — lista plana de músicas únicas

    Retorna dict com estatísticas: {searched, found, skipped, errors}
    """
    import json

    _CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}
    min_rank = _CONFIDENCE_RANK.get(min_confidence, 1)

    data = json.loads(input_path.read_text(encoding="utf-8"))

    # Cache: (song_lower, artist_lower) → youtube_url | None
    # Inicializa com valores já presentes no JSON (permite retomar sessão).
    # Só considera entradas que foram realmente pesquisadas (url != "").
    cache: dict[tuple[str, str], Optional[str]] = {}
    for rec in data:
        for s in rec.get("songs", []):
            existing = s.get("youtube_url")
            if existing:  # string não-vazia = URL real encontrada
                key = (_norm_key(s.get("song", "")), _norm_key(s.get("artist", "")))
                cache[key] = existing

    stats = {"searched": 0, "found": 0, "skipped_confidence": 0,
             "skipped_noise": 0, "skipped_cache": 0, "errors": 0}

    total_songs = sum(len(r.get("songs", [])) for r in data)
    logger.info(f"Total de músicas no arquivo: {total_songs}")

    try:
        for rec_idx, rec in enumerate(data):
            dirty = False

            for song_entry in rec.get("songs", []):
                conf = song_entry.get("confidence", "low")
                if _CONFIDENCE_RANK.get(conf, 0) < min_rank:
                    stats["skipped_confidence"] += 1
                    continue

                # Filtra ruído de OCR
                if _is_noise(song_entry):
                    stats["skipped_noise"] += 1
                    continue

                song_title = song_entry.get("song", "").strip()
                if not song_title:
                    stats["skipped_confidence"] += 1
                    continue

                key = (_norm_key(song_title), _norm_key(song_entry.get("artist", "")))

                # Já tem URL real no registro — confirma cache e pula
                if song_entry.get("youtube_url"):
                    cache.setdefault(key, song_entry["youtube_url"])
                    stats["skipped_cache"] += 1
                    continue

                # Cache hit (por outro reel com mesma música)
                if key in cache:
                    song_entry["youtube_url"] = cache[key] or ""
                    dirty = True
                    stats["skipped_cache"] += 1
                    continue

                # Limite de buscas atingido — para sem gravar nada
                if max_searches and stats["searched"] >= max_searches:
                    raise _SearchLimitReached

                # Nova busca
                query = _build_query(song_entry)
                logger.info(f"Buscando [{stats['searched']+1}]: {query!r}")
                yt_url = search_youtube(query)
                cache[key] = yt_url
                song_entry["youtube_url"] = yt_url or ""
                dirty = True

                stats["searched"] += 1
                if yt_url:
                    stats["found"] += 1
                    logger.info(f"  → {yt_url}")
                else:
                    stats["errors"] += 1
                    logger.warning(f"  Não encontrado: {query!r}")

                time.sleep(delay)

            # Salva progresso a cada 10 reels
            if dirty and rec_idx % 10 == 9:
                _save_json(data, results_path)
                logger.debug(f"  Progresso salvo ({rec_idx + 1}/{len(data)} reels)")

    except _SearchLimitReached:
        logger.info(f"Limite de {max_searches} buscas atingido — parando.")

    # Salva estado final
    _save_json(data, results_path)

    flat = _build_flat_list(data, min_rank=min_rank)
    _save_json(flat, flat_output_path)
    logger.info(
        f"youtube_songs.json: {len(flat)} músicas únicas → {flat_output_path}"
    )

    return stats


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #


def _norm_key(text: str) -> str:
    return text.lower().strip()


def _save_json(data, path: Path):
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_flat_list(data: list, min_rank: int = 1) -> list[dict]:
    """Lista plana de músicas únicas, ordenada por frequência de aparição."""
    _CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}

    seen: dict[tuple[str, str], dict] = {}
    freq: dict[tuple[str, str], int] = {}

    for rec in data:
        for s in rec.get("songs", []):
            if _CONFIDENCE_RANK.get(s.get("confidence", "low"), 0) < min_rank:
                continue
            if _is_noise(s):
                continue

            title = s.get("song", "").strip()
            artist = s.get("artist", "").strip()
            if not title:
                continue

            key = (_norm_key(title), _norm_key(artist))
            freq[key] = freq.get(key, 0) + 1

            if key not in seen:
                seen[key] = {
                    "song": title,
                    "artist": artist,
                    "youtube_url": s.get("youtube_url", ""),
                    "mb_id": s.get("mb_id", ""),
                    "normalized": s.get("normalized", False),
                    "appearances": 0,
                }
            if not seen[key]["youtube_url"] and s.get("youtube_url"):
                seen[key]["youtube_url"] = s["youtube_url"]

    flat = []
    for key, entry in seen.items():
        entry["appearances"] = freq[key]
        flat.append(entry)

    flat.sort(key=lambda x: x["appearances"], reverse=True)
    return flat
