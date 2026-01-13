# -*- coding: utf-8 -*-
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

@app.get("/", response_class=HTMLResponse)
def read_root():
    # Читаем файл index.html и отдаем его пользователю
    with open("web/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/status")
def get_status():
    """Этот путь Виктория будет использовать для получения данных"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Берем последнее здоровье БелАЗа
    cur.execute("SELECT health_index FROM component_health WHERE truck_id = 1")
    health = cur.fetchone()
    
    cur.close()
    conn.close()
    return health