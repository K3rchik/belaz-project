# -*- coding: utf-8 -*-
import psycopg2
from psycopg2.extras import RealDictCursor
import math
import time
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- КОНСТАНТЫ ИЗ НАУЧНЫХ СТАТЕЙ ---
# Статья Маслюкова, стр. 93
THRESHOLDS_SFC = {
    "GENTLE": 200,          # Щадящий (г/кВт*ч или г/ткм)
    "ACTIVE": 245,          # Активно-форсированный
    "REACTIVE": 290,        # Реактивно-форсированный
    "AGGRESSIVE": 999       # Агрессивный
}

# Коэффициенты ускорения износа для режимов
WEAR_MULTIPLIERS = {
    "GENTLE": 1.0,
    "ACTIVE": 1.4,
    "REACTIVE": 3.0,
    "AGGRESSIVE": 18.0     # ! Самое важное: в 18 раз быстрее
}

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
        host=os.getenv("DB_HOST"), database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD")
    )
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    print(f"\n--- АНАЛИЗ [{datetime.now().strftime('%H:%M:%S')}] ---")

    try:
        data = get_latest_telemetry(cur)
        if not data: 
            print("Нет данных телеметрии!")
            return

        # === ДАННЫЕ ===
        fuel_rate = data.get('fuel_rate', 25.0)
        speed = data.get('speed', 0.0)
        payload_val = data.get('payload', 0.0) # Это значение из базы (в тоннах, например 90.0)
        iron_ppm = data.get('oil_iron', 15.0)
        
        # ! ИСПРАВЛЕНИЕ: Приводим к кг для расчетов !
        # Если в базе < 500, считаем что это тонны и переводим в кг
        if payload_val < 500:
            payload_kg = payload_val * 1000.0
            payload_tons = payload_val
        else:
            payload_kg = payload_val
            payload_tons = payload_val / 1000.0

        # =========================================================
        # 1. ДВИГАТЕЛЬ (ENGINE)
        # =========================================================
        if speed > 5 and payload_tons > 0:
            transport_work = payload_tons * speed
            sfc = (fuel_rate * 850) / transport_work
        else:
            sfc = 100.0 

        if sfc <= THRESHOLDS_SFC["GENTLE"]: mode = "GENTLE"
        elif sfc <= THRESHOLDS_SFC["ACTIVE"]: mode = "ACTIVE"
        elif sfc <= THRESHOLDS_SFC["REACTIVE"]: mode = "REACTIVE"
        else: mode = "AGGRESSIVE"

        CRITICAL_IRON = 60.0
        prob_engine = min(1.0, (iron_ppm / CRITICAL_IRON)**2)
        engine_health = max(0.0, 100.0 - (prob_engine * 100.0))

        # Обновление ДВС
        cur.execute("""
            UPDATE component_health 
            SET failure_probability = %s, health_index = %s, last_update = NOW()
            WHERE truck_id = 1 AND component_name = 'Engine System'
            RETURNING id
        """, (prob_engine, engine_health))
        
        if cur.rowcount == 0:
            cur.execute("""
                INSERT INTO component_health (truck_id, component_name, failure_probability, health_index, last_update)
                VALUES (1, 'Engine System', %s, %s, NOW())
            """, (prob_engine, engine_health))

        # История ДВС
        cur.execute("""
            INSERT INTO component_health_history 
            (truck_id, component_name, health_index, failure_probability, last_update)
            VALUES (1, 'Engine System', %s, %s, NOW())
        """, (engine_health, prob_engine))

        print(f"ДВС: Режим {mode} | Fe {iron_ppm:.1f} | Здоровье {engine_health:.2f}%")

        # =========================================================
        # 2. РАМА (FRAME SYSTEM) - ИСПРАВЛЕНО
        # =========================================================
        frame_damage = 0.0
        
        # Проверяем условия (теперь используем payload_kg)
        # 130 тонн = 130000 кг
        if payload_kg > 130000:
            frame_damage = 0.5 
            print(f"!!! ПЕРЕГРУЗ РАМЫ: {payload_kg:.0f} кг !!!")
        elif speed > 20 and payload_kg > 100000:
            frame_damage = 0.05 
            print(f"!!! ДИНАМИЧЕСКИЙ УДАР: {speed:.0f} км/ч с грузом {payload_kg:.0f} кг !!!")
        
        # 1. Пытаемся обновить и получить текущее здоровье
        cur.execute("""
            UPDATE component_health 
            SET health_index = GREATEST(0, health_index - %s), last_update = NOW()
            WHERE truck_id = 1 AND component_name = 'Frame System'
            RETURNING health_index
        """, (frame_damage,))
        
        row = cur.fetchone()
        
        # 2. Если записи не было - создаем
        if row is None:
            current_frame_health = 100.0
            cur.execute("""
                INSERT INTO component_health (truck_id, component_name, failure_probability, health_index, last_update)
                VALUES (1, 'Frame System', 0.0, 100.0, NOW())
            """)
            print("Рама: Запись создана (была пустая)")
        else:
            current_frame_health = row['health_index']
            # print(f"Рама: Обновлена. Здоровье: {current_frame_health:.4f}%")

        # 3. Пишем историю Рамы
        frame_prob = 1.0 - (current_frame_health / 100.0)
        
        cur.execute("""
            INSERT INTO component_health_history 
            (truck_id, component_name, health_index, failure_probability, last_update)
            VALUES (1, 'Frame System', %s, %s, NOW())
        """, (current_frame_health, frame_prob))

        conn.commit()

    except Exception as e:
        print(f"Ошибка аналитики: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    while True:
        calculate_packet()
        time.sleep(5) # Аналитика работает раз в 5 секунд