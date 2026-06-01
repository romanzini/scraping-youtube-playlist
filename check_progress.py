import json
from pathlib import Path

data = json.loads(Path('output/extracted_songs.json').read_text())
total = sum(len(r.get('songs',[])) for r in data)
with_url = sum(1 for r in data for s in r.get('songs',[]) if s.get('youtube_url'))

flat_path = Path('output/youtube_songs.json')
flat = json.loads(flat_path.read_text()) if flat_path.exists() else []
flat_found = sum(1 for x in flat if x.get('youtube_url'))

print(f'Total songs: {total}')
print(f'With youtube_url: {with_url}')
print(f'Still pending: {total - with_url}')
print(f'Flat list: {len(flat)} unique, {flat_found} with URL')
