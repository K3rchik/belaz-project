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
                 initial_suspension_back = 29.1):
        
        #неизменяемые
        self.truck_id = truck_id
        self.mass = 107100 
        self.fuel_capacity = 1900
        self.basket_volume = 104
        self.wheeltype = "diagonal" #диагональные (33.00-51 или 36/90-51)
                                    #радиальные (33.00R51)
        
        if self.wheeltype == "diagonal":
            self.lifting_cap = 130000
        elif self.wheeltype == "radial":
            self.lifting_cap = 136000

        #изменяемые
        self.lat = 67.562
        self.lon = 33.412
        self.state = "GOING_TO_LOAD"
        self.incline = 0.0

        self.payload = 0.0
        self.basket_pressure = 0.0

        if self.wheeltype == "diagonal":
            self.wheel_pressure_rf = 610000
            self.wheel_pressure_lf = 610000
            self.wheel_pressure_rb = 610000
            self.wheel_pressure_lb = 610000
        elif self.wheeltype == "radial":
            self.wheel_pressure_rf = 700000
            self.wheel_pressure_lf = 700000
            self.wheel_pressure_rb = 700000
            self.wheel_pressure_lb = 700000
        
        self.wheel_temperature_rf = 60
        self.wheel_temperature_lf = 60
        self.wheel_temperature_rb = 60
        self.wheel_temperature_lb = 60
        self.fuel_rate = 0.0
        self.speed = 0.0
        self.temp = 85.0
        self.rpm = 0.0
        self.voltage = 24 

        #заправочные емкости
        self.fuel_level = initial_fuel #Топливный бак
        self.cooling_level = initial_cool #Система охлаждения двигателя
        self.greasing_level = initial_greasing #Система смазки двигателя
        self.hydraulic_level = initial_hydraulic #Гидравлическая система
        self.gearbox_level_1 = initial_gearbox #Редукторы мотор-колес
        self.gearbox_level_2 = initial_gearbox #Редукторы мотор-колес
        self.suspension_level_f1 = initial_suspension_front #Передние цилиндры подвески
        self.suspension_level_f2 = initial_suspension_front #Передние цилиндры подвески
        self.suspension_level_b1 = initial_suspension_back #Задние цилиндры подвески
        self.suspension_level_b2 = initial_suspension_back #Задние цилиндры подвески


    def calculate_fuel_consumption(self):
        """Математическая модель расхода топлива"""
        base_idle = 25.0
        if self.state == "REFUELING":
            self.fuel_rate = 0.0
            return 0.0

        if self.state == "LOADING":
            self.fuel_rate = base_idle + (self.payload * 0.1)
            return self.fuel_rate

        # Физика движения
        work_factor = (self.speed * 1.2) + (self.payload * 0.5)
        incline_effect = math.sin(math.radians(self.incline)) * 10.0
        load_multiplier = max(0.1, 1.0 + incline_effect)
        
        self.fuel_rate = base_idle + (work_factor * load_multiplier)
        return self.fuel_rate

    def update_position(self, target, speed):
        """Логика перемещения"""
        self.speed = speed
        step = speed/36000.0 

        if self.lat < target["lat"]: self.lat += step
        else: self.lat -= step
        if self.lon < target["lon"]: self.lon += step
        else: self.lon -= step
    
    def update_sensors(self):
        """Имитация естественного колебания датчиков (шум)"""
        # Давление в шинах
        jitter = random.uniform(-500, 500) 
        self.wheel_pressure_rf += jitter

        jitter = random.uniform(-500, 500) 
        self.wheel_pressure_lf += jitter

        jitter = random.uniform(-500, 500) 
        self.wheel_pressure_rb += jitter

        jitter = random.uniform(-500, 500) 
        self.wheel_pressure_lb += jitter
        
        # Температура ДВС колеблется вокруг целевой
        self.temp += random.uniform(-0.2, 0.2)
        
        # Напряжение сети (24В +/- 0.5В)
        self.voltage = 24.0 + random.uniform(-0.5, 0.5)

    def is_at(self, target):
        """Проверка достижения точки"""
        return abs(self.lat - target["lat"]) < 0.003 and abs(self.lon - target["lon"]) < 0.003