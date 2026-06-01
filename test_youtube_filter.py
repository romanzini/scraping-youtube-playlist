"""
Script de teste para verificar se o filtro de vídeos com imagem está funcionando.
Testa algumas queries conhecidas de músicas e vídeos apenas de áudio.
"""

import logging
import sys
from pathlib import Path

# Adiciona o diretório extractor ao path
sys.path.insert(0, str(Path(__file__).parent))

from extractor.youtube_search import search_youtube

# Configura logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

def test_search():
    """Testa algumas queries para verificar o filtro."""
    
    test_queries = [
        "Roberto Carlos Detalhes",  # Deve encontrar vídeo com imagem
        "Caetano Veloso Alegria Alegria",  # Deve encontrar vídeo com imagem
        "música brasileira",  # Query genérica
    ]
    
    print("\n" + "="*70)
    print("Testando busca no YouTube com filtro de vídeos com imagem")
    print("="*70 + "\n")
    
    for query in test_queries:
        print(f"\nQuery: {query!r}")
        print("-" * 70)
        
        url = search_youtube(query)
        
        if url:
            print(f"✓ Encontrado: {url}")
        else:
            print("✗ Nenhum vídeo com imagem encontrado")
        
        print()

if __name__ == "__main__":
    test_search()
