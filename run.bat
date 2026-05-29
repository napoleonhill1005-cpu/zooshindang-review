@echo off
cd /d "C:\Users\USER\OneDrive\Desktop\review-digest\review-digest\review-digest"
set PYTHONIOENCODING=utf-8
set USE_MOCK=0
python main.py >> log.txt 2>&1
