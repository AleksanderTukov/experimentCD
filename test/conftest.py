import os
import sys

# Корень проекта — это папка выше, чем test/
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Добавляем root_dir в sys.path, чтобы `from src.main import ...` работал
sys.path.insert(0, root_dir)
