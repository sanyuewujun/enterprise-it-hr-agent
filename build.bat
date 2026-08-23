@echo off
cd /d C:\Users\SatoY\Desktop\AI-Agent\RAGProjeact
docker compose up -d --build > build.log 2>&1
echo BUILD_DONE >> build.log
