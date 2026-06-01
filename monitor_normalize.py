"""Monitor normalization progress"""
import json
import time
from pathlib import Path
from datetime import datetime

YOUTUBE_SONGS = Path("output/youtube_songs.json")

def check_progress():
    data = json.loads(YOUTUBE_SONGS.read_text())
    
    total = len(data)
    normalized = sum(1 for s in data if s.get('normalized'))
    remaining = total - normalized
    progress_pct = (normalized / total * 100) if total > 0 else 0
    
    print("="*60)
    print(f"NORMALIZAÇÃO - Status em {datetime.now().strftime('%H:%M:%S')}")
    print("="*60)
    print(f"Total de músicas    : {total}")
    print(f"Normalizadas        : {normalized} ({progress_pct:.1f}%)")
    print(f"Restantes           : {remaining}")
    print("="*60)
    
    if normalized > 0:
        print("\nÚltimas 3 normalizações:")
        count = 0
        for song in data:
            if song.get('normalized'):
                print(f"  ✓ {song.get('artist')} - {song.get('song')}")
                count += 1
                if count >= 3:
                    break
    
    return normalized, total

if __name__ == "__main__":
    import sys
    
    if "--watch" in sys.argv:
        print("Monitorando progresso (Ctrl+C para sair)...\n")
        try:
            while True:
                normalized, total = check_progress()
                if normalized >= total:
                    print("\n✓ Normalização completa!")
                    break
                time.sleep(30)  # Atualiza a cada 30 segundos
                print("\n")
        except KeyboardInterrupt:
            print("\n\nMonitoramento interrompido.")
    else:
        check_progress()
