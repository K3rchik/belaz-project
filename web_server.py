# -*- coding: utf-8 -*-
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
from datetime import datetime # Добавлено для record_time

load_dotenv()

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/upload_route':
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self.send_error(400, "Empty payload")
                return

            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                
                # Подключаемся к базе (сохрани функцию save_route_to_db из прошлого примера)
                self.save_route_to_db(data)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "message": f"Saved {len(data)} points"}).encode('utf-8'))
                
            except Exception as e:
                print(f"Ошибка при сохранении маршрута: {e}")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        else:
            self.send_error(404)

    # --- НОВЫЙ БЛОК: Обработка POST-запросов от Unity ---
    def do_POST(self):
        if self.path == '/api/upload_route':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                # Декодируем JSON, присланный Андреем
                data = json.loads(post_data.decode('utf-8'))
                
                # Отправляем в базу
                self.save_route_to_db(data)
                
                # Отвечаем Unity "всё ок"
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "message": f"Saved {len(data)} points"}).encode('utf-8'))
                
            except Exception as e:
                print(f"Ошибка при сохранении маршрута: {e}")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        else:
            self.send_error(404)

    # --- НОВЫЙ БЛОК: Запись маршрута в БД ---
    def save_route_to_db(self, track_data):
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"), database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD")
        )
        cur = conn.cursor()
        
        # ВАЖНО: Замени 'route_data' на реальное имя твоей таблицы!
        table_name = "track_data" 
        
        # Очищаем таблицу перед новой записью маршрута (если нужно)
        cur.execute(f"TRUNCATE TABLE {table_name};") 
        
        now = datetime.now()
        
        # Подготавливаем данные для быстрой пакетной вставки (executemany)
        # Ожидаем, что Андрей пришлет список словарей (массив объектов в JSON)
        records_to_insert = [
            (point.get('distance', 0), point.get('speed', 0), 
             point.get('incline', 0), point.get('turn_radius', 9999), now)
            for point in track_data
        ]

        # Записываем в базу (ID сгенерируется сам, если он SERIAL)
        cur.executemany(f"""
            INSERT INTO {table_name} (distance, speed, incline, turn_radius, record_time)
            VALUES (%s, %s, %s, %s, %s)
        """, records_to_insert)
            
        conn.commit()
        cur.close()
        conn.close()

    def get_data_from_db(self):
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"), database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD")
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT DISTINCT ON (parameter_name) parameter_name, value
            FROM telemetry WHERE truck_id = 1
            ORDER BY parameter_name, time DESC;
        """)
        telemetry = {r['parameter_name']: r['value'] for r in cur.fetchall()}

        cur.execute("""
            SELECT component_name, health_index, failure_probability 
            FROM component_health WHERE truck_id = 1;
        """)
        health_rows = cur.fetchall()
        health = {}
        for r in health_rows:
            name = r['component_name']
            if "Engine" in name: key = "Engine"
            elif "Frame" in name: key = "Frame"
            else: key = name 
                
            health[key] = {
                'health_index': r['health_index'],
                'failure_probability': r['failure_probability']
            }

        cur.close()
        conn.close()
        return {"telemetry": telemetry, "health": health}

def run(server_class=HTTPServer, handler_class=RequestHandler, port=8000):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f'Starting server on port {port}...')
    httpd.serve_forever()

if __name__ == '__main__':
    run()