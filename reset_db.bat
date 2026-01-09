@echo off
echo 🔄 Resetting corrupted database...
python scripts/reset_database.py
if %errorlevel% equ 0 (
    echo.
    echo ✅ Database reset complete! You can now run: python app.py
    pause
) else (
    echo.
    echo ❌ Database reset failed!
    pause
)
