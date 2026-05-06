# -*- coding: utf-8 -*-
import psycopg2
import time
import os
import random
from datetime import datetime
from dotenv import load_dotenv

from belaz_model import BelazSim

STATE_MAP = {
    "GOING_TO_LOAD": 0,
    "LOADING": 1,
    "GOING_TO_DUMP": 2,
    "UNLOADING": 3,
    "GOING_TO_REFUEL": 4,
    "REFUELING": 5
}

load_dotenv()

POINTS = {
    "LOAD": {"lat": 67.548, "lon": 33.395},
    "DUMP": {"lat": 67.562, "lon": 33.412},
    "FUEL": {"lat": 67.574, "lon": 33.430}
}

#Описание трека по сегментам
#Маршрут от Экскаватора (LOAD) до Отвала (DUMP)
TRACK_ROUTE = [
    {"id": 1, "length_m": 200, "incline": 0.0,  "radius": 9999.0, "speed_kmh": 25}, # Прямая из забоя
    {"id": 2, "length_m": 400, "incline": 8.0,  "radius": 9999.0, "speed_kmh": 15}, # Крутой прямой подъем
    {"id": 3, "length_m": 150, "incline": 8.0,  "radius": 45.0,   "speed_kmh": 10}, # Серпантин (подъем + поворот)
    {"id": 4, "length_m": 300, "incline": 3.0,  "radius": 9999.0, "speed_kmh": 20}, # Пологий подъем
    {"id": 5, "length_m": 100, "incline": 0.0,  "radius": 9999.0, "speed_kmh": 15}  # Подъезд к отвалу
]

def start_sim():
    truck = BelazSim(truck_id=1)
    interval = 2
    
    # Переменные для навигации по треку
    current_segment_idx = 0
    dist_on_segment = 0.0
    
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    cur = conn.cursor()

    try:
        print("Система запущена. Мониторинг 6-ти колес активен.")
        while True:
            # Расчет пройденной дистанции за этот тик (interval)
            # Формула: Скорость (км/ч) переводим в м/с и умножаем на секунды
            travel_dist_m = (truck.speed * 1000 / 3600) * interval

            # --- ЛОГИКА СОСТОЯНИЙ ---
            if truck.fuel_level <= 100.0 and truck.state == "GOING_TO_LOAD":
                truck.state = "GOING_TO_REFUEL"

            if truck.state == "GOING_TO_REFUEL":
                truck.update_position(POINTS["FUEL"], speed=35.0)
                truck.incline = 3.0
                if truck.is_at(POINTS["FUEL"]): truck.state = "REFUELING"

            elif truck.state == "REFUELING":
                truck.speed, truck.incline = 0.0, 0.0
                truck.fuel_level += 60.0
                if truck.fuel_level >= truck.fuel_capacity: 
                    truck.state = "GOING_TO_LOAD"
                    truck.fuel_level = truck.fuel_capacity
                    # Сброс навигации для пути обратно
                    current_segment_idx = len(TRACK_ROUTE) - 1 
                    dist_on_segment = 0.0

            elif truck.state == "GOING_TO_LOAD":
                # ЧИТАЕМ ТРЕК КАК СТЕК (С конца в начало)
                if current_segment_idx >= 0:
                    seg = TRACK_ROUTE[current_segment_idx]
                    truck.speed = seg["speed_kmh"] + 10 # Порожний едет быстрее
                    truck.incline = -seg["incline"]     # Подъем стал спуском
                    truck.turn_radius = seg["radius"]
                    
                    dist_on_segment += travel_dist_m
                    if dist_on_segment >= seg["length_m"]:
                        current_segment_idx -= 1 # Шагаем назад по массиву
                        dist_on_segment = 0.0
                else:
                    # Трек закончился
                    truck.state = "LOADING"
                    truck.turn_radius = 9999.0
                    truck.loading_cycles_count += 1

            elif truck.state == "LOADING":
                truck.speed, truck.incline = 0.0, 0.0
                if random.random() < 0.2:
                    truck.payload += random.randint(30, 50)
                else:
                    truck.payload += random.randint(10, 20)
                
                if truck.payload >= 90.0 and random.random() > 0.8:
                     truck.state = "GOING_TO_DUMP"
                     # Сброс навигации для пути туда
                     current_segment_idx = 0 
                     dist_on_segment = 0.0

            elif truck.state == "GOING_TO_DUMP":
                # ЧИТАЕМ ТРЕК КАК ОЧЕРЕДЬ (С начала в конец)
                if current_segment_idx < len(TRACK_ROUTE):
                    seg = TRACK_ROUTE[current_segment_idx]
                    truck.speed = seg["speed_kmh"]
                    truck.incline = seg["incline"]
                    truck.turn_radius = seg["radius"]
                    
                    dist_on_segment += travel_dist_m
                    # Проверяем, проехали ли мы этот сегмент
                    if dist_on_segment >= seg["length_m"]:
                        current_segment_idx += 1 # Шагаем вперед
                        dist_on_segment = 0.0    # Обнуляем прогресс для нового сегмента
                else:
                    # Трек закончился, приехали на выгрузку
                    truck.state = "UNLOADING"

            elif truck.state == "UNLOADING":
                truck.speed, truck.incline = 0.0, 0.0
                truck.payload -= 45.0
                if truck.payload <= 0:
                    truck.payload = 0
                    truck.state = "GOING_TO_LOAD"
                    # Сброс навигации для пути обратно
                    current_segment_idx = len(TRACK_ROUTE) - 1 
                    dist_on_segment = 0.0

            # --- РАСЧЕТ ФИЗИКИ ---
            # Теперь calculate_physics работает с реальными данными сегмента трека!
            truck.calculate_physics(dt_seconds=interval)
            truck.update_sensors()

            # --- СБОР ДАННЫХ ПО СИСТЕМАМ (Осталось без изменений) ---
            now = datetime.now()
            payload_to_db = [
                (now, truck.truck_id, 'speed', truck.speed),
                (now, truck.truck_id, 'payload', truck.payload),
                (now, truck.truck_id, 'current_state', STATE_MAP.get(truck.state, -1)),
                (now, truck.truck_id, 'incline', truck.incline),
                (now, truck.truck_id, 'turn_radius', truck.turn_radius),
                (now, truck.truck_id, 'fuel_level', truck.fuel_level),
                (now, truck.truck_id, 'fuel_rate', truck.fuel_rate),
                (now, truck.truck_id, 'engine_temp', truck.temp),
                (now, truck.truck_id, 'oil_iron', truck.accumulated_iron),
                (now, truck.truck_id, 'voltage', truck.voltage),
                (now, truck.truck_id, 'load_cycles', truck.loading_cycles_count),
                (now, truck.truck_id, 't_ambient', truck.t_ambient),
            ]

            for pos, val in truck.pressures.items():
                payload_to_db.append((now, truck.truck_id, f'tire_press_{pos.lower()}', val))
            for pos, val in truck.temperatures.items():
                payload_to_db.append((now, truck.truck_id, f'tire_temp_{pos.lower()}', val))

            cur.executemany(
                "INSERT INTO telemetry (time, truck_id, parameter_name, value) VALUES (%s, %s, %s, %s)", 
                payload_to_db
            )
            conn.commit()

            # --- ОБНОВЛЕНИЕ НАРАБОТКИ УЗЛОВ (Моточасы) ---
            # Передаем словарь working_hours из объекта truck в новую таблицу
            wh = truck.working_hours
            cur.execute("""
                UPDATE working_hours SET
                    engine = %s,
                    frame = %s,
                    hydraulic = %s,
                    tire_fl = %s,
                    tire_fr = %s,
                    tire_rli = %s,
                    tire_rlo = %s,
                    tire_rri = %s,
                    tire_rro = %s,
                    last_update = NOW()
                WHERE truck_id = %s;
            """, (
                wh['engine'], wh['frame'], wh['hydraulic'],
                wh['tire_fl'], wh['tire_fr'],
                wh['tire_rli'], wh['tire_rlo'],
                wh['tire_rri'], wh['tire_rro'],
                truck.truck_id
            ))
            conn.commit()
            
            # Выводим инфу, чтобы видеть, как он едет по сегментам
            seg_info = f"Сегмент [{current_segment_idx}]" if "GOING" in truck.state else ""
            print(f"[{truck.state}] {seg_info} Скорость: {truck.speed} км/ч, Уклон: {truck.incline}%")
            
            time.sleep(interval)

    except Exception as e:
        print(f"Ошибка симулятора: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    start_sim()