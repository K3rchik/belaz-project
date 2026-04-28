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
ALPHA_TIRE = 1.0e-4  # Износостойкость (стр. 61)
SIGMA_TIRE = 30.0     # Теплоотдача (стр. 60)
A_PO_TIRE = 15.0      # Площадь шины 33.00R51
OTD_MAX = 78.5 # Начальный протектор
MASS_EMPTY = 107100.0
MAX_PAYLOAD = 130000.0  # Для диагональных шин
LA = 5.3                # Колесная база
# Расстояния до центра масс (вычисляем из развесовки 50.9 / 49.1)
# b = LA * 0.509 = 2.697м (от задней оси)
# a = LA * 0.491 = 2.602м (от передней оси)
B_EMPTY = 2.697 
A_EMPTY = 2.602

# Высота центра масс (h)
H_EMPTY = 2.1
H_LOADED = 2.5

def calculate_wheel_wear(wheel_pos, speed_kmh, payload_kg, incline_deg, radius_m, p_bar, t_sh, dt=2):
            if speed_kmh < 0.5: return 0.0

            v_ms = speed_kmh / 3.6
            alpha_rad = math.radians(incline_deg)
            load_factor = min(1.0, payload_kg / MAX_PAYLOAD) # 0.0 (пустой) -> 1.0 (полный)

            # 1. ДИНАМИЧЕСКАЯ РАЗВЕСОВКА (Интерполяция данных со скриншота)
            # Передняя ось: 50.9% -> 33.0%
            # Задняя ось: 49.1% -> 67.0%
            front_ratio = 0.509 - (0.509 - 0.330) * load_factor
            rear_ratio = 0.491 + (0.670 - 0.491) * load_factor

            # Текущая высота центра масс
            h_curr = H_EMPTY + (H_LOADED - H_EMPTY) * load_factor

            total_mass = MASS_EMPTY + payload_kg
            g = 9.81

            # 2. РАСЧЕТ НОРМАЛЬНОЙ РЕАКЦИИ (Rz) с учетом переноса веса на уклоне
            # Используем формулы 2.29 и 2.30 из диссертации
            if "front" in wheel_pos:
                n = 2
                # Для передней оси: используем плечо b (расстояние от задней оси)
                # В пустом b = 2.697. В груженом b смещается. 
                # Но проще использовать долю веса (ratio) и корректировать на уклон:
                rz = (total_mass * g * (front_ratio * math.cos(alpha_rad) - (h_curr/LA) * math.sin(alpha_rad))) / n
            else:
                n = 4
                # Для задней оси: используем плечо a и прибавляем смещение веса (+)
                rz = (total_mass * g * (rear_ratio * math.cos(alpha_rad) + (h_curr/LA) * math.sin(alpha_rad))) / n

            # 3. СОПРОТИВЛЕНИЕ КАЧЕНИЮ (f)
            f = 0.001 * ((20.2 / (0.64 * p_bar)) + (speed_kmh**3.7 / (778 * p_bar**2.03)))

            # 4. КАСАТЕЛЬНАЯ РЕАКЦИЯ (Rx)
            # Только задние колеса (ведущие) создают активную тягу
            if "rear" in wheel_pos:
                # Rx = Rz * f + Сила для преодоления уклона
                # Делим общую силу уклона на 4 задних колеса
                rx = rz * f + (total_mass * g * math.sin(alpha_rad)) / 4.0
            else:
                # Передние колеса только катятся (Rx минимальна)
                rx = rz * f

            # 5. ПОПЕРЕЧНАЯ РЕАКЦИЯ (Ry)
            ry = (rz * (v_ms**2)) / (g * radius_m) if radius_m < 1000 else 0.0

            # 6. ИЗНОС (ур. 2.27)
            s_step = v_ms * dt # Пройденный путь за шаг аналитики
        
            if v_ms > 0.1:
                # Полная сила сопротивления (эквивалент всех энергетических потерь в пятне контакта)
                total_resistance_force = (f * math.sqrt(rx**2 + ry**2)) / (1 - f)
                
                # По тексту диссертации (стр. 52): на внешнее трение уходит в среднем 10% потерь.
                # Именно эта сила физически отрывает частицы резины от протектора.
                friction_force = total_resistance_force * 0.10
                
                # Температурная деградация (стр. 14): при >100°C прочность падает,
                # при 120-130°C износ ускоряется почти в 3 раза.
                thermal_degradation = 1.0
                if t_sh > 100.0:
                    # Плавно увеличиваем износ: при 100°C коэф=1.0, при 120°C коэф=3.0
                    thermal_degradation = 1.0 + ((t_sh - 100.0) / 20.0) * 10.0
                
                # Итоговый физический износ = Базовая износостойкость * Сила трения * Ухудшение от нагрева * Путь
                wear_mm = ALPHA_TIRE * friction_force * thermal_degradation * s_step
                
            else:
                # БЕЛАЗ стоит - износа нет
                wear_mm = 0.0
            return wear_mm


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
        

        WHEELS_CONFIG = [
            {'db_name': 'Tire_FL', 'telemetry_suffix': 'fl', 'pos': 'front'},
            {'db_name': 'Tire_FR', 'telemetry_suffix': 'fr', 'pos': 'front'},
            {'db_name': 'Tire_RLI', 'telemetry_suffix': 'rli', 'pos': 'rear'},
            {'db_name': 'Tire_RLO', 'telemetry_suffix': 'rlo', 'pos': 'rear'},
            {'db_name': 'Tire_RRI', 'telemetry_suffix': 'rri', 'pos': 'rear'},
            {'db_name': 'Tire_RRO', 'telemetry_suffix': 'rro', 'pos': 'rear'},
        ]

        for wheel in WHEELS_CONFIG:
            wear = calculate_wheel_wear(
                wheel_pos = wheel['pos'],
                speed_kmh = data.get('speed', 0.0),
                payload_kg = payload_kg,
                incline_deg = data.get('incline', 0.0),
                radius_m = data.get('turn_radius', 9999.0),
                p_bar = data.get(f"tire_press_{wheel['telemetry_suffix']}", 700000) / 100000.0,
                t_sh = data.get(f"tire_temp_{wheel['telemetry_suffix']}", 40.0)
            )

            health_loss = (wear / 78.5) * 100.0

            # Обновляем здоровье
            cur.execute("""
                UPDATE component_health 
                SET health_index = health_index - %s, last_update = NOW()
                WHERE truck_id = 1 AND component_name = %s
                RETURNING health_index;
            """, (health_loss, wheel['db_name']))
            
            new_health = cur.fetchone()['health_index']
            
            # Пишем в историю
            cur.execute("""
                INSERT INTO component_health_history (truck_id, component_name, health_index, last_update)
                VALUES (1, %s, %s, NOW());
            """, (wheel['db_name'], new_health))

            if "RLI" in wheel['db_name']: # Лог только для одного заднего для краткости
                print(f"Заднее колесо: Износ {wear:.6f}мм | Здоровье {new_health:.6f}%")

        
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