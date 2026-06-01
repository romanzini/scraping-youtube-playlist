# Scraping to YouTube Playlist

Uma ferramenta automatizada para extrair dados de músicas, normalizar metadados (via MusicBrainz) e criar uma playlist no YouTube contendo apenas vídeos com imagem (excluindo faixas puramente em áudio).

## Arquitetura

O projeto é dividido em três fases principais:

1.  **Extração (`extractor/`)**: Busca dados de músicas e pesquisa no YouTube, garantindo que o resultado seja um videoclipe (com streams de imagem, evitando vídeos de "apenas áudio"). Usa `yt-dlp` e YouTube Data API v3.
2.  **Normalização (`normalize_youtube.py`)**: Valida e padroniza títulos e artistas usando a API do MusicBrainz, lidando com caracteres especiais e formatos inconsistentes.
3.  **Criação de Playlist (`create_playlist.py`)**: Insere os vídeos encontrados em uma playlist no YouTube, respeitando rigorosamente os limites de cota da API (aproximadamente 200 inserções por dia) e mantendo o progresso localmente para retomar em dias subsequentes.

## Requisitos

*   Python 3.10+
*   Gerenciador de pacotes `uv` (recomendado)
*   Google Cloud Platform (GCP) com YouTube Data API v3 ativada.
*   Credenciais OAuth 2.0 salvas em `.secrets/client_secrets.json`.

## Configuração

1.  Clone o repositório.
2.  Instale as dependências usando o `uv`:
    ```bash
    uv sync
    ```
3.  Crie a pasta `.secrets` na raiz do projeto.
4.  Coloque seu arquivo de credenciais OAuth do Google em `.secrets/client_secrets.json`.

## Como Usar

### 1. Extração (e/ou Normalização)
Para executar a normalização das músicas com o MusicBrainz:
```bash
uv run python normalize_youtube.py
```
*(Você pode usar `uv run python normalize_youtube.py --retry-not-found` para tentar novamente músicas que falharam na normalização anterior).*

Para monitorar o processo de normalização:
```bash
uv run python monitor_normalize.py
```

### 2. Criação da Playlist
Para criar a playlist e adicionar os vídeos:
```bash
uv run python create_playlist.py
```
**Nota sobre Cotas:** A API do YouTube possui um limite diário estrito (geralmente permitindo ~200 inserções por dia). O script acompanha o progresso em `output/playlist_progress.json`. Quando o limite for atingido, o script irá parar. Você deve rodar o mesmo comando no dia seguinte (após a meia-noite no fuso horário do Pacífico) e ele continuará de onde parou automaticamente.

### 3. Utilitários
*   **Verificar Progresso:** `uv run python check_progress.py` ou `uv run python check_status.py`
*   **Listar Músicas Não Encontradas:** `uv run python show_notfound.py`

## Estrutura de Arquivos

*   `extractor/youtube_search.py`: Lógica de busca no YouTube (filtros para vídeos com imagem).
*   `normalize_youtube.py`: Integração com MusicBrainz.
*   `create_playlist.py`: Interação com a API de Playlists do YouTube.
*   `output/`: Contém os estados das execuções (`music_data.json`, `music_data_normalized.json`, `playlist_progress.json`).
*   `test_*.py`: Scripts para testar os filtros do YouTube e comportamento de busca.

## Licença

Este projeto é de uso pessoal.
