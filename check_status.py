"""Check status of youtube_songs.json"""
import json
from pathlib import Path

data = json.loads(Path("output/youtube_songs.json").read_text())

print(f"Total músicas: {len(data)}")
com_url = sum(1 for s in data if s.get('youtube_url'))
print(f"Com URL: {com_url}")
normalizadas = sum(1 for s in data if s.get('normalized'))
print(f"Normalizadas: {normalizadas}")

print("\nPrimeiras 3 músicas:")
for i, song in enumerate(data[:3], 1):
    print(f"\n{i}. {song.get('artist')} - {song.get('song')}")
    print(f"   URL: {song.get('youtube_url', 'N/A')}")
    print(f"   Normalizada: {song.get('normalized', False)}")
    print(f"   MB ID: {song.get('mb_id', 'N/A')}")
