#!/bin/bash
echo "🔄 Resetting corrupted database..."
python3 scripts/reset_database.py

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Database reset complete! You can now run: python app.py"
else
    echo ""
    echo "❌ Database reset failed!"
    exit 1
fi
