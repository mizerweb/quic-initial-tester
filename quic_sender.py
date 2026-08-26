#!/usr/bin/env python3
"""
QUIC Packet Sender — утилита для отправки заранее подготовленных QUIC-пакетов
(.bin дампов) на заданный домен и проверки, отвечает ли сервер на UDP/443.

Использование: положите .bin файлы в папку QUICs рядом со скриптом и запустите его.
"""

from __future__ import annotations

import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------- #
# Константы
# --------------------------------------------------------------------------- #

QUIC_FOLDER_NAME: Final[str] = "QUICs"
QUIC_PORT: Final[int] = 443
SOCKET_TIMEOUT_SEC: Final[float] = 5.0
MIN_QUIC_PACKET_SIZE: Final[int] = 1200  # RFC 9000, §14.1 — минимальный размер Initial-пакета
RECV_BUFFER_SIZE: Final[int] = 4096
MAX_DOMAIN_LENGTH: Final[int] = 253
MAX_LABEL_LENGTH: Final[int] = 63

# Убирает схему вида "https://", "ftp://" и даже голое "://"
_SCHEME_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*)?://")


class DomainValidationError(ValueError):
    """Некорректно введённый домен."""


class UserInputError(ValueError):
    """Некорректный ввод пользователя (номер файла, формат строки)."""


@dataclass(frozen=True, slots=True)
class SendResult:
    success: bool
    message: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    filename: str
    success: bool
    detail: str


# --------------------------------------------------------------------------- #
# Работа с файлами (чистые функции — легко тестировать)
# --------------------------------------------------------------------------- #

def list_bin_files(folder_path: Path) -> list[str]:
    """Отсортированный список .bin файлов в папке (регистронезависимо по расширению)."""
    return sorted(
        f.name for f in folder_path.iterdir()
        if f.is_file() and f.suffix.lower() == ".bin"
    )


def pad_to_min_size(payload: bytes) -> bytes:
    """Дополняет payload нулями до MIN_QUIC_PACKET_SIZE байт (RFC 9000, §14.1)."""
    if len(payload) >= MIN_QUIC_PACKET_SIZE:
        return payload
    return payload.ljust(MIN_QUIC_PACKET_SIZE, b"\x00")


# --------------------------------------------------------------------------- #
# Валидация ввода
# --------------------------------------------------------------------------- #

def sanitize_domain(raw_domain: str) -> str:
    """
    Убирает схему, путь и порт, возвращает «голый» домен.
    Бросает DomainValidationError при пустом или слишком длинном домене.
    """
    domain = _SCHEME_PREFIX_RE.sub("", raw_domain.strip())
    domain = domain.split("/", 1)[0].split(":", 1)[0].strip()

    if not domain:
        raise DomainValidationError("Вы не указали домен!")

    if len(domain) > MAX_DOMAIN_LENGTH or any(
        len(label) > MAX_LABEL_LENGTH for label in domain.split(".")
    ):
        raise DomainValidationError(
            f"Введён слишком длинный домен (макс. {MAX_DOMAIN_LENGTH} символов)."
        )

    return domain


def parse_choice(raw_input: str, files_count: int) -> tuple[int, str] | tuple[None, str]:
    """
    Разбирает ввод пользователя:
      "<номер> <домен>" -> (индекс файла с 0, домен) — проверка одного файла;
      "A <домен>"       -> (None, домен)              — проверка ВСЕХ файлов на домен.
    """
    parts = raw_input.split()
    if len(parts) != 2:
        raise UserInputError("Введите номер (или 'A') и домен через пробел.")

    selector, raw_domain = parts

    if selector.lower() == "a":
        return None, sanitize_domain(raw_domain)

    try:
        file_num = int(selector)
    except ValueError:
        # isdigit() пропускает не только ASCII-цифры (например, юникодные
        # надстрочные символы), на которых int() падает — поэтому проверяем
        # реальным преобразованием, а не .isdigit().
        raise UserInputError("Первым аргументом должен быть номер файла или 'A'.") from None

    if not (1 <= file_num <= files_count):
        raise UserInputError(f"Файла под номером {file_num} нет.")

    return file_num - 1, sanitize_domain(raw_domain)


# --------------------------------------------------------------------------- #
# Сеть
# --------------------------------------------------------------------------- #

def _send_over_udp(payload: bytes, ip: str) -> SendResult:
    """
    Отправляет UDP-пакет на уже резолвленный IP:443 и ждёт ответа именно от него.

    Важно: используется единый дедлайн на весь цикл ожидания, а не таймаут
    на каждый recvfrom() в отдельности — иначе поток "чужих" пакетов (например,
    от посторонних узлов) мог бы удерживать сокет открытым дольше SOCKET_TIMEOUT_SEC.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        deadline = time.monotonic() + SOCKET_TIMEOUT_SEC
        try:
            sock.sendto(payload, (ip, QUIC_PORT))

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise socket.timeout

                sock.settimeout(remaining)
                data, addr = sock.recvfrom(RECV_BUFFER_SIZE)
                if addr[0] == ip:
                    return SendResult(
                        True, f"Получено {len(data)} байт от {addr[0]}."
                    )
                # Ответ пришёл не от целевого IP — игнорируем и ждём остаток времени

        except socket.timeout:
            return SendResult(
                False,
                "Таймаут. Пакет отброшен, заблокирован, либо сервер не поддерживает QUIC.",
            )
        except OSError as e:
            return SendResult(False, f"Сетевая ошибка: {e}")


def send_quic_packet(payload: bytes, domain: str) -> SendResult:
    """Резолвит domain и отправляет один UDP-пакет на domain:443 (для одиночной проверки)."""
    try:
        ip = socket.gethostbyname(domain)
    except socket.gaierror:
        return SendResult(False, f"Не удалось определить IP для '{domain}'.")

    print(f"📍 IP-адрес: {ip}")
    return _send_over_udp(payload, ip)


def probe_all_files(folder_path: Path, files: list[str], domain: str) -> list[ProbeResult]:
    """
    Прогоняет КАЖДЫЙ .bin файл против одного домена и возвращает список результатов.
    IP резолвится один раз и переиспользуется для всех файлов — так и быстрее
    (нет лишних DNS-запросов на каждый файл), и вывод не дублируется.
    Ctrl+C прерывает проверку, но уже накопленные результаты не теряются.
    """
    results: list[ProbeResult] = []

    try:
        ip = socket.gethostbyname(domain)
    except socket.gaierror:
        print(f"\n❌ Не удалось определить IP для '{domain}'. Проверка отменена.")
        return results

    print(f"📍 IP-адрес: {ip}")
    print(f"🚀 Проверка {len(files)} файлов на домене {domain} (порт {QUIC_PORT})...\n")

    try:
        for i, filename in enumerate(files, 1):
            file_path = folder_path / filename
            try:
                payload = pad_to_min_size(file_path.read_bytes())
            except OSError as e:
                results.append(ProbeResult(filename, False, f"Ошибка чтения: {e}"))
                print(f" [{i}/{len(files)}] {filename}: ❌ ошибка чтения")
                continue

            result = _send_over_udp(payload, ip)
            results.append(ProbeResult(filename, result.success, result.message))
            mark = "✅" if result.success else "❌"
            print(f" [{i}/{len(files)}] {filename}: {mark} {result.message}")

            # Небольшая пауза между попытками — не спамим целевой домен/локальный роутер подряд
            if i < len(files):
                time.sleep(0.3)
    except KeyboardInterrupt:
        print(f"\n⏹ Проверка прервана — успели проверить {len(results)}/{len(files)}.")

    return results


def print_probe_report(domain: str, results: list[ProbeResult]) -> None:
    working = [r.filename for r in results if r.success]

    print("\n" + "=" * 55)
    print(f" ИТОГ проверки для {domain}: {len(working)}/{len(results)} рабочих")
    print("=" * 55)
    for r in results:
        mark = "✅" if r.success else "❌"
        print(f" {mark} {r.filename}")

    if working:
        print("\nРабочие фейки:")
        for name in working:
            print(f"  - {name}")
    else:
        print("\nНи один фейк не прошёл — возможно, домен блокируется иначе или недоступен.")


# --------------------------------------------------------------------------- #
# UI / интерактивный цикл
# --------------------------------------------------------------------------- #

def print_menu(files: list[str]) -> None:
    print("\n" + "—" * 28)
    print(" Доступные QUIC файлы (.bin):")
    for i, file_name in enumerate(files, 1):
        print(f" [{i}] {file_name}")
    print("—" * 28)
    print("\n" + "=" * 55)
    print(" СИНТАКСИС: <номер_файла> <домен>   — проверить один файл")
    print("            A <домен>              — проверить ВСЕ файлы")
    print(" ПРИМЕРЫ:   1 youtube.com")
    print("            A tracker.gg")
    print(" ОБНОВЛЕНИЕ: Введите 'U' для обновления списка")
    print("=" * 55 + "\n")


def prompt_file_and_domain(files: list[str]) -> tuple[int, str] | tuple[None, str] | None:
    """
    Возвращает:
      (индекс, домен) — проверить один файл;
      (None, домен)    — проверить все файлы;
      None             — просто обновить список (команда 'U').
    """
    print_menu(files)
    raw = input("👉 Введите номер/'A' и домен (или 'U'): ").strip()

    if raw.lower() == "u":
        print("\n🔄 Обновление списка...")
        return None

    return parse_choice(raw, len(files))


def handle_no_files() -> bool:
    """Возвращает True, если нужно продолжить цикл (обновить список), False — выйти."""
    print("\n❌ В папке 'QUICs' нет файлов .bin.")
    choice = input("👉 Закиньте .bin файлы и введите 'U' для обновления (или 'N' для выхода): ")
    return choice.strip().lower() == "u"


def send_selected_file(folder_path: Path, files: list[str], file_index: int, domain: str) -> None:
    file_path = folder_path / files[file_index]

    try:
        payload = file_path.read_bytes()
    except OSError as e:
        print(f"\n❌ Ошибка чтения файла: {e}")
        return

    original_len = len(payload)
    payload = pad_to_min_size(payload)
    if len(payload) != original_len:
        print(f"\nℹ️ Пакет был {original_len} байт. Дополнен нулями до {MIN_QUIC_PACKET_SIZE} байт (RFC 9000).")

    print(f"🚀 Отправка QUIC-пакета на домен: {domain} (порт {QUIC_PORT})...")
    result = send_quic_packet(payload, domain)

    print("\n" + "*" * 40)
    print(("[УСПЕХ] " if result.success else "[ОШИБКА] ") + result.message)
    print("*" * 40)


def run_interactive_loop(folder_path: Path) -> None:
    while True:
        files = list_bin_files(folder_path)

        if not files:
            if handle_no_files():
                continue
            break

        try:
            choice = prompt_file_and_domain(files)
        except (UserInputError, DomainValidationError) as e:
            print(f"\n❌ ОШИБКА: {e}")
            continue
        except KeyboardInterrupt:
            print("\nВыход.")
            break

        if choice is None:
            continue

        file_index, domain = choice
        if file_index is None:
            results = probe_all_files(folder_path, files, domain)
            if results:
                print_probe_report(domain, results)
        else:
            send_selected_file(folder_path, files, file_index, domain)

        try:
            again = input("\n" + "-" * 40 + "\nПродолжить? (y - да / n - выходить): ").strip().lower()
            if again == "n":
                break
        except KeyboardInterrupt:
            break


# --------------------------------------------------------------------------- #
# Точка входа
# --------------------------------------------------------------------------- #

def main() -> None:
    script_dir = Path(__file__).resolve().parent
    folder_path = script_dir / QUIC_FOLDER_NAME

    if not folder_path.exists():
        print(f"Папка '{QUIC_FOLDER_NAME}' не найдена по пути: {folder_path}\nСоздаю её...")
        folder_path.mkdir(parents=True, exist_ok=True)
        print("Пожалуйста, положите туда .bin дампы и запустите скрипт снова.")
        return

    run_interactive_loop(folder_path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nВыход.")
