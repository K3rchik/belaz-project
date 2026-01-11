# -*- coding: utf-8 -*-
import psycopg2
import time
import math
import random
from datetime import datetime

# Настройки БД (Твой IP малинки)
DB_CONFIG = {"host": "10.227.43.86", "database": "belaz_db", "user": "admin", "password": "K3rchikk", "port": "5432"}

# Координаты
POINT_A = {"lat": 67.548, "lon": 33.395} # Погрузка
POINT_B = {"lat": 67.562, "lon": 33.412} # Разгрузка
POINT_C = {"lat": 67.574, "lon": 33.430} # Заправка

class BelazSim:
    def __init__(self):
        self.truck_id = 1
        self.state = "GOING_TO_LOAD"
        self.lat = POINT_B["lat"]
        self.lon = POINT_B["lon"]
        self.payload = 0.0
        self.fuel_level = 1000.0
        self.speed = 0.0
        self.oil_pressure = 4.5
        self.temp = 85.0
        self.incline = 0.0 
        self.fuel_rate = 0.0 
    
    def calculate_fuel_consumption(self):
        """Математическая модель расхода топлива"""
        base_idle = 20.0  # л/час на холостом ходу
        
        # Если машина стоит и не заправляется
        if self.speed == 0 and self.state != "REFUELING":
            self.fuel_rate = base_idle
            return self.fuel_rate

        # Влияние скорости и веса
        work_factor = (self.speed * 1.2) + (self.payload * 0.5)
        
        # Влияние уклона через СИНУС (работа против гравитации)
        # math.sin(math.radians(self.incline)) даст нам % подъема
        # Добавляем множитель 10, чтобы уклон реально "бил" по баку
        incline_effect = math.sin(math.radians(self.incline)) * 10.0
        
        # Итоговый коэффициент нагрузки (не может быть меньше 0.1 при спуске)
        load_multiplier = max(0.1, 1.0 + incline_effect)

        self.fuel_rate = base_idle + (work_factor * load_multiplier)
        return self.fuel_rate

    def update(self, interval_sec):
        # 1. Логика заправки
        if self.fuel_level <= 100.0 and self.state == "GOING_TO_LOAD":
            self.state = "GOING_TO_REFUEL"
            self.incline = 3.0 # Небольшой подъем к заправке

        # 2. Машина состояний
        if self.state == "GOING_TO_REFUEL":
            self.move_towards(POINT_C, speed=35.0)
            if self.at_destination(POINT_C):
                self.state = "REFUELING"
                self.incline = 0.0 
                self.speed = 0.0

        elif self.state == "REFUELING":
            self.fuel_level += 60.0 
            if self.fuel_level >= 1000.0:
                self.fuel_level = 1000.0
                self.state = "GOING_TO_LOAD"
                self.incline = 13.0
                

        elif self.state == "GOING_TO_LOAD":
            self.move_towards(POINT_A, speed=38.0)
            self.incline = -5.0 # Спуск в карьер
            if self.at_destination(POINT_A):
                self.state = "LOADING"

        elif self.state == "LOADING":
            self.speed = 0.0
            self.incline = 0.0
            self.payload += 30.0
            if self.payload >= 90.0:
                self.state = "GOING_TO_DUMP"

        elif self.state == "GOING_TO_DUMP":
            self.move_towards(POINT_B, speed=22.0)
            self.incline = 12.0 # Тяжелый подъем из карьера
            if self.at_destination(POINT_B):
                self.state = "UNLOADING"

        elif self.state == "UNLOADING":
            self.speed = 0.0
            self.incline = 0.0
            self.payload -= 45.0
            if self.payload <= 0:
                self.state = "GOING_TO_LOAD"

        # 3. Расчет расхода и списание топлива
        if self.state != "REFUELING":
            rate = self.calculate_fuel_consumption()
            consumed = (rate / 3600) * interval_sec
            self.fuel_level -= consumed
            
        # Имитация температуры (растет при нагрузке)
        self.temp = 80 + (self.fuel_rate / 5) + random.uniform(-1, 1)

    def move_towards(self, target, speed):
        self.speed = speed
        step = 0.001 
        if self.lat < target["lat"]: self.lat += step
        else: self.lat -= step
        if self.lon < target["lon"]: self.lon += step
        else: self.lon -= step

    def at_destination(self, target):
        return abs(self.lat - target["lat"]) < 0.003 and abs(self.lon - target["lon"]) < 0.003

def start_sim():
    truck = BelazSim()
    interval = 2
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print("ASD Simulator started on PC...")

        while True:
            truck.update(interval)
            now = datetime.now()
            
            params = [
                (now, truck.truck_id, 'latitude', truck.lat),
                (now, truck.truck_id, 'longitude', truck.lon),
                (now, truck.truck_id, 'speed', truck.speed),
                (now, truck.truck_id, 'payload', truck.payload),
                (now, truck.truck_id, 'fuel_level', truck.fuel_level),
                (now, truck.truck_id, 'engine_temp', truck.temp),
                (now, truck.truck_id, 'fuel_rate', truck.fuel_rate),
                (now, truck.truck_id, 'incline', truck.incline)
            ]
            
            for p in params:
                cur.execute("INSERT INTO telemetry (time, truck_id, parameter_name, value) VALUES (%s, %s, %s, %s)", p)
            
            conn.commit()
            print(f"[{truck.state}] Fuel: {truck.fuel_level:.1f}L, Rate: {truck.fuel_rate:.1f}L/h, Incline: {truck.incline}°")
            time.sleep(interval)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    start_sim()