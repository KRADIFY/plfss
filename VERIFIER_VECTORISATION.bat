@echo off
cd /d "%~dp0"
"C:\Python314\python.exe" -B tools\verify_memo_vectorization.py
if errorlevel 1 goto erreur
echo Lire vectorization\memo-20261004\preparation-audit.json avant toute demande RunPod.
pause
exit /b 0
:erreur
echo Controle non termine : consulter les fichiers de vectorization.
pause
exit /b 1
