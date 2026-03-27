#!/usr/bin/env python3
"""
Генератор config.json для IP Changer.
Сканує папку з ключами і автоматично розподіляє їх по країнах NordVPN.

Використання:
  python3 generate_config.py /шлях/до/ключів             — випадковий розподіл (ЗА ЗМОВЧУВАННЯМ)
  python3 generate_config.py /шлях/до/ключів --no-shuffle — послідовний розподіл
"""

import json
import os
import sys
import random

# Доступні країни (Тільки ЄС + Україна)
NORDVPN_COUNTRIES = [
    "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czech Republic",
    "Denmark", "Estonia", "Finland", "France", "Germany", "Greece",
    "Hungary", "Ireland", "Italy", "Latvia", "Lithuania", "Luxembourg",
    "Netherlands", "Poland", "Portugal", "Romania", "Slovakia", "Slovenia",
    "Spain", "Sweden", "Ukraine"
]


def scan_keys(directory, extensions=None):
    """Сканувати папку і знайти файли ключів."""
    if extensions is None:
        extensions = [".dat", ".pfx", ".jks", ".zs2", ".sk", ".key", ".p12"]

    keys = []
    if not os.path.isdir(directory):
        print(f"Папка не знайдена: {directory}")
        return keys

    for entry in sorted(os.listdir(directory)):
        full_path = os.path.join(directory, entry)
        if os.path.isfile(full_path):
            _, ext = os.path.splitext(entry)
            if ext.lower() in extensions or not extensions:
                keys.append(entry)

    return keys


def generate_config(keys_directory, shuffle=True, output_file="config.json"):
    """Згенерувати config.json з автоматичним розподілом країн."""
    keys = scan_keys(keys_directory)

    if not keys:
        print(f"Ключі не знайдено в '{keys_directory}'")
        print(f"Підтримувані розширення: .dat, .pfx, .jks, .zs2, .sk, .key, .p12")
        sys.exit(1)

    print(f"Знайдено {len(keys)} ключів")

    # Prepare country list
    countries = list(NORDVPN_COUNTRIES)
    if shuffle:
        random.shuffle(countries)
        print("🔀 Країни перемішані випадковим чином")

    mappings = []
    for i, key_file in enumerate(keys):
        country = countries[i % len(countries)]
        name = os.path.splitext(key_file)[0]
        mappings.append({
            "key_file": key_file,
            "label": name,
            "country": country,
        })

    config = {
        "keys_directory": keys_directory,
        "browser_url": "https://cabinet.tax.gov.ua/",
        "open_browser": True,
        "mappings": mappings,
    }

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_file)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"✅ Конфіг збережено: {output_path}")
    print(f"Розподіл: {len(keys)} ключів по {len(countries)} країнах")

    # Show summary
    country_count = {}
    for m in mappings:
        country_count[m["country"]] = country_count.get(m["country"], 0) + 1

    print(f"\nКраїни з найбільшою кількістю ключів:")
    for country, count in sorted(country_count.items(), key=lambda x: -x[1])[:10]:
        print(f"  {country}: {count} ключів")

    # Validate
    print()
    validate_config(config, verbose=True)


def validate_config(config, verbose=False):
    """Валідація конфігурації."""
    warnings = []
    errors = []
    mappings = config.get("mappings", [])

    if not mappings:
        errors.append("Конфігурація не містить жодного ключа")
        if verbose:
            for e in errors:
                print(f"  ❌ {e}")
        return errors, warnings

    # Check for duplicate key files
    key_files = [m.get("key_file", "") for m in mappings]
    seen_keys = {}
    for i, kf in enumerate(key_files):
        if kf in seen_keys:
            warnings.append(f"Дублікат ключа: \"{kf}\" (рядки {seen_keys[kf]+1} і {i+1})")
        else:
            seen_keys[kf] = i

    # Check for empty fields
    for i, m in enumerate(mappings):
        if not m.get("key_file"):
            errors.append(f"Ключ #{i+1}: відсутнє ім'я файлу (key_file)")
        if not m.get("country"):
            errors.append(f"Ключ #{i+1}: відсутня країна (country)")
        if not m.get("label"):
            warnings.append(f"Ключ #{i+1} ({m.get('key_file', '?')}): відсутня назва (label)")

    # Check for invalid countries
    valid_countries = set(NORDVPN_COUNTRIES)
    for i, m in enumerate(mappings):
        country = m.get("country", "")
        if country and country not in valid_countries:
            warnings.append(f"Ключ #{i+1}: невідома країна \"{country}\" — можливо помилка")

    # Check country distribution
    country_count = {}
    for m in mappings:
        c = m.get("country", "")
        country_count[c] = country_count.get(c, 0) + 1

    # Warn if too many keys share same country (>6)
    for country, count in country_count.items():
        if count > 6:
            warnings.append(f"Країна \"{country}\" має {count} ключів — IP можуть повторюватись")

    if verbose:
        if errors:
            for e in errors:
                print(f"  ❌ {e}")
        if warnings:
            for w in warnings:
                print(f"  ⚠️  {w}")
        if not errors and not warnings:
            print(f"  ✅ Конфігурація валідна — проблем не знайдено")

    return errors, warnings


def main():
    if len(sys.argv) < 2:
        print("Використання:")
        print("  python3 generate_config.py /шлях/до/ключів")
        print("  python3 generate_config.py /шлях/до/ключів --no-shuffle")
        print()
        print("Опції:")
        print("  --no-shuffle    Не перемішувати країни (послідовний розподіл)")
        print()
        print("Приклад:")
        print("  python3 generate_config.py ~/Documents/keys")
        print()
        print("Підтримувані розширення: .dat, .pfx, .jks, .zs2, .sk, .key, .p12")
        sys.exit(1)

    keys_directory = os.path.expanduser(sys.argv[1])
    shuffle = "--no-shuffle" not in sys.argv
    generate_config(keys_directory, shuffle=shuffle)


if __name__ == "__main__":
    main()
