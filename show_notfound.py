import json
from pathlib import Path

data = json.loads(Path('output/extracted_songs.json').read_text())
not_found = []
seen = set()
for rec in data:
    for s in rec.get('songs', []):
        if 'youtube_url' in s and s['youtube_url'] == '':
            key = (s.get('song','').strip().lower(), s.get('artist','').strip().lower())
            if key not in seen:
                seen.add(key)
                not_found.append({
                    'song': s.get('song',''),
                    'artist': s.get('artist',''),
                    'confidence': s.get('confidence','')
                })

print(f'Unique not-found: {len(not_found)}')
for e in not_found:
    print(f'  [{e["confidence"]}] {repr(e["artist"])} | {repr(e["song"])}')
