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
    # Создаем объект БелАЗа
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
        print("Система запущена.")
        while True:
            # --- ЛОГИКА СОСТОЯНИЙ (теперь управляется здесь) ---
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
                truck.update_position(POINTS["LOAD"], speed = 35)
                truck.incline = -8.0
                if truck.is_at(POINTS["LOAD"]): 
                    truck.state = "LOADING"
                    truck.loading_cycles_count += 1

            elif truck.state == "LOADING":
                truck.speed, truck.incline = 0.0, 0.0
                
                # --- ИЗМЕНЕНИЕ ДЛЯ ТЕСТА: Шанс перегруза ---
                # В 20% случаев грузим до 140 тонн (это убьет раму)
                if random.random() < 0.2:
                    truck.payload += random.randint(30, 50) # Резкий наброс
                else:
                    truck.payload += random.randint(10, 20) # Нормальная погрузка
                
                # Поднимаем лимит, чтобы генератор не останавливался на 90т
                # Если > 135, считаем что загружен
                #if truck.payload >= 135.0: 
                #    truck.state = "GOING_TO_DUMP"
                #   print(f"!!! ЭМУЛЯЦИЯ: Самосвал перегружен ({truck.payload} т) !!!")
                if truck.payload >= 90.0 and random.random() > 0.8:
                     truck.state = "GOING_TO_DUMP" # Иногда уезжаем с нормой

            elif truck.state == "GOING_TO_DUMP":
                # --- ИЗМЕНЕНИЕ ДЛЯ ТЕСТА: Превышение скорости ---
                # Иногда едем 25 км/ч вместо 15
                target_speed = 25 if random.random() < 0.3 else 15
                
                truck.update_position(POINTS["DUMP"], speed=target_speed)
                truck.incline = 8.0 # Тяжелый подъем
                if truck.is_at(POINTS["DUMP"]): truck.state = "UNLOADING"

            elif truck.state == "GOING_TO_DUMP":
                truck.update_position(POINTS["DUMP"], speed = 15)
                truck.incline = 8.0
                if truck.is_at(POINTS["DUMP"]): truck.state = "UNLOADING"

            elif truck.state == "UNLOADING":
                truck.speed, truck.incline = 0.0, 0.0
                truck.payload -= 45.0
                if truck.payload <= 0:
                    truck.payload = 0
                    truck.state = "GOING_TO_LOAD"

            # --- РАСЧЕТ ФИЗИКИ И ЗАПИСЬ ---
            truck.calculate_physics(dt_seconds=interval)
            truck.update_sensors()

            # Запись в БД
            now = datetime.now()
            params = [
                (now, truck.truck_id, 'speed', truck.speed),
                (now, truck.truck_id, 'payload', truck.payload),
                (now, truck.truck_id, 'fuel_level', truck.fuel_level),
                (now, truck.truck_id, 'fuel_rate', truck.fuel_rate),
                (now, truck.truck_id, 'engine_temp', truck.temp),
                (now, truck.truck_id, 'voltage', truck.voltage),
                (now, truck.truck_id, 'incline', truck.incline),
                (now, truck.truck_id, 'coolant_level', truck.cooling_level),
                (now, truck.truck_id, 'hydraulic_level', truck.hydraulic_level),
                (now, truck.truck_id, 'wheel_press_rf', truck.wheel_pressure_rf),
                (now, truck.truck_id, 'wheel_press_lf', truck.wheel_pressure_lf),
                (now, truck.truck_id, 'wheel_press_rb', truck.wheel_pressure_rb),
                (now, truck.truck_id, 'wheel_press_lb', truck.wheel_pressure_lb),
                (now, truck.truck_id, 'load_cycles', truck.loading_cycles_count),
                (now, truck.truck_id, 'oil_iron', truck.accumulated_iron),
                (now, truck.truck_id, 'current_state', STATE_MAP.get(truck.state, -1))
            ]
            for p in params:
                cur.execute("INSERT INTO telemetry (time, truck_id, parameter_name, value) VALUES (%s, %s, %s, %s)", p)
            
            conn.commit()
            print(f"[{truck.state}] Топливо: {truck.fuel_level:.1f} л. Расход: {truck.fuel_rate:.1f} л/ч")
            time.sleep(interval)

    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    start_sim()