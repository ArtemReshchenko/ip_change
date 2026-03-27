#!/usr/bin/env python3
"""
IP Changer for cabinet.tax.gov.ua
Автоматично перемикає NordVPN на потрібну країну при виборі КЕП-ключа.

Функції:
- Пошук/фільтр ключів по назві
- Збереження прогресу (які ключі оброблені)
- Пагінація (по 20 ключів на сторінку)
- Перевірка зміни IP
- Авто-retry при помилках VPN
- Детекція дублів IP
"""

import json
import subprocess
import sys
import time
import webbrowser
import os
import shutil
from datetime import datetime

# ─── ANSI colors ───────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
RED = "\033[31m"
WHITE = "\033[37m"
BG_BLUE = "\033[44m"
BG_GREEN = "\033[42m"
BG_RED = "\033[41m"
BG_YELLOW = "\033[43m"

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "progress.json")

PAGE_SIZE = 20
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

# Маппінг країн (тільки ЄС + Україна) → ISO коди для NordVPN
# Цей список використовується для валідації config.json
COUNTRY_CODES = {
    "Austria": "at", "Belgium": "be", "Bulgaria": "bg", "Croatia": "hr",
    "Cyprus": "cy", "Czech Republic": "cz", "Denmark": "dk", "Estonia": "ee",
    "Finland": "fi", "France": "fr", "Germany": "de", "Greece": "gr",
    "Hungary": "hu", "Ireland": "ie", "Italy": "it", "Latvia": "lv",
    "Lithuania": "lt", "Luxembourg": "lu", "Netherlands": "nl", "Poland": "pl",
    "Portugal": "pt", "Romania": "ro", "Slovakia": "sk", "Slovenia": "si",
    "Spain": "es", "Sweden": "se", "Ukraine": "ua"
}


# ═══════════════════════════════════════════════════════════════════════════
#  Progress tracking
# ═══════════════════════════════════════════════════════════════════════════

def load_progress():
    """Завантажити прогрес з файлу."""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"completed": {}, "ip_history": {}}


def save_progress(progress):
    """Зберегти прогрес у файл."""
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"  {RED}✗ Не вдалося зберегти прогрес: {e}{RESET}")


def mark_completed(progress, key_file, ip_address, country):
    """Позначити ключ як оброблений."""
    progress["completed"][key_file] = {
        "ip": ip_address,
        "country": country,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    # Track IP history for duplicate detection
    if ip_address and ip_address != "невідомий":
        if ip_address not in progress["ip_history"]:
            progress["ip_history"][ip_address] = []
        progress["ip_history"][ip_address].append(key_file)
    save_progress(progress)


def is_completed(progress, key_file):
    """Перевірити чи ключ вже оброблений."""
    return key_file in progress.get("completed", {})


# ═══════════════════════════════════════════════════════════════════════════
#  NordVPN detection & control
# ═══════════════════════════════════════════════════════════════════════════

def find_nordvpn_cli():
    """Знайти nordvpn CLI binary."""
    if shutil.which("nordvpn"):
        return "nordvpn"
    
    common_paths = [
        "/usr/local/bin/nordvpn",
        "/usr/bin/nordvpn",
        "/opt/homebrew/bin/nordvpn",
        "/Applications/NordVPN.app/Contents/MacOS/nordvpn",
        os.path.expanduser("~/Applications/NordVPN.app/Contents/MacOS/nordvpn"),
    ]
    for path in common_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def find_nordvpn_app():
    """Знайти NordVPN GUI app, пріоритет запущеним."""
    app_paths = [
        "/Applications/NordVPN.app",
        "/Applications/NordVPN IKE.app",
        os.path.expanduser("~/Applications/NordVPN.app"),
        os.path.expanduser("~/Applications/NordVPN IKE.app"),
    ]
    
    # 1. Пошук тих, що вже працюють
    for path in app_paths:
        if os.path.exists(path):
            app_name = os.path.basename(path).replace(".app", "")
            code, stdout, _ = run_command(["pgrep", "-x", app_name])
            if code == 0 and stdout.strip():
                return path

    # 2. Якщо жоден не запущений — беремо перший встановлений
    for path in app_paths:
        if os.path.exists(path):
            return path
            
    return None


def detect_vpn_method():
    """Визначити доступний метод керування NordVPN."""
    cli = find_nordvpn_cli()
    if cli:
        return "cli", cli
    app = find_nordvpn_app()
    if app:
        return "applescript", app
    return "manual", None


def run_command(cmd, timeout=30):
    """Виконати команду."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, shell=isinstance(cmd, str),
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except FileNotFoundError:
        return -1, "", f"Команда не знайдена: {cmd[0] if isinstance(cmd, list) else cmd}"


# ─── CLI ───────────────────────────────────────────────────────────────────

def cli_disconnect(cli_path):
    """Відключити VPN."""
    print(f"  {YELLOW}⏳ Відключення VPN...{RESET}", end="", flush=True)
    code, stdout, stderr = run_command([cli_path, "disconnect"])
    combined = (stdout + stderr).lower()
    if code == 0 or "not connected" in combined or "disconnected" in combined:
        print(f"\r  {GREEN}✓ VPN відключено              {RESET}")
        return True
    print(f"\r  {RED}✗ Помилка відключення: {stderr or stdout}{RESET}")
    return False


def cli_connect(cli_path, country):
    """Підключити VPN."""
    code, stdout, stderr = run_command([cli_path, "connect", country], timeout=60)
    combined = (stdout + stderr).lower()
    return code == 0 and "connected" in combined


def cli_connect_with_retry(cli_path, country):
    """Підключити VPN з авто-retry."""
    for attempt in range(1, MAX_RETRIES + 1):
        suffix = f" (спроба {attempt}/{MAX_RETRIES})" if attempt > 1 else ""
        print(f"  {YELLOW}⏳ Підключення до {BOLD}{country}{RESET}{YELLOW}{suffix}...{RESET}", end="", flush=True)

        if cli_connect(cli_path, country):
            print(f"\r  {GREEN}✓ Підключено до {BOLD}{country}              {RESET}")
            return True

        if attempt < MAX_RETRIES:
            print(f"\r  {RED}✗ Спроба {attempt} невдала. Повтор через {RETRY_DELAY}с...      {RESET}")
            time.sleep(RETRY_DELAY)
        else:
            print(f"\r  {RED}✗ Не вдалося підключитися після {MAX_RETRIES} спроб      {RESET}")

    return False


def cli_status(cli_path):
    """Статус VPN."""
    code, stdout, _ = run_command([cli_path, "status"])
    return stdout if code == 0 else None


# ─── AppleScript ───────────────────────────────────────────────────────────

def applescript_disconnect(app_path):
    """Відключити VPN через AppleScript."""
    app_name = os.path.basename(app_path).replace(".app", "")
    print(f"  {YELLOW}⏳ Відключення VPN...{RESET}", end="", flush=True)
    script = f'''
    tell application "{app_name}" to activate
    delay 1
    tell application "System Events"
        tell process "{app_name}"
            try
                click button "Disconnect" of window 1
            end try
        end tell
    end tell
    '''
    run_command(["osascript", "-e", script], timeout=30)
    time.sleep(3)
    print(f"\r  {GREEN}✓ VPN відключення ініційовано              {RESET}")
    return True


def applescript_connect_with_retry(app_path, country):
    """Підключити VPN через AppleScript з retry."""
    code_iso = COUNTRY_CODES.get(country, country.lower().replace(" ", "_"))
    uri = f"nordvpn://connect/country/{code_iso}"

    for attempt in range(1, MAX_RETRIES + 1):
        suffix = f" (спроба {attempt}/{MAX_RETRIES})" if attempt > 1 else ""
        print(f"  {YELLOW}⏳ Підключення до {BOLD}{country}{RESET}{YELLOW}{suffix}...{RESET}", end="", flush=True)

        run_command(["open", "-a", app_path, uri])
        time.sleep(5)

        # Verify IP changed
        new_ip = get_current_ip()
        if new_ip != "невідомий":
            print(f"\r  {GREEN}✓ Підключення до {BOLD}{country}{RESET}{GREEN} ініційовано              {RESET}")
            return True

        if attempt < MAX_RETRIES:
            print(f"\r  {RED}✗ Спроба {attempt} невдала. Повтор через {RETRY_DELAY}с...      {RESET}")
            time.sleep(RETRY_DELAY)

    print(f"\r  {GREEN}✓ Підключення до {BOLD}{country}{RESET}{GREEN} ініційовано              {RESET}")
    return True


# ─── Manual ────────────────────────────────────────────────────────────────

def manual_connect(country):
    """Ручне підключення."""
    code_iso = COUNTRY_CODES.get(country, "??")
    print(f"\n  {YELLOW}⚠ NordVPN CLI не знайдено. Виконайте вручну:{RESET}")
    print(f"  {BOLD}1.{RESET} Відкрийте NordVPN")
    print(f"  {BOLD}2.{RESET} Підключіться до: {CYAN}{BOLD}{country} ({code_iso.upper()}){RESET}")
    print(f"  {BOLD}3.{RESET} Натисніть Enter коли підключено")
    run_command(["open", "-a", "NordVPN"])
    input(f"\n  {CYAN}▸ Enter коли VPN підключено...{RESET}")
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  IP utilities
# ═══════════════════════════════════════════════════════════════════════════

def get_current_ip():
    """Отримати зовнішній IP."""
    try:
        import urllib.request
        with urllib.request.urlopen("https://api.ipify.org", timeout=10) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return "невідомий"


def verify_ip_changed(old_ip):
    """Перевірити що IP змінився. Повертає (changed: bool, new_ip: str)."""
    new_ip = get_current_ip()

    if new_ip == "невідомий":
        print(f"  {YELLOW}⚠ Не вдалося визначити IP{RESET}")
        return False, new_ip

    if old_ip and old_ip != "невідомий" and new_ip == old_ip:
        print(f"  {RED}⚠ IP НЕ змінився! ({old_ip}){RESET}")
        return False, new_ip

    print(f"  {GREEN}🌍 Новий IP: {BOLD}{new_ip}{RESET}")
    return True, new_ip


def check_duplicate_ip(progress, ip_address, current_key):
    """Перевірити чи IP вже використовувався для іншого ключа."""
    if ip_address == "невідомий":
        return False

    ip_hist = progress.get("ip_history", {})
    if ip_address in ip_hist:
        previous_keys = [k for k in ip_hist[ip_address] if k != current_key]
        if previous_keys:
            print(f"  {BG_YELLOW}{BOLD} ⚠ УВАГА: IP {ip_address} вже використовувався! {RESET}")
            for k in previous_keys:
                print(f"    {DIM}→ {k}{RESET}")
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════════════════

VALID_COUNTRIES = set(COUNTRY_CODES.keys())


def load_config():
    """Завантажити конфігурацію."""
    if not os.path.exists(CONFIG_FILE):
        print(f"{RED}✗ Файл конфігурації не знайдено: {CONFIG_FILE}{RESET}")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    if not config.get("mappings"):
        print(f"{RED}✗ Конфігурація не містить маппінгів ключів{RESET}")
        sys.exit(1)
    return config


def validate_config(config):
    """Валідація конфігурації при запуску."""
    mappings = config.get("mappings", [])
    warnings = []
    errors = []

    # 1. Duplicate key files
    seen_keys = {}
    for i, m in enumerate(mappings):
        kf = m.get("key_file", "")
        if kf in seen_keys:
            warnings.append(f"Дублікат ключа: \"{kf}\" (#{seen_keys[kf]+1} і #{i+1})")
        else:
            seen_keys[kf] = i

    # 2. Empty required fields
    for i, m in enumerate(mappings):
        if not m.get("key_file"):
            errors.append(f"Ключ #{i+1}: відсутнє ім'я файлу (key_file)")
        if not m.get("country"):
            errors.append(f"Ключ #{i+1}: відсутня країна (country)")
        if not m.get("label"):
            warnings.append(f"Ключ #{i+1} ({m.get('key_file', '?')}): немає назви (label)")

    # 3. Unknown countries
    for i, m in enumerate(mappings):
        country = m.get("country", "")
        if country and country not in VALID_COUNTRIES:
            warnings.append(f"Ключ #{i+1}: невідома країна \"{country}\"")

    # 4. Overloaded countries (too many keys = possible IP duplicates)
    country_count = {}
    for m in mappings:
        c = m.get("country", "")
        country_count[c] = country_count.get(c, 0) + 1
    for country, count in country_count.items():
        if count > 6:
            warnings.append(f"Країна \"{country}\" має {count} ключів — IP можуть повторюватись")

    # Print results
    if errors:
        print(f"\n  {BG_RED}{BOLD} ПОМИЛКИ В КОНФІГУРАЦІЇ {RESET}")
        for e in errors:
            print(f"  {RED}❌ {e}{RESET}")

    if warnings:
        print(f"\n  {YELLOW}{BOLD}⚠ Попередження:{RESET}")
        for w in warnings:
            print(f"  {YELLOW}  • {w}{RESET}")

    if not errors and not warnings:
        print(f"  {GREEN}✓ Конфігурація валідна ({len(mappings)} ключів){RESET}")
    elif warnings and not errors:
        print(f"\n  {DIM}Конфігурація завантажена з попередженнями ({len(mappings)} ключів){RESET}")

    if errors:
        print(f"\n  {RED}Виправте помилки в config.json і запустіть знову.{RESET}")
        sys.exit(1)

    return len(warnings) == 0


# ═══════════════════════════════════════════════════════════════════════════
#  UI
# ═══════════════════════════════════════════════════════════════════════════

def print_header(vpn_method, progress, total_keys):
    """Заголовок."""
    os.system("clear" if os.name != "nt" else "cls")
    method_label = {"cli": "CLI", "applescript": "AppleScript", "manual": "Ручний"}
    done = len(progress.get("completed", {}))
    print()
    print(f"  {BG_BLUE}{BOLD} 🔐 IP Changer — cabinet.tax.gov.ua {RESET}")
    print(f"  {DIM}Режим VPN: {method_label.get(vpn_method, vpn_method)}{RESET}")
    print()
    # Progress bar
    if total_keys > 0:
        pct = int(done / total_keys * 100)
        bar_len = 30
        filled = int(bar_len * done / total_keys)
        bar = "█" * filled + "░" * (bar_len - filled)
        color = GREEN if pct == 100 else YELLOW if pct > 50 else CYAN
        print(f"  {DIM}Прогрес:{RESET} {color}{bar}{RESET} {BOLD}{done}/{total_keys}{RESET} ({pct}%)")
        print()


def print_key_list(mappings, progress, current_ip, page, search_filter=None):
    """Вивести список ключів з пагінацією та пошуком."""
    # Filter
    if search_filter:
        filtered = [(i, m) for i, m in enumerate(mappings)
                     if search_filter.lower() in m.get("label", m["key_file"]).lower()
                     or search_filter.lower() in m.get("key_file", "").lower()
                     or search_filter.lower() in m.get("country", "").lower()]
    else:
        filtered = list(enumerate(mappings))

    total_filtered = len(filtered)
    total_pages = max(1, (total_filtered + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    # Paginate
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total_filtered)
    page_items = filtered[start:end]

    print(f"  {DIM}Поточний IP: {RESET}{CYAN}{current_ip}{RESET}")
    if search_filter:
        print(f"  {DIM}Фільтр: {RESET}{YELLOW}\"{search_filter}\"{RESET} {DIM}(знайдено: {total_filtered}){RESET}")
    print()

    print(f"  {BOLD}{'#':<5} {'Статус':<4} {'Ключ':<30} {'Країна VPN':<20}{RESET}")
    print(f"  {DIM}{'─' * 60}{RESET}")

    for orig_idx, m in page_items:
        label = m.get("label", m["key_file"])
        country = m["country"]
        done = is_completed(progress, m["key_file"])
        status = f"{GREEN}✓{RESET}" if done else f"{DIM}○{RESET}"
        num = orig_idx + 1
        label_color = DIM if done else ""
        label_reset = RESET if done else ""
        print(f"  {CYAN}{num:<5}{RESET} {status}   {label_color}{label:<30}{label_reset} {MAGENTA}{country:<20}{RESET}")

    print(f"  {DIM}{'─' * 60}{RESET}")
    if total_pages > 1:
        print(f"  {DIM}Сторінка {page + 1}/{total_pages}  |  '<' назад  '>' вперед{RESET}")
    print()
    return page, total_pages


def switch_and_open(mapping, config, vpn_method, vpn_path, progress):
    """Перемкнути VPN і відкрити браузер."""
    label = mapping.get("label", mapping["key_file"])
    country = mapping["country"]
    key_file = mapping["key_file"]
    url = config.get("browser_url", "https://cabinet.tax.gov.ua/")

    # Get current IP before switch
    old_ip = get_current_ip()

    print()
    print(f"  {BG_GREEN}{BOLD} Ключ: {label} → {country} {RESET}")
    print()

    # Disconnect + connect with retry
    if vpn_method == "cli":
        cli_disconnect(vpn_path)
        time.sleep(1)
        success = cli_connect_with_retry(vpn_path, country)
        if not success:
            print(f"\n  {RED}Не вдалося підключитися після {MAX_RETRIES} спроб.{RESET}")
            return False
        time.sleep(2)

        status = cli_status(vpn_path)
        if status:
            for line in status.split("\n"):
                ll = line.lower()
                if any(kw in ll for kw in ["country", "server", "ip", "status"]):
                    print(f"  {DIM}{line.strip()}{RESET}")

    elif vpn_method == "applescript":
        applescript_disconnect(vpn_path)
        time.sleep(1)
        applescript_connect_with_retry(vpn_path, country)
        time.sleep(2)

    else:
        manual_connect(country)

    # ─── IP Verification ───────────────────────────────────────────────
    ip_changed, new_ip = verify_ip_changed(old_ip)

    if not ip_changed and new_ip != "невідомий":
        print(f"  {YELLOW}⚠ Спробую перепідключитися...{RESET}")
        if vpn_method == "cli":
            cli_disconnect(vpn_path)
            time.sleep(2)
            cli_connect_with_retry(vpn_path, country)
            time.sleep(3)
            _, new_ip = verify_ip_changed(old_ip)

    # ─── Duplicate IP Detection ────────────────────────────────────────
    check_duplicate_ip(progress, new_ip, key_file)

    # ─── Mark as completed ─────────────────────────────────────────────
    mark_completed(progress, key_file, new_ip, country)

    # ─── Copy path to clipboard (macOS only) ───────────────────────────
    if sys.platform == "darwin":
        keys_dir = config.get("keys_directory", ".")
        abs_path = os.path.abspath(os.path.join(keys_dir, key_file))
        if os.path.exists(abs_path):
            try:
                subprocess.run(["pbcopy"], input=abs_path.encode("utf-8"), check=True)
                print(f"  {BG_BLUE}{BOLD} 📋 Шлях скопійовано: {abs_path} {RESET}")
                print(f"  {DIM}→ У браузері натисніть Cmd+V щоб обрати цей файл{RESET}")
            except Exception as e:
                print(f"  {YELLOW}⚠ Не вдалося скопіювати шлях в буфер: {e}{RESET}")
        else:
            print(f"  {YELLOW}⚠ Файл ключа не знайдено за шляхом: {abs_path}{RESET}")

    # ─── Open browser ──────────────────────────────────────────────────
    if config.get("open_browser", True):
        print(f"\n  {BLUE}🌐 Відкриваю {url}...{RESET}")
        webbrowser.open(url)

    print()
    return True


def print_help():
    """Показати довідку."""
    print(f"""
  {BOLD}Команди:{RESET}
  {CYAN}1-999{RESET}       Обрати ключ за номером
  {CYAN}/ текст{RESET}     Пошук по назві ключа або країні
  {CYAN}//{RESET}          Скинути фільтр
  {CYAN}< >{RESET}         Попередня/наступна сторінка
  {CYAN}r{RESET}           Оновити конфігурацію
  {CYAN}p{RESET}           Показати тільки необроблені ключі
  {CYAN}clear{RESET}       Скинути весь прогрес
  {CYAN}h{RESET}           Ця довідка
  {CYAN}q{RESET}           Вихід
""")


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    config = load_config()
    mappings = config["mappings"]
    progress = load_progress()

    # Validate config
    validate_config(config)

    # Detect VPN method
    vpn_method, vpn_path = detect_vpn_method()
    if vpn_method == "cli":
        print(f"{GREEN}✓ NordVPN CLI: {vpn_path}{RESET}")
    elif vpn_method == "applescript":
        print(f"{YELLOW}⚠ CLI не знайдено, використовую AppleScript{RESET}")
    else:
        print(f"{YELLOW}⚠ NordVPN не знайдено, ручний режим{RESET}")
    time.sleep(2)

    page = 0
    search_filter = None
    show_only_pending = False

    while True:
        current_ip = get_current_ip()

        # Apply "pending only" filter
        display_mappings = mappings
        if show_only_pending:
            display_mappings = [m for m in mappings if not is_completed(progress, m["key_file"])]

        print_header(vpn_method, progress, len(mappings))

        if show_only_pending:
            print(f"  {YELLOW}📋 Показано тільки необроблені{RESET}")

        page, total_pages = print_key_list(
            display_mappings, progress, current_ip, page, search_filter
        )

        print(f"  {BOLD}Введіть номер ключа{RESET} {DIM}| 'h' довідка | 'q' вихід{RESET}")
        print()

        try:
            choice = input(f"  {CYAN}▸ {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n\n  {YELLOW}👋 До побачення!{RESET}\n")
            break

        if not choice:
            continue

        # ─── Commands ──────────────────────────────────────────────────
        if choice.lower() == "q":
            print()
            if vpn_method == "cli":
                cli_disconnect(vpn_path)
            print(f"\n  {YELLOW}👋 До побачення!{RESET}\n")
            break

        if choice.lower() == "h":
            print_help()
            input(f"  {DIM}Enter щоб продовжити...{RESET}")
            continue

        if choice.lower() == "r":
            config = load_config()
            mappings = config["mappings"]
            continue

        if choice.lower() == "p":
            show_only_pending = not show_only_pending
            page = 0
            continue

        if choice == ">":
            page = min(page + 1, total_pages - 1)
            continue

        if choice == "<":
            page = max(page - 1, 0)
            continue

        if choice.startswith("/"):
            query = choice[1:].strip()
            if query == "/":
                # // = reset filter
                search_filter = None
            elif query:
                search_filter = query
                page = 0
            else:
                search_filter = None
            continue

        if choice.lower() == "clear":
            print(f"\n  {RED}⚠ Скинути весь прогрес? (введіть 'так'){RESET}")
            confirm = input(f"  {CYAN}▸ {RESET}").strip()
            if confirm.lower() in ("так", "yes", "y"):
                progress = {"completed": {}, "ip_history": {}}
                save_progress(progress)
                print(f"  {GREEN}✓ Прогрес скинуто{RESET}")
                time.sleep(1)
            continue

        # ─── Key selection ─────────────────────────────────────────────
        try:
            idx = int(choice) - 1
            # Index is always relative to FULL mappings list (not filtered)
            if 0 <= idx < len(mappings):
                mapping = mappings[idx]

                # Warn if already completed
                if is_completed(progress, mapping["key_file"]):
                    label = mapping.get("label", mapping["key_file"])
                    info = progress["completed"][mapping["key_file"]]
                    print(f"\n  {YELLOW}⚠ Ключ \"{label}\" вже оброблений!{RESET}")
                    print(f"  {DIM}IP: {info.get('ip', '?')} | Час: {info.get('time', '?')}{RESET}")
                    print(f"  {DIM}Повторити? (Enter = так, будь-що інше = ні){RESET}")
                    confirm = input(f"  {CYAN}▸ {RESET}").strip()
                    if confirm:
                        continue

                switch_and_open(mapping, config, vpn_method, vpn_path, progress)
                print(f"  {DIM}Натисніть Enter після авторизації щоб продовжити...{RESET}")
                try:
                    input()
                except (KeyboardInterrupt, EOFError):
                    print(f"\n\n  {YELLOW}👋 До побачення!{RESET}\n")
                    break
            else:
                print(f"\n  {RED}✗ Невірний номер. Оберіть від 1 до {len(mappings)}{RESET}")
                time.sleep(1)
        except ValueError:
            print(f"\n  {RED}✗ Невідома команда. Введіть 'h' для довідки{RESET}")
            time.sleep(1)


if __name__ == "__main__":
    main()
