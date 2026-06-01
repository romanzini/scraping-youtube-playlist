"""
Teste mais rigoroso para verificar se vídeos apenas de áudio são filtrados.
"""

import logging
import sys
from pathlib import Path
import yt_dlp

# Adiciona o diretório extractor ao path
sys.path.insert(0, str(Path(__file__).parent))

from extractor.youtube_search import search_youtube

# Configura logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

def check_video_has_image(video_url: str) -> bool:
    """Verifica manualmente se um vídeo tem imagem."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
        
        print(f"\n  Informações do vídeo:")
        print(f"  - Título: {info.get('title', 'N/A')}")
        print(f"  - Height: {info.get('height', 'N/A')}")
        print(f"  - Width: {info.get('width', 'N/A')}")
        print(f"  - Duration: {info.get('duration', 'N/A')}s")
        
        # Verifica formatos disponíveis
        has_video_format = False
        if info.get("formats"):
            for fmt in info["formats"]:
                if fmt.get("vcodec") and fmt.get("vcodec") != "none":
                    if fmt.get("height") and fmt.get("height") > 0:
                        has_video_format = True
                        print(f"  - Formato com vídeo encontrado: {fmt.get('format_id')} ({fmt.get('height')}p)")
                        break
        
        return has_video_format

def test_comprehensive():
    """Teste mais completo."""
    
    test_queries = [
        "Roberto Carlos Detalhes",
        "música instrumental relaxante",  # Pode retornar vídeos apenas de áudio
        "podcast brasileiro",  # Muitos podcasts são apenas áudio
    ]
    
    print("\n" + "="*70)
    print("Teste rigoroso do filtro de vídeos com imagem")
    print("="*70 + "\n")
    
    for query in test_queries:
        print(f"\n{'='*70}")
        print(f"Query: {query!r}")
        print('='*70)
        
        url = search_youtube(query)
        
        if url:
            print(f"✓ URL retornada: {url}")
            
            # Verifica manualmente se tem imagem
            has_image = check_video_has_image(url)
            
            if has_image:
                print(f"  ✓ CORRETO: Vídeo tem imagem")
            else:
                print(f"  ✗ ERRO: Vídeo NÃO tem imagem (deveria ter sido filtrado!)")
        else:
            print("✗ Nenhum vídeo encontrado (possível que todos os resultados fossem apenas áudio)")
        
        print()

if __name__ == "__main__":
    test_comprehensive()
