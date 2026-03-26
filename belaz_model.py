# -*- coding: utf-8 -*-
import math
import random

class BelazSim:
    def __init__(self, truck_id, 
                 initial_fuel = 1900.0, 
                 initial_cool = 320.0,
                 initial_greasing = 195.0,
                 initial_hydraulic = 510.0,
                 initial_gearbox = 46,
                 initial_suspension_front = 31.6,
                 initial_suspension_back = 29.1,
                 initial_engine_hours=1000.0):
        
        # --- НЕИЗМЕНЯЕМЫЕ ПАРАМЕТРЫ (из ТТХ БЕЛАЗ 75131) ---
        self.truck_id = truck_id
        self.mass = 107100.0          # Масса пустого (кг)
        self.fuel_capacity = 1900
        self.wheeltype = "diagonal"   # "diagonal" или "radial"
        self.t_ambient = 20.0         # Температура воздуха (t_cp)
        self.picket_dist = 100.0      # Длина участка (пикета)
        
        if self.wheeltype == "diagonal":
            self.lifting_cap = 130000.0
            self.base_pressure = 610000.0 # 6.1 bar
        else:
            self.lifting_cap = 136000.0
            self.base_pressure = 700000.0 # 7.0 bar

        # --- СОСТОЯНИЕ И ТЕЛЕМЕТРИЯ ---
        self.state = "GOING_TO_LOAD"
        self.speed = 0.0
        self.incline = 0.0
        self.turn_radius = 9999.0
        self.payload = 0.0
        self.lat = 67.562
        self.lon = 33.412
        
        # Давление в 6 колесах (Паскали)
        self.pressures = {
            'FL': self.base_pressure, 'FR': self.base_pressure,
            'RLI': self.base_pressure, 'RLO': self.base_pressure,
            'RRI': self.base_pressure, 'RRO': self.base_pressure
        }
        
        # Температура в 6 колесах (Цельсий)
        self.temperatures = {
            'FL': 25.0, 'FR': 25.0,
            'RLI': 25.0, 'RLO': 25.0,
            'RRI': 25.0, 'RRO': 25.0
        }

        # Остальные системы
        self.fuel_level = initial_fuel
        self.temp = 85.0 # Температура ДВС
        self.accumulated_iron = 15.0
        self.total_engine_hours = initial_engine_hours
        self.loading_cycles_count = 0
        self.fuel_rate = 0.0
        self.voltage = 24.0
        self.cooling_level = initial_cool
        self.hydraulic_level = initial_hydraulic

    def update_sensors(self):
        """
        Расчет физики колес на основе динамической развесовки (данные со скриншота)
        """
        total_mass = self.mass + self.payload
        load_factor = min(1.0, self.payload / self.lifting_cap)

        # 1. ДИНАМИЧЕСКАЯ РАЗВЕСОВКА (Интерполяция данных со скриншота)
        # Передняя ось: 50.9% (пустой) -> 33.0% (груженый)
        # Задняя ось: 49.1% (пустой) -> 67.0% (груженый)
        front_ratio = 0.509 - (0.509 - 0.330) * load_factor
        rear_ratio = 0.491 + (0.670 - 0.491) * load_factor

        # Нагрузка на ОДНО колесо (в тоннах)
        q_front_wheel = (total_mass * front_ratio) / 2.0 / 1000.0
        q_rear_wheel = (total_mass * rear_ratio) / 4.0 / 1000.0

        # 2. РАСЧЕТ ТЕМПЕРАТУРЫ (Формула 2.15 Горюнова)
        # t = 30.1 + 0.6*t_cp + 0.078 * Q * V
        t_base_front = 30.1 + 0.6 * self.t_ambient + 0.078 * q_front_wheel * self.speed
        t_base_rear = 30.1 + 0.6 * self.t_ambient + 0.078 * q_rear_wheel * self.speed

        # Обновляем все 6 колес с небольшим случайным шумом
        for key in self.temperatures:
            base_t = t_base_front if 'F' in key else t_base_rear
            self.temperatures[key] = base_t + random.uniform(-0.5, 0.5)

        # 3. ИМИТАЦИЯ ДАВЛЕНИЯ (растет при нагреве + шум)
        for key in self.pressures:
            thermal_expansion = (self.temperatures[key] - 25.0) * 1500.0 # Упрощенно
            self.pressures[key] = self.base_pressure + thermal_expansion + random.uniform(-500, 500)

    def calculate_physics(self, dt_seconds=2):
        total_mass_ton = (self.mass + self.payload) / 1000.0
        step_hours = dt_seconds / 3600.0
        
        # Расход топлива
        base_consumption = 25.0 
        if self.speed > 1:
            i = self.incline * 10 
            resistance_factor = (0.0005 * i**2 + 0.06 * i + 1.25) if i > 0 else 0.2
            work_load = (total_mass_ton * self.speed) / 200.0
            self.fuel_rate = base_consumption + (work_load * resistance_factor)
        else:
            self.fuel_rate = base_consumption + (10 if self.payload > 0 else 0)

        # Накопление железа
        load_intensity = self.fuel_rate / 100.0
        iron_rate_per_hour = 0.05 * math.exp(1.2 * (load_intensity - 1))
        self.accumulated_iron += iron_rate_per_hour * step_hours
        self.total_engine_hours += step_hours
        
        # Обновление бака и температуры ДВС
        self.fuel_level -= self.fuel_rate * step_hours
        target_temp = 80 + (self.fuel_rate / 10.0) 
        self.temp += (target_temp - self.temp) * 0.1

        return self.fuel_rate

    def update_position(self, target, speed):
        self.speed = speed
        step = speed/36000.0 
        if self.lat < target["lat"]: self.lat += step
        else: self.lat -= step
        if self.lon < target["lon"]: self.lon += step
        else: self.lon -= step

    def is_at(self, target):
        return abs(self.lat - target["lat"]) < 0.003 and abs(self.lon - target["lon"]) < 0.003