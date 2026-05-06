# -*- coding: utf-8 -*-
"""
Модуль предиктивной аналитики (Цифровой двойник маршрута).
Вычисляет будущий износ и температуру КГШ на основе заданного маршрута (трека).
Реализует интегральную оценку ресурса на основе мощностного баланса (диссертация Горюнова) 
и физически корректную модель теплообмена (модель 1-го порядка).
"""

import math

# --- 1. КОНСТАНТЫ МОДЕЛИ ---
ALPHA_TIRE = 1.0e-8    # Базовая износостойкость (откалибрована под симуляцию)
MAX_PAYLOAD = 130000.0 # Макс. нагрузка (кг) 
MASS_EMPTY = 107100.0  # Снаряженная масса (кг)
H_EMPTY = 2.1          # Высота центра масс пустой (м)
H_LOADED = 2.5         # Высота центра масс груженый (м)
LA = 5.3               # Колесная база (м)
OTD_MAX = 78.5         # Начальный протектор Bridgestone (мм)

# Параметры теплообмена (Решение Проблемы №2 и №4)
TAU_DRIVE_BASE = 900.0   # Базовая постоянная времени в движении (сек)
TAU_COOL_STOP = 1400.0   # Постоянная времени на стоянке (сек)
T_soft_limit = 100.0     # Температура начала нелинейной теплоотдачи (C)
T_hard_limit = 118.0     # Физический предел стабилизации (C)

def calculate_wheel_wear(wheel_pos, speed_kmh, payload_kg, incline_deg, radius_m, p_bar, t_sh, dt):
    """
    Математическая модель расчета физического износа (ур. 2.27).
    """
    if speed_kmh < 0.5: return 0.0

    v_ms = speed_kmh / 3.6
    alpha_rad = math.radians(incline_deg)
    load_factor = min(1.0, payload_kg / MAX_PAYLOAD)

    # Динамическая развесовка (согласно ТТХ БЕЛАЗ 75131)
    front_ratio = 0.509 - (0.509 - 0.330) * load_factor
    rear_ratio = 0.491 + (0.670 - 0.491) * load_factor
    h_curr = H_EMPTY + (H_LOADED - H_EMPTY) * load_factor
    total_mass = MASS_EMPTY + payload_kg
    g = 9.81

    # Нормальная реакция Rz (с учетом переноса массы на уклонах)
    if "front" in wheel_pos:
        n = 2
        rz = (total_mass * g * (0.509 * math.cos(alpha_rad) - (h_curr/LA) * math.sin(alpha_rad))) / n
    else:
        n = 4
        rz = (total_mass * g * (0.491 * math.cos(alpha_rad) + (h_curr/LA) * math.sin(alpha_rad))) / n

    # Коэффициент сопротивления качению f (ур. 2.24)
    f = 0.001 * ((20.2 / (0.64 * p_bar)) + (speed_kmh**3.7 / (778 * p_bar**2.03)))

    # Продольная сила Rx (только для задней ведущей оси учитываем тягу)
    if "rear" in wheel_pos:
        rx = rz * f + (total_mass * g * math.sin(alpha_rad)) / 4.0
    else:
        rx = rz * f

    # Поперечная сила Ry
    ry = (rz * (v_ms**2)) / (g * radius_m) if radius_m < 1000 else 0.0

    s_step = v_ms * dt
    if v_ms > 0.1:
        # Мощностной баланс
        total_resistance_force = (f * math.sqrt(rx**2 + ry**2)) / (1 - f)
        # Доля энергии, идущая на механический износ (10% по стр. 52)
        friction_force = total_resistance_force * 0.10
        
        # Температурная деградация (стр. 14): ускорение износа при перегреве
        thermal_degradation = 1.0
        if t_sh > 100.0:
            thermal_degradation = 1.0 + ((t_sh - 100.0) / 20.0) * 2.0 # рост в 3 раза к 120C
        
        wear_mm = ALPHA_TIRE * friction_force * thermal_degradation * s_step
    else:
        wear_mm = 0.0
        
    return wear_mm

def get_equilibrium_temp(wheel_pos, t_ambient, mass_tons, speed_kmh, incline_deg, radius_m):
    """
    Расширенная формула равновесной температуры (Решение Проблемы №1).
    """
    if 'front' in wheel_pos:
        t_base = 30.1 + 0.6 * t_ambient + 0.078 * mass_tons * speed_kmh
    else:
        t_base = 25.8 + 0.6 * t_ambient + 0.076 * mass_tons * speed_kmh

    # Коррекция на уклон (подъем увеличивает внутреннее трение)
    incline_factor = 1.0 + (max(0, incline_deg) * 0.012)
    # Коррекция на повороты (боковой увод)
    turn_factor = 1.0 + (500 / max(50, radius_m)) * 0.015 if radius_m < 500 else 1.0

    return t_base * incline_factor * turn_factor

def predict_shift_wear(track_route, num_cycles, payload_kg, t_ambient=20.0, nominal_press_bar=7.0):
    """
    Симуляция N рабочих циклов БелАЗа по заданному маршруту.
    """
    WHEELS_CONFIG = [
        {'id': 'Tire_FL', 'pos': 'front'}, {'id': 'Tire_FR', 'pos': 'front'},
        {'id': 'Tire_RLI', 'pos': 'rear'}, {'id': 'Tire_RLO', 'pos': 'rear'},
        {'id': 'Tire_RRI', 'pos': 'rear'}, {'id': 'Tire_RRO', 'pos': 'rear'},
    ]
    
    virtual_state = {
        wheel['id']: {'wear_mm': 0.0, 'temp_c': t_ambient, 'pos': wheel['pos']} 
        for wheel in WHEELS_CONFIG
    }

    mass_loaded_tons = (MASS_EMPTY + payload_kg) / 1000.0
    mass_empty_tons = MASS_EMPTY / 1000.0

    print(f"--- ЗАПУСК ПРЕДСКАЗАНИЯ: {num_cycles} РЕЙСОВ ---")

    for cycle in range(1, num_cycles + 1):
        
        # --- А) ПУТЬ ТУДА (Груженый) ---
        for segment in track_route:
            v_ms = segment['speed_kmh'] / 3.6
            dt_seconds = segment['length_m'] / v_ms if v_ms > 0 else 0
            
            for w_id, state in virtual_state.items():
                T_target = get_equilibrium_temp(
                    state['pos'], t_ambient, mass_loaded_tons, 
                    segment['speed_kmh'], segment['incline'], segment['radius']
                )
                T_current = state['temp_c']

                # Экспоненциальный теплообмен (Решение Проблем №2, №4)
                tau_drive = TAU_DRIVE_BASE / (1.0 + 0.018 * segment['speed_kmh'])
                heat_factor = 1.0 - math.exp(-dt_seconds / tau_drive)

                # Нелинейное ускорение охлаждения при перегреве
                if T_current > T_soft_limit:
                    boost = 1.0 + 1.8 * ((T_current - T_soft_limit) / (T_hard_limit - T_soft_limit))**2
                    heat_factor /= boost
                
                # Логистическое насыщение целевой температуры
                if T_target > T_hard_limit:
                    T_target = T_hard_limit - 4.0 * math.exp(-0.15 * (T_target - T_hard_limit))

                # Обновление температуры и расчет износа
                state['temp_c'] += (T_target - T_current) * heat_factor
                state['temp_c'] = max(t_ambient, state['temp_c'])

                wear = calculate_wheel_wear(
                    state['pos'], segment['speed_kmh'], payload_kg, 
                    segment['incline'], segment['radius'], nominal_press_bar,
                    state['temp_c'], dt_seconds
                )
                state['wear_mm'] += wear

        # Остывание при разгрузке (3 мин)
        factor_unload = 1.0 - math.exp(-180.0 / TAU_COOL_STOP)
        for state in virtual_state.values():
            state['temp_c'] -= (state['temp_c'] - t_ambient) * factor_unload

        # --- Б) ПУТЬ ОБРАТНО (Порожний) ---
        for segment in reversed(track_route):
            empty_speed = segment['speed_kmh'] + 10
            v_ms = empty_speed / 3.6
            dt_seconds = segment['length_m'] / v_ms
            
            for w_id, state in virtual_state.items():
                T_target = get_equilibrium_temp(
                    state['pos'], t_ambient, mass_empty_tons, 
                    empty_speed, -segment['incline'], segment['radius']
                )
                T_current = state['temp_c']

                tau_drive = TAU_DRIVE_BASE / (1.0 + 0.018 * empty_speed)
                heat_factor = 1.0 - math.exp(-dt_seconds / tau_drive)

                if T_current > T_soft_limit:
                    boost = 1.0 + 1.8 * ((T_current - T_soft_limit) / (T_hard_limit - T_soft_limit))**2
                    heat_factor /= boost
                
                if T_target > T_hard_limit:
                    T_target = T_hard_limit - 4.0 * math.exp(-0.15 * (T_target - T_hard_limit))

                state['temp_c'] += (T_target - T_current) * heat_factor
                state['temp_c'] = max(t_ambient, state['temp_c'])

                wear = calculate_wheel_wear(
                    state['pos'], empty_speed, 0.0, 
                    -segment['incline'], segment['radius'], nominal_press_bar,
                    state['temp_c'], dt_seconds
                )
                state['wear_mm'] += wear

        # Остывание под погрузкой (2 мин)
        factor_load = 1.0 - math.exp(-120.0 / TAU_COOL_STOP)
        for state in virtual_state.values():
            state['temp_c'] -= (state['temp_c'] - t_ambient) * factor_load

    return virtual_state

# =====================================================================
# ТЕСТИРОВАНИЕ РАБОТЫ СКРИПТА (ЗАГРУЗКА ТРАССЫ ИЗ БД)
# =====================================================================
import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

def fetch_track_from_db():
    """ Читает трассу Андрея из базы данных и преобразует в формат сегментов. """
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"), database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD")
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Читаем все точки маршрута, отсортированные по ID (или по дистанции)
        cur.execute("SELECT * FROM track_data ORDER BY id ASC;")
        rows = cur.fetchall()
        
        track_route = []
        prev_distance = 0.0
        
        for row in rows:
            current_distance = float(row['distance'])
            
            # Вычисляем длину конкретного сегмента (разница между точками)
            segment_length = current_distance - prev_distance
            
            # Защита от нулевых сегментов (например, самая первая точка)
            if segment_length <= 0:
                segment_length = 5.0 # Стандартный шаг Андрея
                
            track_route.append({
                "id": row['id'],
                "length_m": segment_length,
                "incline": float(row['incline']),
                "radius": float(row['turn_radius']),
                "speed_kmh": float(row['speed'])
            })
            
            prev_distance = current_distance
            
        cur.close()
        conn.close()
        return track_route
        
    except Exception as e:
        print(f"Ошибка загрузки трассы из БД: {e}")
        return []

if __name__ == "__main__":
    
    # 1. Загружаем реальную трассу Андрея
    REAL_TRACK = fetch_track_from_db()
    
    if not REAL_TRACK:
        print("В базе нет данных о трассе! Запустите скрипт Андрея в Unity.")
    else:
        print(f"Успешно загружено {len(REAL_TRACK)} сегментов трассы из БД.")
        
        # 2. Запускаем симуляцию
        # t_ambient = 30.0 (Лето), Груз = 130 000 кг (Полный)
        results = predict_shift_wear(
            track_route=REAL_TRACK, 
            num_cycles=30, 
            payload_kg=130000.0, 
            t_ambient=30.0       
        )
        
        # 3. Красивый вывод в консоль
        print("\n=== РЕЗУЛЬТАТЫ СИМУЛЯЦИИ (30 РЕЙСОВ ПО РЕАЛЬНОЙ ТРАССЕ) ===")
        for w_id, data in results.items():
            health_percent = 100.0 - ((data['wear_mm'] / OTD_MAX) * 100.0)
            print(f"[{w_id}] ({data['pos'].upper()}):")
            print(f"  Стерто протектора: {data['wear_mm']:.4f} мм")
            print(f"  Остаток ресурса:   {health_percent:.2f}%")
            print(f"  Температура:       {data['temp_c']:.1f} °C")
            print("-" * 40)