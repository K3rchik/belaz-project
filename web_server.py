# -*- coding: utf-8 -*-
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            try:
                with open('web/index.html', 'rb') as f:
                    self.wfile.write(f.read())
            except FileNotFoundError:
                self.wfile.write(b"File not found. Please create web/index.html")

        elif self.path == '/api/data':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            data = self.get_data_from_db()
            self.wfile.write(json.dumps(data).encode('utf-8'))
        
        elif self.path.endswith('.glb'):
            # Раздача 3D модели
            try:
                path = os.path.join('web', self.path.lstrip('/'))
                with open(path, 'rb') as f:
                    self.send_response(200)
                    self.send_header('Content-type', 'model/gltf-binary')
                    self.end_headers()
                    self.wfile.write(f.read())
            except:
                self.send_error(404)
        else:
            self.send_error(404)

    def get_data_from_db(self):
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"), database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD")
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. Последняя телеметрия
        cur.execute("""
            SELECT DISTINCT ON (parameter_name) parameter_name, value
            FROM telemetry WHERE truck_id = 1
            ORDER BY parameter_name, time DESC;
        """)
        telemetry_rows = cur.fetchall()
        telemetry = {r['parameter_name']: r['value'] for r in telemetry_rows}

        # 2. Здоровье узлов
        cur.execute("""
            SELECT component_name, health_index, failure_probability 
            FROM component_health WHERE truck_id = 1;
        """)
        health_rows = cur.fetchall()
        health = {}
        for r in health_rows:
            # Маппинг имен из БД в ключи JSON
            key = "Engine" if "Engine" in r['component_name'] else "Frame"
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