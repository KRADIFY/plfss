@echo off
cd /d "%~dp0"
"C:\Python314\python.exe" -B tools\resume_vectorization.py --workers 2
if errorlevel 1 goto erreur
echo Preparation locale uniquement. Aucun GPU lance.
pause
exit /b 0
:erreur
echo Preparation arretee : les points de reprise sont conserves.
pause
exit /b 1
