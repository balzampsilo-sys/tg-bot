"""
CLI для управления миграциями

Использование:
    python migrate.py migrate        # Применить все миграции
    python migrate.py migrate 3      # Применить до версии 3
    python migrate.py rollback 1     # Откатить до версии 1
    python migrate.py current        # Показать текущую версию
"""

import asyncio
import sys
import logging

from database.migrations.migration_manager import MigrationManager
from database.migrations.versions import InitialSchema, AddVersionColumn
from config import DATABASE_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def print_usage():
    """Print usage information"""
    print(__doc__)
    sys.exit(1)


async def main():
    """Main CLI function"""
    if len(sys.argv) < 2:
        print_usage()
    
    # Initialize migration manager
    manager = MigrationManager(DATABASE_PATH)
    
    # Register all migrations
    manager.register(InitialSchema)
    manager.register(AddVersionColumn)
    # Добавьте здесь новые миграции
    
    command = sys.argv[1].lower()
    
    try:
        if command == "migrate":
            version = int(sys.argv[2]) if len(sys.argv) > 2 else None
            await manager.migrate(version)
            current = await manager.get_current_version()
            print(f"\n✅ Migration completed! Current version: {current}")
            
        elif command == "rollback":
            if len(sys.argv) < 3:
                print("❌ Error: rollback requires target version")
                print("Usage: python migrate.py rollback <version>")
                sys.exit(1)
            
            version = int(sys.argv[2])
            await manager.rollback(version)
            current = await manager.get_current_version()
            print(f"\n✅ Rollback completed! Current version: {current}")
            
        elif command == "current":
            version = await manager.get_current_version()
            print(f"\n📊 Current database version: {version}")
            
            if manager.migrations:
                latest = max(m.version for m in manager.migrations)
                print(f"🎯 Latest available version: {latest}")
                
                if version < latest:
                    print(f"\n⚠️  Database needs migration ({version} -> {latest})")
                    print("Run: python migrate.py migrate")
                elif version == latest:
                    print("\n✅ Database is up to date!")
            
        else:
            print(f"❌ Unknown command: {command}")
            print_usage()
            
    except Exception as e:
        logging.error(f"❌ Migration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
