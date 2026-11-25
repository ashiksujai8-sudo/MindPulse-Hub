# 🧠 MindPulse — Predicting Strain, Protecting Minds

An AI-powered student wellbeing web app that helps Grade 12 board exam students notice stress early and reduce it.

**Team Project Mind Guard** · Woodlem Park School, Dubai · CBSE Artificial Intelligence (Subject Code 843) · Class XII, 2026-27

| Member | Role |
|---|---|
| Ashik Sujai | Lead Developer |
| Ashfaq Kaliydan | Media Integrator |
| Adinath Sumesh | Data Specialist |
| Sushmitha Billakurthi | Project Tester |

**SDGs:** 3 (Good Health and Well-being) · 4 (Quality Education) · 10 (Reduced Inequalities)

---

## What it does

- **Stress Diagnostics:** set your study, sleep and screen hours and take an optional webcam snapshot. MindPulse combines both to give a 5-tier stress result (Highly Stressed → Fully Rested & Balanced) with advice.
- **AI Counselor:** chat naturally with Google Gemini, with our own offline NLP engine as an automatic fallback. Crisis messages always show the UAE Mental Support Line (800 HOPE).
- **Zen Arcade:** six short calming games (box breathing, memory, bubble pop, whack-a-stress, maze runner, daily word) that earn points toward a 100-point daily goal.
- **Eisenhower Priority Planner:** sort tasks by urgent and important.
- **Home Hub:** streaks, badges, a daily leaderboard and an interactive stress trend chart.
- **Examiner Portal:** a PIN-protected class overview with a CSV report. It never shows passwords or journal text.

## The AI inside

| AI type | What we used | Details |
|---|---|---|
| Machine Learning | Logistic Regression (Orange Data Mining + scikit-learn) | Trained on 200 synthetic student profiles; 5-fold cross-validation; accuracy 90.00%, F1 90.12%, AUC 0.970. Compared with Tree, Random Forest, kNN and Naive Bayes. |
| Computer Vision | DeepFace (pre-trained CNN), OpenCV fallback | Detects 7 facial emotions. The model was pre-trained by DeepFace's developers on the public FER-2013 dataset (35,887 face images). |
| NLP | Google Gemini API + our offline keyword engine | Open conversation online; whole-word intent matching offline. |

## Privacy and safety

- Passwords are stored as salted SHA-256 hashes, never as plain text.
- The camera is optional, and photos are analysed in memory and never saved.
- Chat is sent to Gemini only if the student switches it on.
- MindPulse supports wellbeing; it does not diagnose.

## How to run it

```
pip install -r requirements.txt
streamlit run mindpulse_app.py
```

Optional: place `student_stress_data.csv` or `.xlsx` next to the app to retrain the Logistic Regression model live inside the app. To use the full DeepFace emotion model, also run `pip install deepface tf-keras`; without it, the app uses OpenCV face and smile detection.

## Built with

Python · Streamlit · Orange Data Mining · scikit-learn · DeepFace · OpenCV · Google Gemini API · Plotly · ZenQuotes API
