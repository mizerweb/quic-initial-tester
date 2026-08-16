import os
import socket
import re

def main():
    # Ищем папку QUICs строго там, где лежит сам файл скрипта
    script_dir = os.path.dirname(os.path.abspath(__file__))
    folder_path = os.path.join(script_dir, 'QUICs')
    
    if not os.path.exists(folder_path):
        print(f"Папка 'QUICs' не найдена по пути: {folder_path}\nСоздаю её...")
        os.makedirs(folder_path)
        print("Пожалуйста, положите туда .bin дампы и запустите скрипт снова.")
        return

    while True:
        # Фильтруем файлы строго по расширению .bin
        files = [f for f in os.listdir(folder_path) if f.endswith('.bin') and os.path.isfile(os.path.join(folder_path, f))]
        
        if not files:
            print(f"\n❌ В папке 'QUICs' нет файлов .bin.")
            choice = input("👉 Закиньте .bin файлы и введите 'U' для обновления (или 'N' для выхода): ").strip().lower()
            if choice == 'u':
                continue
            else:
                break

        print("\n" + "—"*28)
        print(" Доступные QUIC файлы (.bin):")
        for i, file_name in enumerate(files, 1):
            print(f" [{i}] {file_name}")
        print("—"*28)

        print("\n" + "="*55)
        print(" СИНТАКСИС: <номер_файла> <домен>")
        print(" ПРИМЕР:    1 youtube.com")
        print(" ОБНОВЛЕНИЕ: Введите 'U' для обновления списка")
        print("="*55 + "\n")

        try:
            user_input_raw = input("👉 Введите номер и домен (или 'U'): ").strip()
            
            if user_input_raw.lower() == 'u':
                print("\n🔄 Обновление списка...")
                continue
                
            user_input = user_input_raw.split()
            if len(user_input) != 2:
                print("\n❌ ОШИБКА: Введите номер и домен через пробел.")
                continue
                
            file_num_str, domain = user_input
            
            # 1. Очистка домена
            domain = re.sub(r'^(https?://|http://|://)', '', domain)
            domain = domain.split('/')[0].split(':')[0].strip()
            
            # Проверка на пустой домен (если ввели просто https://)
            if not domain:
                print("\n❌ ОШИБКА: Вы не указали домен!")
                continue

            # 2. Проверка длины DNS
            if len(domain) > 253 or any(len(label) > 63 for label in domain.split('.')):
                print("\n❌ [ОШИБКА] Введен слишком длинный домен (макс. 253 символа).")
                continue
                
            file_num = int(file_num_str)
            if file_num < 1 or file_num > len(files):
                print(f"\n❌ ОШИБКА: Файла под номером {file_num} нет.")
                continue
                
        except ValueError:
            print("\n❌ ОШИБКА: Номер файла должен быть цифрой.")
            continue
        except KeyboardInterrupt:
            print("\nВыход.")
            break

        selected_file = files[file_num - 1]
        file_path = os.path.join(folder_path, selected_file)

        try:
            with open(file_path, 'rb') as f:
                payload = f.read()
        except Exception as e:
            print(f"\n❌ Ошибка чтения файла: {e}")
            continue

        # 3. QUIC RFC 9000 Padding: Дополняем пакет до 1200 байт, если он меньше
        if len(payload) < 1200:
            original_len = len(payload)
            payload = payload + b'\x00' * (1200 - original_len)
            print(f"\nℹ️ Пакетов был {original_len} байт. Дополнен нулями до 1200 байт (по стандарту QUIC RFC 9000).")

        print(f"🚀 Отправка QUIC-пакета на домен: {domain} (порт 443)...")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)

        try:
            ip = socket.gethostbyname(domain)
            print(f"📍 IP-адрес: {ip}")

            sock.sendto(payload, (ip, 443))

            # 4. Проверяем, что ответ пришел именно от целевого IP
            while True:
                data, addr = sock.recvfrom(4096)
                if addr[0] == ip:
                    print("\n" + "*"*40)
                    print("[УСПЕХ] Сайт ответил на QUIC-запрос!")
                    print(f"Получено: {len(data)} байт от {addr[0]}")
                    print("*"*40)
                    break

        except socket.timeout:
            print("\n" + "*"*40)
            print("[ОШИБКА] Таймаут.")
            print("Пакет отброшен, заблокирован или сервер не поддерживает QUIC.")
            print("*"*40)
        except socket.gaierror:
            print(f"\n❌ [ОШИБКА] Не удалось определить IP для '{domain}'.")
        except Exception as e:
            print(f"\n❌ [ОШИБКА]: {e}")
        finally:
            sock.close()

        try:
            print("\n" + "-"*40)
            choice = input("Продолжить? (y - да / n - выходить): ").strip().lower()
            if choice == 'n':
                break
        except KeyboardInterrupt:
            break

if __name__ == "__main__":
    main()
