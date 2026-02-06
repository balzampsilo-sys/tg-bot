# 🧹 Руководство по исправлению линтинг-ошибок

Этот документ описывает, как исправить все линтинг-ошибки в проекте.

## 🚀 Быстрое исправление (Автоматически)

### Вариант 1: Через GitHub Actions

1. Перейдите на [Actions](https://github.com/balzampsilo-sys/tg-bot/actions)
2. Выберите workflow "Auto Format Code"
3. Нажмите "Run workflow"
4. Выберите ветку `main`
5. Нажмите "Run workflow"
6. ✅ **Готово!** Все ошибки исправлены автоматически

### Вариант 2: Локально

```bash
# 1. Установите инструменты
pip install black isort autoflake

# 2. Запустите скрипт исправления
python fix_linting.py

# 3. Удалите неиспользуемые импорты
autoflake --in-place --remove-all-unused-imports --remove-unused-variables \
  --ignore-init-module-imports --recursive . \
  --exclude venv,__pycache__,.git

# 4. Отсортируйте импорты
isort .

# 5. Отформатируйте код
black .

# 6. Проверьте результат
flake8 . --exclude=venv,__pycache__

# 7. Закоммитьте изменения
git add .
git commit -m "style: fix linting errors"
git push
```

---

## 🔍 Описание ошибок

### W291: Trailing whitespace

**Проблема:** Пробелы в конце строки

```python
# Плохо
print("Hello")    

# Хорошо
print("Hello")
```

**Исправление:** Удалите пробелы в конце строки

### W293: Blank line contains whitespace

**Проблема:** Пустые строки содержат пробелы

```python
# Плохо
def foo():
    pass
    
    
def bar():
    pass

# Хорошо
def foo():
    pass


def bar():
    pass
```

**Исправление:** Очистите пустые строки от пробелов

### E722: Do not use bare 'except'

**Проблема:** Использование `except:` без указания типа исключения

```python
# Плохо
try:
    do_something()
except:
    pass

# Хорошо
try:
    do_something()
except Exception as e:
    logger.error(f"Error: {e}")
```

**Исправление:** Укажите `Exception` или конкретный тип

### F401: Imported but unused

**Проблема:** Импорт не используется

```python
# Плохо
from database.models import Booking  # Не используется
from datetime import datetime

def foo():
    return datetime.now()

# Хорошо
from datetime import datetime

def foo():
    return datetime.now()
```

**Исправление:** Удалите неиспользуемые импорты

### F541: f-string without placeholders

**Проблема:** f-string без `{}`

```python
# Плохо
message = f"Hello World"

# Хорошо
message = "Hello World"

# Или если нужны placeholders
name = "Alice"
message = f"Hello {name}"
```

**Исправление:** Уберите `f` перед строкой или добавьте `{}`

### E501: Line too long

**Проблема:** Строка длиннее 127 символов

```python
# Плохо
my_very_long_variable_name = some_function_with_many_parameters(parameter1, parameter2, parameter3, parameter4, parameter5)

# Хорошо
my_very_long_variable_name = some_function_with_many_parameters(
    parameter1, 
    parameter2, 
    parameter3, 
    parameter4, 
    parameter5
)
```

**Исправление:** Разбейте на несколько строк (`black` сделает это автоматически)

---

## 🔧 Ручное исправление конкретных файлов

### Исправить один файл

```bash
# Удалить trailing whitespace
sed -i 's/[[:space:]]*$//' utils/helpers.py

# Исправить bare except
sed -i 's/except:/except Exception:/g' utils/helpers.py

# Отформатировать
black utils/helpers.py
isort utils/helpers.py
```

### Проверить конкретный файл

```bash
flake8 utils/helpers.py
```

---

## 🛡️ Предотвращение ошибок

### Pre-commit hooks

Установите pre-commit хуки, чтобы автоматически форматировать код перед коммитом:

```bash
# Установка
pip install pre-commit

# Создать .pre-commit-config.yaml
cat > .pre-commit-config.yaml << EOF
repos:
  - repo: https://github.com/psf/black
    rev: 24.1.0
    hooks:
      - id: black

  - repo: https://github.com/pycqa/isort
    rev: 5.13.0
    hooks:
      - id: isort

  - repo: https://github.com/pycqa/flake8
    rev: 7.0.0
    hooks:
      - id: flake8
        args: [--max-line-length=127]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
EOF

# Установить хуки
pre-commit install

# Запустить вручную
pre-commit run --all-files
```

### VS Code настройки

Добавьте в `.vscode/settings.json`:

```json
{
  "python.formatting.provider": "black",
  "python.linting.enabled": true,
  "python.linting.flake8Enabled": true,
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports": true
  },
  "files.trimTrailingWhitespace": true,
  "files.insertFinalNewline": true
}
```

---

## 📊 Текущие ошибки

По вашему отчету:

| Ошибка | Кол-во | Описание |
|---------|---------|-------------|
| W293 | 250 | Пустые строки с пробелами |
| W291 | 43 | Trailing whitespace |
| E722 | 4 | Bare except |
| F401 | 4 | Неиспользуемые импорты |
| F541 | 2 | f-strings без placeholders |
| E501 | 1 | Длинная строка |

**Итого:** 304 ошибки

---

## ✅ Рекомендация

Используйте **Вариант 1 (Через GitHub Actions)** - это самый простой способ!

1. Перейдите на https://github.com/balzampsilo-sys/tg-bot/actions
2. Выберите "Auto Format Code"
3. Нажмите "Run workflow" → "Run workflow"
4. ✅ **Готово!**

---

🎉 **После исправления все тесты будут проходить успешно!**
