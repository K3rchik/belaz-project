# -*- coding: utf-8 -*-
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
import uvicorn

load_dotenv()
app = FastAPI()

def get_db_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port="5432"
    )

@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("web/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/data")
def get_data():
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Берем здоровье узлов
    cur.execute("SELECT component_name, health_index, failure_probability FROM component_health ORDER BY id ASC")
    health = cur.fetchall()
    
    # 2. Берем последние замеры датчиков
    cur.execute("""
        SELECT DISTINCT ON (parameter_name) parameter_name, value 
        FROM telemetry ORDER BY parameter_name, time DESC
    """)
    telemetry = {r['parameter_name']: r['value'] for r in cur.fetchall()}
    
    cur.close()
    conn.close()
    return {"health": health, "telemetry": telemetry}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)