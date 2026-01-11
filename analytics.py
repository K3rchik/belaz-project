import psycopg2
import time
from datetime import datetime

DB_CONFIG = {
    "host": "localhost",
    "database": "belaz_db",
    "user": "admin",
    "password": "K3rchikk",
    "port": "5432"
}

# Константы надежности
TOTAL_RESOURCE_HOURS = 20000 
# Сколько % ресурса потребляется за 1 секунду в идеальных условиях
BASE_WEAR_PER_SEC = (100.0 / (TOTAL_RESOURCE_HOURS * 3600))

def get_wear_coefficient(temp):
    if temp is None: return 1.0
    if temp > 102: return 10.0  # Критический износ
    if temp > 95:  return 2.0   # Ускоренный износ
    return 1.0                  # Норма

def run_analytics():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print("Analytical Module (Reliability) started...")

        while True:
            # 1. Считаем среднюю температуру за последние 10 минут
            cur.execute("""
                SELECT AVG(value) FROM telemetry 
                WHERE parameter_name = 'engine_temp' 
                AND time > now() - interval '10 minutes';
            """)
            avg_temp = cur.fetchone()[0]

            if avg_temp:
                # 2. Получаем коэффициент износа
                k_factor = get_wear_coefficient(avg_temp)
                
                # 3. Рассчитываем, сколько % ресурса "съедено" за этот цикл (например, за 60 сек)
                # Износ = Базовый_износ * Время * Коэффициент
                actual_wear = BASE_WEAR_PER_SEC * 60 * k_factor

                # 4. Обновляем таблицу здоровья
                cur.execute("""
                    UPDATE component_health 
                    SET health_index = health_index - %s, 
                        last_update = now()
                    WHERE truck_id = 1 AND component_name = 'Engine System';
                """, (actual_wear,))
                
                conn.commit()
                print(f"[{datetime.now().strftime('%H:%M')}] Avg Temp: {avg_temp:.1f}C | K: {k_factor} | Wear Applied: {actual_wear:.6f}%")
            else:
                print("No new telemetry data found...")

            time.sleep(60) # Расчет каждую минуту

    except Exception as e:
        print(f"Analytics Error: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    run_analytics()
