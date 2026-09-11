@echo off
echo ==========================================
echo   DEXRY AUTO PUSH TO GITHUB & RENDER
echo ==========================================

echo Dang kiem tra thay doi code...
git add .

set /p msg=Nhap noi dung commit (Vi du: update code moi): 
if "%msg%"=="" set msg=update server code

git commit -m "%msg%"

echo Dang push len GitHub...
git push origin main

echo ==========================================
echo   HOAN TAT! Hay doi 1-2 phut de Render deploy.
echo ==========================================
pause