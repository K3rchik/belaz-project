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
        
        #неизменяемые
        self.truck_id = truck_id
        self.mass = 107100 
        self.fuel_capacity = 1900
        self.basket_volume = 104
        self.wheeltype = "diagonal" #диагональные (33.00-51 или 36/90-51)
                                    #радиальные (33.00R51)
        self.t_ambient = 20.0        # Температура воздуха
        self.picket_dist = 100.0     # Длина участка (пикета)
        
        if self.wheeltype == "diagonal":
            self.lifting_cap = 130000
        elif self.wheeltype == "radial":
            self.lifting_cap = 136000

        #изменяемые
        self.turn_radius = 9999.0    # Радиус поворота (9999 - прямая)
        self.consuption = 0.0
        self.lat = 67.562
        self.lon = 33.412
        self.state = "GOING_TO_LOAD"
        self.incline = 0.0
        self.loading_cycles_count = 0 # Счетчик циклов погрузки

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
        self.oil_pressure = 4.5 
        self.accumulated_iron = 15.0 # мг/кг (начальное загрязнение)
        self.total_engine_hours = initial_engine_hours 

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


    

    def calculate_physics(self, dt_seconds=2):
        """
        Главный метод расчета физики. Вызывается каждый шаг симуляции.
        """
        # 1. Расчет общей массы (т)
        total_mass_ton = (self.mass + self.payload) / 1000.0
        
        # 2. РАСХОД ТОПЛИВА (Формула Паначева + адаптация)
        # Базовый расход на холостых ~25 л/ч
        base_consumption = 25.0 
        
        if self.speed > 1:
            # Формула энергоемкости от уклона (Паначев, стр. 68): P = 0.0005*i^2 + ...
            # i - уклон в промилле, у нас в процентах, умножаем на 10
            i = self.incline * 10 
            
            # Коэффициент сопротивления движению (упрощенно)
            # Если едем вверх (i>0) - тяжело, вниз - легко
            if i > 0:
                resistance_factor = (0.0005 * i**2 + 0.06 * i + 1.25)
            else:
                resistance_factor = 0.2 # Катимся накатом
            
            # Расход = (База + Работа по перемещению веса) * Сопротивление
            work_load = (total_mass_ton * self.speed) / 200.0
            self.fuel_rate = base_consumption + (work_load * resistance_factor)
        else:
            self.fuel_rate = base_consumption + (10 if self.payload > 0 else 0)

        # 3. НАКОПЛЕНИЕ ЖЕЛЕЗА В МАСЛЕ (По статье Маслюкова)
        # Скорость накопления зависит от нагрузки (расхода топлива)
        # Нормальный расход ~80-100 л/ч. 
        load_intensity = self.fuel_rate / 100.0
        
        # Формула скорости накопления (мг/кг в час):
        # При агрессивной езде (load > 2.0) накопление идет экспоненциально
        iron_rate_per_hour = 0.05 * math.exp(1.2 * (load_intensity - 1))
        
        # Добавляем к общему значению
        step_hours = dt_seconds / 3600.0
        self.accumulated_iron += iron_rate_per_hour * step_hours
        self.total_engine_hours += step_hours
        
        # 4. Обновление бака
        self.fuel_level -= self.fuel_rate * step_hours

        # 5. Температура (инерция)
        target_temp = 80 + (self.fuel_rate / 10.0) 
        self.temp += (target_temp - self.temp) * 0.1

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
        # Q - нагрузка на одно колесо в тоннах
        q_wheel = (self.mass + self.payload) / 6.0 / 1000.0
        
        # Формула 2.15: t = 30.1 + 0.6*t_cp + 0.078 * Q * V
        # Используем self.speed
        calculated_temp = 30.1 + 0.6 * self.t_ambient + 0.078 * q_wheel * self.speed
        
        # Обновляем температуры (можно добавить чуть-чуть шума для реализма)
        self.wheel_temperature_rf = calculated_temp + random.uniform(-0.5, 0.5)
        self.wheel_temperature_lf = calculated_temp + random.uniform(-0.5, 0.5)
        self.wheel_temperature_rb = calculated_temp + random.uniform(-0.5, 0.5)
        self.wheel_temperature_lb = calculated_temp + random.uniform(-0.5, 0.5)


    def is_at(self, target):
        """Проверка достижения точки"""
        return abs(self.lat - target["lat"]) < 0.003 and abs(self.lon - target["lon"]) < 0.003