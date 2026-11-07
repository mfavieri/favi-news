@echo off
chcp 65001 >nul
title FaviNews - Servidor Local & Configurador PC
cd /d "d:\Projetos_Antigravity\favi-news"

echo =================================================================
echo ⚙️  FAVINEWS — INICIANDO SERVIDOR LOCAL E CONFIGURADOR PC
echo    Slogan: "Em 15 minutos tudo pode mudar !!"
echo    Login do Configurador: usr: FaviNews  ^|  psw: NewsFavi
echo =================================================================
echo.

echo [1/3] Sincronizando com a nuvem do GitHub (git pull)...
git pull --rebase -X theirs origin main >nul 2>&1

echo [2/3] Abrindo navegador em http://localhost:8090/?config=1 ...
start "" "http://localhost:8090/?config=1"

echo [3/3] Servidor local FaviNews ativo na porta 8090!
echo (Mantenha esta janela aberta enquanto estiver configurando; feche quando terminar)
echo.
python "d:\Projetos_Antigravity\favi-news\server.py" 8090
pause
