# -*- coding: utf-8 -*-
"""
Модуль предиктивной аналитики (Цифровой двойник маршрута).
Вычисляет будущий износ и температуру КГШ на основе заданного маршрута (трека).
НЕ использует базу данных (PostgreSQL), работает полностью в оперативной памяти.
"""

import math

# --- КОНСТАНТЫ МОДЕЛИ ---
ALPHA_TIRE = 1.0e-8   # Износостойкость (стр. 61)
MAX_PAYLOAD = 130000.0  
MASS_EMPTY = 107100.0
H_EMPTY = 2.1
H_LOADED = 2.5
LA = 5.3

def calculate_wheel_wear(wheel_pos, speed_kmh, payload_kg, incline_deg, radius_m, p_bar, t_sh, dt):
    """
    Математическая модель расчета физического износа.
    (Взята без изменений из основной аналитики)
    """
    if speed_kmh < 0.5: return 0.0

    v_ms = speed_kmh / 3.6
    alpha_rad = math.radians(incline_deg)
    load_factor = min(1.0, payload_kg / MAX_PAYLOAD)

    front_ratio = 0.509 - (0.509 - 0.330) * load_factor
    rear_ratio = 0.491 + (0.670 - 0.491) * load_factor
    h_curr = H_EMPTY + (H_LOADED - H_EMPTY) * load_factor
    total_mass = MASS_EMPTY + payload_kg
    g = 9.81

    if "front" in wheel_pos:
        n = 2
        rz = (total_mass * g * (front_ratio * math.cos(alpha_rad) - (h_curr/LA) * math.sin(alpha_rad))) / n
    else:
        n = 4
        rz = (total_mass * g * (rear_ratio * math.cos(alpha_rad) + (h_curr/LA) * math.sin(alpha_rad))) / n

    f = 0.001 * ((20.2 / (0.64 * p_bar)) + (speed_kmh**3.7 / (778 * p_bar**2.03)))

    if "rear" in wheel_pos:
        rx = rz * f + (total_mass * g * math.sin(alpha_rad)) / 4.0
    else:
        rx = rz * f

    ry = (rz * (v_ms**2)) / (g * radius_m) if radius_m < 1000 else 0.0

    s_step = v_ms * dt
    if v_ms > 0.1:
        total_resistance_force = (f * math.sqrt(rx**2 + ry**2)) / (1 - f)
        friction_force = total_resistance_force * 0.10
        
        # Температурная деградация
        thermal_degradation = 1.0
        if t_sh > 100.0:
            thermal_degradation = 1.0 + ((t_sh - 100.0) / 20.0) * 2.0
        
        wear_mm = ALPHA_TIRE * friction_force * thermal_degradation * s_step
    else:
        wear_mm = 0.0
        
    return wear_mm


def get_equilibrium_temp(wheel_pos, t_ambient, mass_tons, speed_kmh):
    """
    Эмпирические формулы нагрева КГШ (ТКВЧ).
    """
    if 'front' in wheel_pos:
        return 30.1 + 0.6 * t_ambient + 0.078 * mass_tons * speed_kmh
    else:
        return 25.8 + 0.6 * t_ambient + 0.076 * mass_tons * speed_kmh


def predict_shift_wear(track_route, num_cycles, payload_kg, t_ambient=20.0, nominal_press_bar=7.0):
    """
    Прогоняет виртуальный БелАЗ по треку N раз и возвращает итоговое состояние шин.
    """
    
    # 1. Инициализация Виртуального состояния (Память о шинах)
    WHEELS_CONFIG = [
        {'id': 'Tire_FL', 'pos': 'front'}, {'id': 'Tire_FR', 'pos': 'front'},
        {'id': 'Tire_RLI', 'pos': 'rear'}, {'id': 'Tire_RLO', 'pos': 'rear'},
        {'id': 'Tire_RRI', 'pos': 'rear'}, {'id': 'Tire_RRO', 'pos': 'rear'},
    ]
    
    # Стартовое состояние: износа нет, шины равны температуре улицы
    virtual_state = {
        wheel['id']: {'wear_mm': 0.0, 'temp_c': t_ambient, 'pos': wheel['pos']} 
        for wheel in WHEELS_CONFIG
    }

    mass_loaded_tons = (MASS_EMPTY + payload_kg) / 1000.0
    mass_empty_tons = MASS_EMPTY / 1000.0

    print(f"--- ЗАПУСК ПРЕДСКАЗАНИЯ: {num_cycles} РЕЙСОВ ---")
    print(f"Масса груза: {payload_kg} кг | Температура среды: {t_ambient}°C\n")
    
    # 2. Симуляция рейсов
    for cycle in range(1, num_cycles + 1):
        
        # --- А) ПУТЬ ТУДА (Груженый к отвалу, читаем как ОЧЕРЕДЬ) ---
        for segment in track_route:
            v_ms = segment['speed_kmh'] / 3.6
            dt_seconds = segment['length_m'] / v_ms if v_ms > 0 else 0
            
            for w_id, state in virtual_state.items():
                # Расчет температуры с учетом инерции нагрева
                target_temp = get_equilibrium_temp(state['pos'], t_ambient, mass_loaded_tons, segment['speed_kmh'])
                heat_transfer_coef = 0.05 * (dt_seconds / 60.0)
                state['temp_c'] += (target_temp - state['temp_c']) * heat_transfer_coef
                
                # Расчет износа на основе актуальной температуры
                wear = calculate_wheel_wear(
                    wheel_pos=state['pos'],
                    speed_kmh=segment['speed_kmh'],
                    payload_kg=payload_kg,
                    incline_deg=segment['incline'],
                    radius_m=segment['radius'],
                    p_bar=nominal_press_bar,
                    t_sh=state['temp_c'], 
                    dt=dt_seconds         
                )
                state['wear_mm'] += wear

        # Небольшое остывание во время выгрузки (2-3 минуты)
        for state in virtual_state.values():
            state['temp_c'] = max(t_ambient, state['temp_c'] - 5.0)

        # --- Б) ПУТЬ ОБРАТНО (Порожний в забой, читаем как СТЕК с конца) ---
        for segment in reversed(track_route):
            empty_speed = segment['speed_kmh'] + 10 # Пустой едет быстрее
            v_ms = empty_speed / 3.6 
            dt_seconds = segment['length_m'] / v_ms if v_ms > 0 else 0
            
            for w_id, state in virtual_state.items():
                target_temp = get_equilibrium_temp(state['pos'], t_ambient, mass_empty_tons, empty_speed)
                state['temp_c'] += (target_temp - state['temp_c']) * (0.05 * (dt_seconds / 60.0))
                
                wear = calculate_wheel_wear(
                    wheel_pos=state['pos'],
                    speed_kmh=empty_speed,
                    payload_kg=0.0,                  # Машина пустая!
                    incline_deg=-segment['incline'], # Подъем стал спуском!
                    radius_m=segment['radius'],
                    p_bar=nominal_press_bar,
                    t_sh=state['temp_c'],
                    dt=dt_seconds
                )
                state['wear_mm'] += wear

        # Остывание в очереди под экскаватором
        for state in virtual_state.values():
            state['temp_c'] = max(t_ambient, state['temp_c'] - 10.0)

    # 3. Возвращаем результаты
    return virtual_state

# =====================================================================
# ТЕСТИРОВАНИЕ РАБОТЫ СКРИПТА
# =====================================================================
if __name__ == "__main__":
    
    # Пример трека (Тот же, что мы прописали в receiver.py)
    # length_m: длина куска, incline: уклон в %, radius: радиус поворота (9999 = прямая)
    SAMPLE_TRACK = [
        {"id": 1, "length_m": 200, "incline": 0.0,  "radius": 9999.0, "speed_kmh": 25}, 
        {"id": 2, "length_m": 400, "incline": 8.0,  "radius": 9999.0, "speed_kmh": 15}, 
        {"id": 3, "length_m": 150, "incline": 8.0,  "radius": 45.0,   "speed_kmh": 10}, # Серпантин!
        {"id": 4, "length_m": 300, "incline": 3.0,  "radius": 9999.0, "speed_kmh": 20}, 
        {"id": 5, "length_m": 100, "incline": 0.0,  "radius": 9999.0, "speed_kmh": 15}  
    ]
    
    # Запускаем симуляцию на 30 рейсов
    results = predict_shift_wear(
        track_route=SAMPLE_TRACK, 
        num_cycles=30, 
        payload_kg=130000.0, # Груз 130 тонн
        t_ambient=20.0       # Лето, +22 градуса
    )
    
    # Красивый вывод в консоль
    for w_id, data in results.items():
        # Начальный слой протектора = 78.5 мм
        health_percent = 100.0 - ((data['wear_mm'] / 78.5) * 100.0)
        
        print(f"[{w_id}] ({data['pos'].upper()}):")
        print(f"  Стерто протектора: {data['wear_mm']:.4f} мм")
        print(f"  Остаток ресурса:   {health_percent:.2f}%")
        print(f"  Температура:       {data['temp_c']:.1f} °C")
        print("-" * 30)