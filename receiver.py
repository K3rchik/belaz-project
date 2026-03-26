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

# Константы маршрута
POINTS = {
    "LOAD": {"lat": 67.548, "lon": 33.395},
    "DUMP": {"lat": 67.562, "lon": 33.412},
    "FUEL": {"lat": 67.574, "lon": 33.430}
}

def start_sim():
    truck = BelazSim(truck_id=1)
    interval = 2
    
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

            elif truck.state == "GOING_TO_LOAD":
                target_speed = 25 if random.random() < 0.3 else 15
                truck.update_position(POINTS["LOAD"], speed = target_speed)
                truck.incline = -8.0
                truck.turn_radius = 150.0 if random.random() > 0.5 else 9999.0
                if truck.is_at(POINTS["LOAD"]): 
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

            elif truck.state == "GOING_TO_DUMP":
                target_speed = 25 if random.random() < 0.3 else 15
                truck.update_position(POINTS["DUMP"], speed=target_speed)
                truck.incline = 8.0 
                # Имитируем поворот на серпантине
                truck.turn_radius = 200.0 if random.random() > 0.7 else 9999.0
                if truck.is_at(POINTS["DUMP"]): truck.state = "UNLOADING"

            elif truck.state == "UNLOADING":
                truck.speed, truck.incline = 0.0, 0.0
                truck.payload -= 45.0
                if truck.payload <= 0:
                    truck.payload = 0
                    truck.state = "GOING_TO_LOAD"

            # --- РАСЧЕТ ФИЗИКИ ---
            truck.calculate_physics(dt_seconds=interval)
            truck.update_sensors()

            # --- СБОР ДАННЫХ ПО СИСТЕМАМ ---
            now = datetime.now()
            payload_to_db = [
                # Группа: Общие (Vehicle)
                (now, truck.truck_id, 'speed', truck.speed),
                (now, truck.truck_id, 'payload', truck.payload),
                (now, truck.truck_id, 'current_state', STATE_MAP.get(truck.state, -1)),
                (now, truck.truck_id, 'incline', truck.incline),
                (now, truck.truck_id, 'turn_radius', truck.turn_radius),
                
                # Группа: Двигатель (Engine)
                (now, truck.truck_id, 'fuel_level', truck.fuel_level),
                (now, truck.truck_id, 'fuel_rate', truck.fuel_rate),
                (now, truck.truck_id, 'engine_temp', truck.temp),
                (now, truck.truck_id, 'oil_iron', truck.accumulated_iron),
                (now, truck.truck_id, 'voltage', truck.voltage),
                (now, truck.truck_id, 'load_cycles', truck.loading_cycles_count),
                
                # Группа: Среда (Environment)
                (now, truck.truck_id, 't_ambient', truck.t_ambient),
            ]

            # Группа: Шины (Tires) - Динамически добавляем все 6 колес
            for pos, val in truck.pressures.items():
                payload_to_db.append((now, truck.truck_id, f'tire_press_{pos.lower()}', val))
            
            for pos, val in truck.temperatures.items():
                payload_to_db.append((now, truck.truck_id, f'tire_temp_{pos.lower()}', val))

            # Запись всего пакета в БД
            cur.executemany(
                "INSERT INTO telemetry (time, truck_id, parameter_name, value) VALUES (%s, %s, %s, %s)", 
                payload_to_db
            )
            
            conn.commit()
            print(f"[{truck.state}] Данные отправлены. Скорость: {truck.speed} км/ч, Груз: {truck.payload} кг")
            time.sleep(interval)

    except Exception as e:
        print(f"Ошибка симулятора: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    start_sim()