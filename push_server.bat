@echo off
chcp 65001 > nul
cls
echo ==========================================
echo        DEXRY AUTO PUSH TO GITHUB
echo ==========================================

:: 1. Kiểm tra xem thư mục đã khởi tạo Git chưa
if not exist ".git" (
    echo [Thong bao] Chua co kho lu tru Git, dang khoi tao...
    git init
    git branch -M main
    git remote add origin https://github.com/thhaolove/thhaoweb.git
)

:: 2. Kiểm tra thay đổi code
echo Dang kiem tra thay doi code...
git status

:: 3. Nhập nội dung commit từ bạn
set /p commit_msg="Nhap noi dung commit (Mac dinh la 'update code'): "
if "%commit_msg%"=="" set commit_msg=update code

:: 4. Tiến hành Add, Commit
git add .
git commit -m "%commit_msg%"

:: 5. Kéo code mới nhất từ GitHub về trước để tránh lỗi xung đột (dùng --rebase)
echo Dang dong bo code tu GitHub...
git pull origin main --rebase

:: 6. Đẩy code lên GitHub (nếu vẫn bị kẹt conflict thì tự động ép push bản ở máy lên)
echo Dang push len GitHub...
git push -u origin main
if %errorlevel% neq 0 (
    echo [Canh bao] Phat hien xung đột hoac tu choi, dang ep day code len...
    git push -u origin main --force
)

echo ==========================================
echo   HOAN TAT! Code da duoc day len GitHub.
echo ==========================================
pause