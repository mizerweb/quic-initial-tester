import os
import socket

def main():
    folder_name = 'QUICs'
    
    # 1. Проверяем наличие папки QUICs
    if not os.path.exists(folder_name):
        print(f"Папка '{folder_name}' не найдена. Создаю её для вас...")
        os.makedirs(folder_name)
        print(f"Пожалуйста, положите ваши файлы .bin в папку '{folder_name}' и запустите скрипт снова.")
        return

    # 2. Получаем список файлов
    files = [f for f in os.listdir(folder_name) if os.path.isfile(os.path.join(folder_name, f))]
    
    if not files:
        print(f"В папке '{folder_name}' пока нет файлов. Поместите туда quic_initial.bin.")
        return

    # 3. Выводим список файлов с номерами
    print("\n--- Доступные QUIC файлы ---")
    for i, file_name in enumerate(files, 1):
        print(f"[{i}] {file_name}")
    print("----------------------------")

    # 4. Подробная инструкция по синтаксису для пользователя
    print("\n" + "="*55)
    print(" ИНСТРУКЦИЯ ПО ВВОДУ:")
    print(" Введите номер файла из списка выше и домен сайта.")
    print(" Значения нужно написать в одну строку через ПРОБЕЛ.")
    print("")
    print(" СИНТАКСИС: <номер_файла> <домен>")
    print("")
    print(" ПРАВИЛЬНЫЕ ПРИМЕРЫ:")
    print("   1 youtube.com")
    print("   2 google.com")
    print("")
    print(" ВАЖНО: Вводите только цифру (без скобок) и домен (без https://).")
    print("="*55 + "\n")

    # 5. Обработка ввода
    try:
        user_input_raw = input("👉 Введите номер и домен: ").strip()
        user_input = user_input_raw.split()
        
        if len(user_input) != 2:
            print("\n❌ ОШИБКА: Неверный формат ввода!")
            print("Вы ввели:", f"'{user_input_raw}'")
            print("Нужно ввести ровно два значения через пробел. Пример: 1 youtube.com")
            return
            
        file_num_str, domain = user_input
        
        # Очистка домена, если пользователь случайно ввел https:// или http://
        if domain.startswith("http://"):
            domain = domain.replace("http://", "")
        if domain.startswith("https://"):
            domain = domain.replace("https://", "")
        # Убираем слэш на конце, если есть (например, youtube.com/)
        domain = domain.rstrip("/")
            
        file_num = int(file_num_str)
        
        if file_num < 1 or file_num > len(files):
            print(f"\n❌ ОШИБКА: Файла с номером {file_num} не существует. Выберите номер от 1 до {len(files)}.")
            return
            
    except ValueError:
        print("\n❌ ОШИБКА: Первым значением должна быть цифра (номер файла).")
        return
    except KeyboardInterrupt:
        print("\nВыход.")
        return

    selected_file = files[file_num - 1]
    file_path = os.path.join(folder_name, selected_file)

    # 6. Читаем бинарный файл
    try:
        with open(file_path, 'rb') as f:
            payload = f.read()
    except Exception as e:
        print(f"\n❌ Ошибка при чтении файла {selected_file}: {e}")
        return

    print(f"\n✅ Файл выбран: {selected_file} ({len(payload)} байт)")
    print(f"🚀 Отправка QUIC-пакета на домен: {domain} (порт 443)...")

    # 7. Создаем UDP сокет и отправляем данные
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)  # Таймаут ожидания ответа - 5 секунд

    try:
        # Узнаем IP-адрес домена
        ip = socket.gethostbyname(domain)
        print(f"📍 IP-адрес домена: {ip}")

        # Отправляем payload (стандартный порт для QUIC/HTTP3 - 443)
        sock.sendto(payload, (ip, 443))

        # Ждем ответ
        data, addr = sock.recvfrom(4096)
        
        print("\n" + "*"*40)
        print("[УСПЕХ] Сайт ответил на QUIC-запрос!")
        print(f"Статус: Сервер активен.")
        print(f"Получен ответ: {len(data)} байт от узла {addr[0]}")
        print("*"*40)

    except socket.timeout:
        print("\n" + "*"*40)
        print("[ОШИБКА] Таймаут.")
        print("Сайт не загрузился по QUIC (пакет отброшен, заблокирован или сервер не поддерживает HTTP/3).")
        print("*"*40)
    except socket.gaierror:
        print(f"\n❌ [ОШИБКА] Не удалось найти IP для домена '{domain}'. Проверьте правильность написания.")
    except Exception as e:
        print(f"\n❌ [ОШИБКА] Непредвиденная ошибка: {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    main()