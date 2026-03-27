#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  🔐 IP Changer — Запуск
#  Просто двічі клікніть на цей файл або запустіть в терміналі
# ═══════════════════════════════════════════════════════════════

# Перейти в папку де лежить скрипт
cd "$(dirname "$0")"

# Перевірити чи є Python
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo ""
    echo "  ❌ Python не знайдено!"
    echo ""
    echo "  Щоб встановити Python на macOS:"
    echo "  1. Відкрийте браузер"
    echo "  2. Перейдіть на https://www.python.org/downloads/"
    echo "  3. Натисніть 'Download Python'"
    echo "  4. Встановіть завантажений файл"
    echo "  5. Спробуйте знову запустити цей файл"
    echo ""
    read -p "  Натисніть Enter щоб закрити..."
    exit 1
fi

echo ""
echo "  ✅ Python знайдено: $($PYTHON --version)"
echo "  🚀 Запускаю IP Changer..."
echo ""

$PYTHON ip_changer.py

# Якщо скрипт завершився з помилкою — не закривати вікно
if [ $? -ne 0 ]; then
    echo ""
    echo "  ❌ Виникла помилка. Зверніться до адміністратора."
    echo ""
    read -p "  Натисніть Enter щоб закрити..."
fi
