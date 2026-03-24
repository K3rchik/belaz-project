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

# 3. Для КГШ 
ALPHA_TIRE = 1.0e-7  # Износостойкость (стр. 61)
SIGMA_TIRE = 30.0     # Теплоотдача (стр. 60)
A_PO_TIRE = 15.0      # Площадь шины 33.00R51
OTD_MAX = 78.5 # Начальный протектор

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

        # =========================================================
        # 3. КГШ
        # =========================================================
        # --- ВВОД ИСХОДНЫХ ДАННЫХ ---
        speed = data.get('speed', 0.0)
        payload_kg = data.get('payload', 0.0) * 1000.0 # Перевод в кг
        incline = data.get('incline', 0.0)
        radius = data.get('turn_radius', 9999.0)
        p_bar = data.get('wheel_press_rf', 610000) / 100000.0
        t_sh = data.get('wheel_temp_avg', 40.0)
        
        v_ms = speed / 3.6
        g = 9.81
        mass_empty = 107100
        
        # 1. РОМБ: Автосамосвал загружен? (Определение массы)
        # В блок-схеме это влияет на распределение нагрузок
        mass_total = mass_empty + payload_kg
        
        # Расчет нормальной реакции Rz (база для всех сил)
        # Горюнов указывает, что нагрузка распределяется по осям. 
        # Для 75131 груженого ~67% веса на заднюю ось (4 колеса)
        rz_one_wheel = (mass_total * g * math.cos(math.radians(incline)) * 0.67) / 4.0

        # 2. РОМБ: Движение на подъем (i >= 0) или спуск (i < 0)?
        # Здесь выбираются формулы 2.31 или 2.32
        
        # Сначала считаем f (сопротивление качению) по ур. 2.24
        f = 0.001 * ((20.2 / (0.64 * p_bar)) + (speed**3.7 / (778 * p_bar**2.03)))
        
        if incline >= 0:
            # Определение Rx при подъеме (ур. 2.31 / 2.33)
            # Сила тяги должна преодолеть и качение, и уклон
            rx = rz_one_wheel * f + (mass_total / 4.0) * g * math.sin(math.radians(incline))
        else:
            # Определение Rx при спуске (ур. 2.32)
            # Здесь сила может быть тормозной
            rx = rz_one_wheel * f - (mass_total / 4.0) * g * math.sin(math.radians(abs(incline)))

        # 3. РОМБ: Движение на повороте? (R < 1000)
        # Определение Ry (ур. 2.35 / 2.36)
        if radius < 1000:
            ry = (rz_one_wheel * (v_ms**2)) / (g * radius)
        else:
            ry = 0.0

        # --- ОПРЕДЕЛЕНИЕ ИЗНОСА НА УЧАСТКЕ (ур. 2.27) ---
        # Теперь Rx и Ry вычислены корректно согласно состоянию БЕЛАЗа
        s_step = v_ms * 2.0 # Путь за интервал 2 сек
        
        # Расчет мощностных составляющих (ур. 2.27)
        if v_ms > 0.1:
             # Общая мощность потерь в шине (N_п)
            total_power_loss = (f * math.sqrt(rx**2 + ry**2)) / (1 - f)
            
            # Согласно стр. 52 диссертации, на трение (износ) идет 
            # в среднем 10% (0.1) от общей мощности потерь.
            # Остальные 90% уходят в тепло (гистерезис).
            friction_power = total_power_loss * 0.10
            
            # Теперь считаем износ только от мощности трения
            # Формула 2.21: I = alpha * A (где A - работа трения)
            # Работа трения = Мощность трения * Время (или Сила * Путь)
            wear_mm = ALPHA_TIRE * friction_power * s_step
        else:
            wear_mm = 0.0

        # Обновление здоровья в БД
        health_loss = (wear_mm / OTD_MAX) * 100.0
        
        # Обновляем текущее состояние
        cur.execute("""
            UPDATE component_health 
            SET health_index = GREATEST(0, health_index - %s), 
                failure_probability = %s,
                last_update = NOW()
            WHERE truck_id = 1 AND component_name = 'Tire System'
            RETURNING health_index
        """, (health_loss, 1.0 if t_sh > 120 else 0.0))
        
        # Если записи не было - создаем (первичная инициализация)
        if cur.rowcount == 0:
            cur.execute("""
                INSERT INTO component_health (truck_id, component_name, failure_probability, health_index, last_update)
                VALUES (1, 'Tire System', 0.0, 100.0, NOW())
            """)
            current_tire_health = 100.0
        else:
            current_tire_health = cur.fetchone()['health_index']

        # 7. Запись в историю (для графиков на Web-сервере)
        cur.execute("""
            INSERT INTO component_health_history 
            (truck_id, component_name, health_index, failure_probability, last_update)
            VALUES (1, 'Tire System', %s, %s, NOW())
        """, (current_tire_health, 1.0 if t_sh > 120 else 0.0))

        print(f"ШИНЫ: Износ {wear_mm:.10f} мм | Здоровье {current_tire_health:.2f}% | T {t_sh:.1f}°C")
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