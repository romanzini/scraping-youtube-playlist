#!/bin/bash
# Script para monitorar o progresso da normalização

cd ~/repos/scraping

echo "=================================================="
echo "Iniciando normalização em background..."
echo "=================================================="
echo ""

# Roda o processo de normalização
.venv/bin/python normalize_youtube.py &
PID=$!

echo "Processo iniciado com PID: $PID"
echo "Para ver o progresso em tempo real:"
echo "  tail -f output/normalize.log"
echo ""
echo "Para verificar status:"
echo "  python check_status.py"
echo ""
echo "O processo continuará rodando mesmo se você fechar este terminal."
echo "=================================================="
echo ""
echo "Exibindo progresso inicial (últimas 10 linhas do log):"
echo ""

# Aguarda um pouco para o log começar a ser gerado
sleep 5

# Mostra as últimas linhas do log
tail -10 output/normalize.log

echo ""
echo "=================================================="
echo "Processo rodando em background. Para acompanhar:"
echo "  wsl bash -c 'cd ~/repos/scraping && tail -f output/normalize.log'"
echo "=================================================="
