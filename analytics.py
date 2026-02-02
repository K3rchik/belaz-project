# -*- coding: utf-8 -*-
import psycopg2
import math
import os
from dotenv import load_dotenv

load_dotenv()

def calculate_reliability():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    cur = conn.cursor()

    # 1. Получаем коэффициенты из базы
    cur.execute("SELECT parameter_name, coefficient FROM model_coefficients")
    coeffs = dict(cur.fetchall())

    # 2. Получаем последние данные датчиков
    # (Для примера берем последние значения, в идеале - средние за минуту)
    cur.execute("""
        SELECT parameter_name, value FROM telemetry 
        WHERE time > now() - interval '1 minute'
    """)
    sensors = dict(cur.fetchall())

    if sensors:
        # 3. Нормализация (Метод Мин-Макс из файла Тимура)
        # x_norm = (x - min) / (max - min)
        # Здесь используем упрощенные границы из таблицы норм Виктории
        x1 = (sensors.get('engine_temp', 90) - 80) / (115 - 80)
        x2 = (sensors.get('oil_pressure', 400) - 170) / (550 - 170)
        x4 = (sensors.get('rpm', 1000) - 600) / (2100 - 600)
        
        # 4. Расчет по формуле: λ = λ0 * exp(a1x1 + a2x2 + ...)
        # λ0 (базовый риск) возьмем из файла = 0.000055
        lambda_0 = 0.000055
        exponent = (coeffs['engine_temp'] * x1) + (coeffs['oil_pressure'] * x2) + (coeffs['rpm'] * x4)
        
        failure_rate = lambda_0 * math.exp(exponent)

        cur.execute("""
            UPDATE component_health 
            SET failure_probability = %s, 
                last_update = now()
            WHERE component_name = 'Engine System'
        """, (min(failure_rate, 1.0),))
        
        # ДОБАВЬ ЭТУ СТРОКУ ДЛЯ ПРОВЕРКИ:
        print(f"DEBUG: Попытка обновить 'Engine System'. Результат: {cur.rowcount} строк изменено.")
        
        conn.commit()
        
        # 5. Обновляем вероятность отказа в базе
        cur.execute("""
            UPDATE component_health 
            SET failure_probability = %s, 
                last_update = now()
            WHERE component_name = 'Engine System'
        """, (min(failure_rate, 1.0),)) # Вероятность не выше 100%
        
        conn.commit()
        print(f"Расчет окончен. Текущий риск отказа: {failure_rate:.6f}")

    cur.close()
    conn.close()

if __name__ == "__main__":
    print("Smart Analytics Engine started...")
    while True:
        try:
            calculate_reliability()
        except Exception as e:
            print(f"Ошибка в цикле: {e}")
        
        import time
        time.sleep(30) # Считать риск каждые 30 секунд