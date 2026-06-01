"""
create_playlist.py

Creates the YouTube playlist "lambradessevideo" and adds all songs
from output/youtube_songs.json that have a youtube_url.

Quota-aware: YouTube Data API allows ~10,000 units/day.
  - playlist.create   = 50 units  (once)
  - playlistItems.insert = 50 units each

At 50 units/insert → ~200 songs/day max.
Run this script daily until all songs are added; progress is saved to
output/playlist_progress.json so it resumes from where it left off.

Usage:
  uv run python create_playlist.py
  uv run python create_playlist.py --max-inserts 200   # override daily limit
  uv run python create_playlist.py --dry-run           # preview only
"""

import argparse
import datetime
import json
import os
import re
import sys
import time

SECRETS_DIR = os.path.join(os.path.dirname(__file__), ".secrets")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
SONGS_FILE = os.path.join(OUTPUT_DIR, "youtube_songs.json")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "playlist_progress.json")

PLAYLIST_NAME = "lambradessevideo"
PLAYLIST_DESCRIPTION = "Músicas extraídas dos reels do @lembradessesom"

# Safety margin: stop before hitting the daily quota wall
# playlist.create = 50; each insert = 50
UNITS_PER_INSERT = 50
DAILY_QUOTA = 10_000
DEFAULT_MAX_INSERTS = (DAILY_QUOTA - 50) // UNITS_PER_INSERT  # ~199


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _load_credentials():
    """Load and refresh OAuth2 credentials from .secrets/."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    client_file = os.path.join(SECRETS_DIR, "youtube-oauth-client.json")
    token_file = os.path.join(SECRETS_DIR, "youtube-oauth-token.json")

    with open(client_file) as f:
        client_data = json.load(f)["installed"]

    with open(token_file) as f:
        token_data = json.load(f)

    # expiry_date is stored as milliseconds since epoch
    expiry_ms = token_data.get("expiry_date")
    expiry = datetime.datetime.utcfromtimestamp(expiry_ms / 1000) if expiry_ms else None

    creds = Credentials(
        token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=client_data["token_uri"],
        client_id=client_data["client_id"],
        client_secret=client_data["client_secret"],
        scopes=[token_data.get("scope", "https://www.googleapis.com/auth/youtube")],
        expiry=expiry,
    )

    if creds.expired or not creds.valid:
        print("Token expired — refreshing...")
        creds.refresh(Request())
        # Persist refreshed token
        token_data["access_token"] = creds.token
        token_data["expiry_date"] = int(creds.expiry.timestamp() * 1000)
        with open(token_file, "w") as f:
            json.dump(token_data, f, indent=2)
        print("Token refreshed and saved.")

    return creds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from a watch URL."""
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def _load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"playlist_id": None, "added_video_ids": [], "skipped": [], "total_added": 0}


def _save_progress(progress: dict):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# YouTube API calls
# ---------------------------------------------------------------------------

def _build_youtube(creds):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds)


def _create_playlist(youtube, dry_run: bool) -> str:
    """Create the playlist and return its ID."""
    print(f"Creating playlist: «{PLAYLIST_NAME}»...")
    if dry_run:
        fake_id = "DRY_RUN_PLAYLIST_ID"
        print(f"  [dry-run] Would create playlist → id={fake_id}")
        return fake_id

    body = {
        "snippet": {
            "title": PLAYLIST_NAME,
            "description": PLAYLIST_DESCRIPTION,
        },
        "status": {"privacyStatus": "public"},
    }
    response = youtube.playlists().insert(part="snippet,status", body=body).execute()
    playlist_id = response["id"]
    print(f"  Playlist created → id={playlist_id}")
    print(f"  URL: https://www.youtube.com/playlist?list={playlist_id}")
    return playlist_id


def _add_video_to_playlist(youtube, playlist_id: str, video_id: str, dry_run: bool):
    if dry_run:
        return
    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
    }
    youtube.playlistItems().insert(part="snippet", body=body).execute()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Create YouTube playlist and add songs.")
    parser.add_argument(
        "--max-inserts",
        type=int,
        default=DEFAULT_MAX_INSERTS,
        help=f"Max videos to insert this run (default: {DEFAULT_MAX_INSERTS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without calling the API",
    )
    args = parser.parse_args()

    # Load songs
    with open(SONGS_FILE) as f:
        songs = json.load(f)
    songs_with_url = [s for s in songs if s.get("youtube_url")]
    print(f"Songs with YouTube URL: {len(songs_with_url)}")

    # Load progress
    progress = _load_progress()
    already_added = set(progress["added_video_ids"])
    print(f"Already added in previous runs: {len(already_added)}")

    # Build pending list (preserve original order, skip already added)
    pending = []
    for s in songs_with_url:
        vid = _extract_video_id(s["youtube_url"])
        if not vid:
            progress["skipped"].append({"song": s["song"], "artist": s["artist"], "url": s["youtube_url"], "reason": "bad_url"})
            continue
        if vid not in already_added:
            pending.append((vid, s))

    print(f"Pending to add: {len(pending)}")
    print(f"Max inserts this run: {args.max_inserts}")
    print()

    if not pending:
        print("Nothing to do — all songs already added!")
        if progress["playlist_id"]:
            print(f"Playlist: https://www.youtube.com/playlist?list={progress['playlist_id']}")
        return

    # Auth + API client
    if not args.dry_run:
        creds = _load_credentials()
        youtube = _build_youtube(creds)
    else:
        youtube = None

    # Create playlist if needed
    if not progress["playlist_id"]:
        playlist_id = _create_playlist(youtube, args.dry_run)
        if not args.dry_run:
            progress["playlist_id"] = playlist_id
            _save_progress(progress)
    else:
        playlist_id = progress["playlist_id"]
        print(f"Resuming playlist id={playlist_id}")
        print(f"  URL: https://www.youtube.com/playlist?list={playlist_id}")

    # Add videos
    inserted = 0
    errors = 0
    batch = pending[: args.max_inserts]

    for i, (video_id, song) in enumerate(batch, 1):
        label = f"{song.get('artist', '?')} — {song.get('song', '?')}"
        try:
            _add_video_to_playlist(youtube, playlist_id, video_id, args.dry_run)
            inserted += 1
            print(f"  [{i}/{len(batch)}] + {label} ({video_id})")
            if not args.dry_run:
                already_added.add(video_id)
                progress["added_video_ids"].append(video_id)
                progress["total_added"] = len(progress["added_video_ids"])
        except Exception as e:
            err_str = str(e)
            if "quotaExceeded" in err_str:
                print(f"\n  QUOTA EXHAUSTED at item {i}. Stop for today.", file=sys.stderr)
                print("  Run again tomorrow — quota resets daily at midnight Pacific.", file=sys.stderr)
                break
            errors += 1
            print(f"  [{i}/{len(batch)}] ERROR {label}: {e}", file=sys.stderr)
            if not args.dry_run:
                progress["skipped"].append({"song": song["song"], "artist": song["artist"], "video_id": video_id, "reason": err_str})

        # Save progress every 10 inserts (real runs only)
        if not args.dry_run and i % 10 == 0:
            _save_progress(progress)

        # Small delay to be polite to the API
        if not args.dry_run:
            time.sleep(0.3)

    if not args.dry_run:
        _save_progress(progress)

    # Summary
    remaining = len(pending) - inserted
    print()
    print("=" * 50)
    print(f"Run complete.")
    print(f"  Inserted this run : {inserted}")
    print(f"  Errors            : {errors}")
    print(f"  Total in playlist : {progress['total_added']}")
    print(f"  Still pending     : {remaining}")
    if remaining > 0:
        days_left = -(-remaining // args.max_inserts)  # ceiling division
        print(f"  (~{days_left} more run(s) needed to finish)")
    print(f"  Playlist URL: https://www.youtube.com/playlist?list={playlist_id}")


if __name__ == "__main__":
    main()
