#!/bin/bash

echo "Iniciando Streamlit..."
streamlit run app.py --server.port $PORT --server.address 0.0.0.0 &

echo "Iniciando Telegram Bot..."
python bot.py
