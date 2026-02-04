# -*- coding: utf-8 -*-
import psycopg2
from psycopg2.extras import RealDictCursor
import math
import time
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- КОНСТАНТЫ МОДЕЛИ ---
# 1. Для ДВС (Модель Кокса)
LAMBDA_0 = 0.000055
COEFFS = {'temp': 6.95, 'rpm': 7.00} # Из файла formula

# 2. Для Рамы (Правило Майнера)
N_NORMAL = 100000.0
N_OVERLOAD = 10000.0

# --- СОСТОЯНИЕ СКРИПТА (чтобы не считать дважды) ---
state = {
    "last_cycle_count": 0,
    "last_process_time": datetime.now()
}

def get_latest_telemetry(cur):
    """Получает последние значения всех нужных датчиков одним запросом"""
    cur.execute("""
        SELECT DISTINCT ON (parameter_name) parameter_name, value, time
        FROM telemetry
        WHERE truck_id = 1
        ORDER BY parameter_name, time DESC;
    """)
    rows = cur.fetchall()
    return {r['parameter_name']: r['value'] for r in rows}

def calculate_packet():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port="5432"
    )
    # RealDictCursor позволяет обращаться к полям по именам, как в словаре
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Анализ данных...")

    try:
        # 1. Забираем свежую телеметрию
        sensors = get_latest_telemetry(cur)
        if not sensors:
            return

        updates_packet = [] # Сюда будем складывать расчеты

        # --- БЛОК 1: РАСЧЕТ ДВС (Модель Кокса - непрерывно) ---
        temp = sensors.get('engine_temp', 85.0)
        # Нормализация (Мин-Макс)
        x_temp = (temp - 15) / (115 - 15)
        exponent = COEFFS['temp'] * x_temp
        failure_risk = LAMBDA_0 * math.exp(exponent)
        
        updates_packet.append({
            "name": "Engine System",
            "prob": min(failure_risk, 1.0),
            "wear": 0.0001 * (2.0 if temp > 95 else 1.0) # Упрощенный износ для примера
        })

        # --- БЛОК 2: РАСЧЕТ РАМЫ (Правило Майнера - по событию) ---
        current_cycle = int(sensors.get('load_cycles', 0))
        print(f"DEBUG: Текущий цикл в базе: {current_cycle}, Последний обработанный: {state['last_cycle_count']}")
        if current_cycle > state["last_cycle_count"]:
            payload = sensors.get('payload', 0.0)
            # Считаем износ по Майнеру: 1/N
            n_limit = N_OVERLOAD if payload > 100.0 else N_NORMAL
            frame_wear = (1.0 / n_limit) * 100.0
            
            

            updates_packet.append({
                "name": "Frame System",
                "prob": 0.01 if payload > 100.0 else 0.001, # Риск растет при перегрузе
                "wear": frame_wear
            })

            print(f"Считаю износ рамы для цикла {current_cycle} = {frame_wear} ")
            state["last_cycle_count"] = current_cycle
            print(f"Detected new cycle: {current_cycle}. Calculating Frame wear...")

        # --- БЛОК 3: ЗАПИСЬ ПАКЕТА В БАЗУ ---
        for item in updates_packet:
            cur.execute("""
                UPDATE component_health 
                SET failure_probability = %s,
                    health_index = health_index - %s,
                    last_update = now()
                WHERE truck_id = 1 AND component_name = %s
            """, (item['prob'], item['wear'], item['name']))
        
        conn.commit()
        print(f"Пакет обновлен: {len(updates_packet)} узлов обработано.")

    except Exception as e:
        print(f"Ошибка аналитики: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    while True:
        calculate_packet()
        time.sleep(30) # Пауза между пакетами