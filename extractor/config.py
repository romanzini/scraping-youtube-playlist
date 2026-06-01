from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"
FRAMES_DIR = OUTPUT_DIR / "frames"          # frames extraídos dos vídeos

INPUT_FILE = OUTPUT_DIR / "lembradessesom.json"
PROGRESS_FILE = OUTPUT_DIR / "progress.json"
RESULTS_FILE = OUTPUT_DIR / "extracted_songs.json"

# Delay entre requisições (segundos) para evitar bloqueio do Instagram
REQUEST_DELAY = 3.0

# Intervalo entre frames extraídos do vídeo (segundos)
# Para reels de 30-75s com 5-10 músicas, 6s captura ~1 frame por música
FRAME_INTERVAL_SEC = 6.0

# Largura máxima para OCR (reduz resolução para acelerar processamento)
OCR_MAX_WIDTH = 720

# OCR
OCR_LANGUAGES = ["pt", "en"]
OCR_CONFIDENCE_THRESHOLD = 0.3

# yt-dlp: número de retentativas em caso de erro
YTDLP_RETRIES = 3
