"""CLI для управления миграциями"""

import asyncio
import sys
from database.migrations.migration_manager import MigrationManager
from database.migrations.versions.v004_add_services import AddServicesBackwardCompatible
from config import DATABASE_PATH


async def main():
    manager = MigrationManager(DATABASE_PATH)
    
    # Регистрируем все миграции
    manager.register(AddServicesBackwardCompatible)
    
    command = sys.argv[1] if len(sys.argv) > 1 else "migrate"
    
    if command == "migrate":
        version = int(sys.argv[2]) if len(sys.argv) > 2 else None
        await manager.migrate(version)
        print("\u2705 Migrations completed successfully")
    elif command == "rollback":
        if len(sys.argv) < 3:
            print("❌ Error: version required for rollback")
            print("Usage: python migrate.py rollback <version>")
            return
        version = int(sys.argv[2])
        await manager.rollback(version)
        print(f"\u2705 Rolled back to version {version}")
    elif command == "current":
        version = await manager.get_current_version()
        print(f"Current database version: {version}")
    else:
        print("Unknown command. Available: migrate, rollback, current")


if __name__ == "__main__":
    asyncio.run(main())
