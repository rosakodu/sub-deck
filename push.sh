#!/bin/bash
# Скрипт для отправки кода в репозиторий sub-deck

echo "Отправка изменений в ветку main..."
git push -u origin main

if [ $? -eq 0 ]; then
    echo "🎉 Успешно отправлено на GitHub!"
else
    echo "❌ Ошибка при отправке."
fi
