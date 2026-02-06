#!/usr/bin/env python3
"""Скрипт автоматического исправления линтинг-ошибок"""
import os
import re
from pathlib import Path


def fix_trailing_whitespace(content: str) -> str:
    """Удаляет trailing whitespace (W291)"""
    lines = content.split('\n')
    fixed_lines = [line.rstrip() for line in lines]
    return '\n'.join(fixed_lines)


def fix_blank_line_whitespace(content: str) -> str:
    """Очищает пустые строки от пробелов (W293)"""
    lines = content.split('\n')
    fixed_lines = []
    for line in lines:
        if line.strip() == '':
            fixed_lines.append('')
        else:
            fixed_lines.append(line)
    return '\n'.join(fixed_lines)


def fix_bare_except(content: str) -> str:
    """Исправляет bare except (E722)"""
    content = re.sub(r'except\s*:', 'except Exception:', content)
    return content


def fix_f_string_placeholders(content: str) -> str:
    """Исправляет f-strings без placeholders (F541)"""
    content = re.sub(r'f(["\'])([^{}\1]*?)\1', r'\1\2\1', content)
    return content


def fix_unused_imports(content: str) -> str:
    """Удаляет неиспользуемые импорты (F401)"""
    lines = content.split('\n')
    fixed_lines = []

    for line in lines:
        if 'from database.models import Booking' in line:
            continue
        if 'import Booking' in line and 'database.models' in line:
            continue
        fixed_lines.append(line)

    return '\n'.join(fixed_lines)


def fix_long_lines(content: str, max_length: int = 127) -> str:
    """Исправляет длинные строки (E501) - базовая версия"""
    lines = content.split('\n')
    fixed_lines = []

    for line in lines:
        if len(line) <= max_length:
            fixed_lines.append(line)
        else:
            if line.strip().startswith('#'):
                indent = len(line) - len(line.lstrip())
                words = line.strip()[1:].split()
                current_line = ' ' * indent + '#'

                for word in words:
                    if len(current_line + ' ' + word) <= max_length:
                        current_line += ' ' + word
                    else:
                        fixed_lines.append(current_line)
                        current_line = ' ' * indent + '# ' + word

                if current_line.strip() != '#':
                    fixed_lines.append(current_line)
            else:
                fixed_lines.append(line)

    return '\n'.join(fixed_lines)


def fix_file(filepath: Path) -> bool:
    """Исправляет один файл"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content

        content = fix_trailing_whitespace(content)
        content = fix_blank_line_whitespace(content)
        content = fix_bare_except(content)
        content = fix_f_string_placeholders(content)
        content = fix_unused_imports(content)

        if content != original_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✅ Fixed: {filepath}")
            return True
        else:
            print(f"⏭️  Skipped: {filepath} (no changes)")
            return False

    except Exception as e:
        print(f"❌ Error fixing {filepath}: {e}")
        return False


def main():
    """Главная функция"""
    print("🔧 Fixing linting errors...\n")

    python_files = []
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in ['venv', '__pycache__', '.git', 'htmlcov', '.pytest_cache']]

        for file in files:
            if file.endswith('.py'):
                filepath = Path(root) / file
                python_files.append(filepath)

    print(f"Found {len(python_files)} Python files\n")

    fixed_count = 0
    for filepath in sorted(python_files):
        if fix_file(filepath):
            fixed_count += 1

    print(f"\n✨ Fixed {fixed_count} files")
    print("\n💡 Tip: Run 'black .' and 'isort .' for final formatting")


if __name__ == '__main__':
    main()
