#!/usr/bin/env python3
"""
Database Reset Script
This script safely deletes the corrupted database and reinitializes it.
"""

import os
import sys
import shutil
from pathlib import Path

def reset_database():
    """Reset the corrupted database by deleting and recreating it."""
    
    # Get the project root directory
    project_root = Path(__file__).parent.parent
    
    # Database file paths to check and remove
    db_files = [
        project_root / "database.db",
        project_root / "instance" / "database.db",
        project_root / "app.db"
    ]
    
    print("🔄 Resetting corrupted database...")
    
    # Remove corrupted database files
    for db_file in db_files:
        if db_file.exists():
            try:
                db_file.unlink()
                print(f"✅ Removed corrupted database: {db_file}")
            except Exception as e:
                print(f"❌ Error removing {db_file}: {e}")
    
    # Remove instance directory if it exists and is empty
    instance_dir = project_root / "instance"
    if instance_dir.exists():
        try:
            if not any(instance_dir.iterdir()):  # Check if directory is empty
                instance_dir.rmdir()
                print("✅ Removed empty instance directory")
        except Exception as e:
            print(f"⚠️  Could not remove instance directory: {e}")
    
    # Remove receipts directory (optional - contains generated PDFs)
    receipts_dir = project_root / "receipts"
    if receipts_dir.exists():
        try:
            shutil.rmtree(receipts_dir)
            print("✅ Removed receipts directory")
        except Exception as e:
            print(f"⚠️  Could not remove receipts directory: {e}")
    
    print("\n✨ Database reset complete!")
    print("📝 Next steps:")
    print("   1. Run: python app.py")
    print("   2. The app will automatically create a fresh database")
    print("   3. Default test accounts will be created:")
    print("      - john@example.com / Password123")
    print("      - jane@example.com / Password123")

if __name__ == "__main__":
    try:
        reset_database()
    except KeyboardInterrupt:
        print("\n❌ Database reset cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error during database reset: {e}")
        sys.exit(1)
