# 🍽️ Wastewise: Hotel Food Waste Tracking & Forecasting

**An intelligent food waste management and consumption forecasting web application for large-scale hotels.**

## 📌 About the Project

Food waste is a significant challenge in the hospitality industry. Large hotels prepare meals for hundreds of guests daily, making accurate food preparation planning essential.

This project aims to develop an intelligent system that helps hotels:

- Monitor food preparation and consumption.
- Track and analyze food waste.
- Predict future food consumption using machine learning.
- Visualize historical food consumption trends.
- Improve kitchen planning and reduce unnecessary food waste.

The project uses large-scale hotels such as **The Kingsbury, Sri Lanka**, as a reference scenario for understanding real-world hotel operations.

## 🎯 Project Objectives

1. Develop a web-based food waste tracking platform.
2. Integrate a machine learning model to forecast food consumption.
3. Analyze historical food consumption and prediction accuracy.
4. Reduce manual data entry through future computer vision integration.
5. Support data-driven decisions in hotel food preparation.

## ✨ Features

### ✅ Implemented Features

**Food Waste Tracking**

- Record food preparation, consumption, and waste information.
- Organize data by food item and meal session.

**Machine Learning Prediction**

- Predict expected food consumption.
- Use a trained regression model.
- Integrate prediction functionality with the backend.

**Data Visualization**

- Display historical consumption information.
- Compare predicted and actual food consumption.
- Explore historical trends through interactive charts.

### 🚧 Planned Features

**Computer Vision Integration**

- Identify remaining food items automatically from images.
- Estimate remaining food quantities.
- Reduce manual food waste recording.

**Leftover Food Management**

- Track food reused in subsequent meal sessions.
- Distinguish reusable leftovers from discarded waste.

## 🛠️ Technologies Used

| Component        | Technology                  |
| ---------------- | --------------------------- |
| Frontend         | HTML, CSS, JavaScript       |
| Backend          | Python, FastAPI, Uvicorn  |
| Database         | SQLAlchemy (SQLite by default, PostgreSQL-ready) |
| Machine Learning | Python, Scikit-learn        |
| Trained Model    | Pickle (.pkl)               |
| Development      | VS Code, AI-assisted coding |
| Version Control  | Git, GitHub                 |

## 🏗️ System Architecture

The current application follows this general architecture:

```text
       Hotel Staff
            |
            v
    Web Application
   (HTML, CSS, JavaScript)
            |
            v
     FastAPI Backend
            |
            v
    Machine Learning Model
        (Python)
            |
            v
    Consumption Prediction
            |
            v
       Web Dashboard
```

The frontend provides the user interface, FastAPI handles backend requests, and the machine learning model generates food consumption predictions.

## 🤖 Machine Learning

The forecasting component uses supervised machine learning with a regression-based approach.

Potential prediction inputs include:

- Food item
- Meal type
- Number of guests
- Event type
- Historical food consumption

The objective is to estimate expected food demand and help kitchen staff prepare more appropriate quantities.

## 🚀 Getting Started

To run the project locally:

1. Clone this repository.
2. Open the project folder in VS Code.
3. Set up a Python virtual environment.
4. Install the required project dependencies.
5. Make sure the trained machine learning model is available.
6. Start the app with `python run.py`.
7. Open <http://127.0.0.1:5000/>.

On Windows PowerShell, create a virtual environment with `py -3.12 -m venv .venv`, install dependencies with `.venv\Scripts\python.exe -m pip install -r requirements.txt`, and run with `.venv\Scripts\python.exe run.py`. Initialize a new database with demo data with `.venv\Scripts\python.exe scripts/init_db.py --seed`.

The JSON APIs used by the React pages are documented, and can be tried out, at <http://127.0.0.1:5000/docs>.

## Food item counting (OWLv2)

Open <http://127.0.0.1:5000/food-counting> (**Food counting** in the sidebar). Drop, paste (Ctrl+V) or browse for a photo, type what to count, such as `cupcake`, `egg` or `bread roll`, and press **Count**. A numbered pin drops onto each item the model finds while the total and its tally build up. You can then:

- drag the **Minimum confidence** slider to see the count change instantly, without re-running the model;
- click any pin or list row to remove a wrong item from the count, and click again to restore it;
- hover a list row to highlight its item in the photo.

The page uses the open-vocabulary detector [`google/owlv2-base-patch16-ensemble`](https://huggingface.co/google/owlv2-base-patch16-ensemble) from Hugging Face Transformers (PyTorch). It finds objects from a text description, so it can count items without fine-tuning. Overlapping boxes on the same item are counted once. The first count downloads about 600 MB of model weights into the Hugging Face cache (`%USERPROFILE%\.cache\huggingface`). To run offline, save the model with `save_pretrained` and set `FOOD_COUNTER_MODEL_NAME` in the app config to that folder.

Counting works for separate items photographed from above. It does not work for loose food such as rice, curry or salad, and stacked or cut-off items may be miscounted. Uploaded photos and counts are not saved.

### React frontend

Three pages are React apps mounted inside the server-rendered layout. Their source is in [`frontend/src/`](frontend/src/), one folder per page:

| Page | Source | JSON API it calls |
|---|---|---|
| Meal forecast | `frontend/src/forecast/` | `POST /api/predict-meal`, `GET /api/forecast-history` |
| Food counting | `frontend/src/counting/` | `POST /api/food-count` |

The **Waste overview** is a Jinja template rendered by FastAPI. It combines the filters, totals, breakdowns and the full record table on one page; **Add waste record** and **Edit** open as a side panel over it. Old `/records` links redirect to the overview, and `/records/new` opens the overview with the add panel showing, so kitchen staff can bookmark it. All pages share the colours and layout in `app/static/styles.css`: white sheets hold what people enter, and dark pine panels hold what the system answers.

The built files are committed in `app/static/react/`, so `python run.py` works without Node.js. To change the React code, install [Node.js](https://nodejs.org/), then:

```powershell
cd frontend
npm install
npm run watch   # rebuilds app/static/react on every save; refresh the browser
```

Run `npm run build` once before committing so the committed files match the source.

To see the forecast history chart with sample data, run `python scripts/seed_demo_history.py`. It adds demo records, marked as demo data, to your real database (`instance/food_waste.sqlite3`); run it with `--remove` to take them out again.

Run tests with `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt` and `.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-run`.

## 🗄️ Database

The app uses SQLAlchemy, so it runs on the local SQLite file by default and on PostgreSQL by changing one setting. Large record lists are split into pages of 50, and the overview's totals are added up by the database.

| Setting | Default | Example |
|---|---|---|
| `DATABASE_URL` | `sqlite:///instance/food_waste.sqlite3` | `postgresql+psycopg://user:password@localhost/food_waste` |

To use PostgreSQL:

```powershell
.venv\Scripts\python.exe -m pip install "psycopg[binary]"
$env:DATABASE_URL = "postgresql+psycopg://user:password@localhost/food_waste"
.venv\Scripts\python.exe scripts/init_db.py --seed
.venv\Scripts\python.exe run.py
```

`scripts/init_db.py` only creates missing tables, so it is safe to run on an existing database. Existing SQLite files from the earlier Flask version work without changes.

## 🧭 Project map

Each backend feature has its own folder in `app/`, named after the page it serves. The React pages in `frontend/src/` use the same names.

```text
food-waste-tracking-system/
├── run.py                  Starts the web app (python run.py)
├── app/                    FastAPI backend
│   ├── __init__.py         create_app(): builds the app and includes each feature's routes
│   ├── config.py           Settings, such as DATABASE_URL
│   ├── web.py              Shared page helpers: templates, URLs, error pages, upload size limit
│   ├── database/           Tables (SQLAlchemy), connection, queries and demo seed data
│   ├── waste_records/      Waste overview page, and the Add and Edit record side panels
│   ├── forecast/           Meal forecast page, its JSON APIs and the forecast model loader
│   ├── vision/             Food counting page, shared upload checks
│   ├── templates/          HTML for the server-rendered pages and the shared layout
│   └── static/             styles.css for every page; react/ holds the built React pages
├── frontend/               React source for three pages (Node.js only needed to change them)
│   └── src/                forecast/, counting/ and shared/
├── ml_models/              Trained model files: forecast (.pkl); the unused Food-101 classifier (.keras) is kept
├── scripts/                init_db.py (create tables, demo data) and seed_demo_history.py
└── tests/                  pytest tests, one file per feature
```

Where to start:

- **Change a page's URL or add a page:** the `@router.get` / `@router.post` line above the view in its feature folder. A new feature's `router` is added to `ROUTERS` in `app/__init__.py`.
- **Change the waste overview or the record form:** `app/waste_records/` (`overview.py`, `add_record.py`, `edit_record.py`) and `app/templates/` (`overview.html`, `_record_panel.html`).
- **Change the forecast or counting page:** the Python view in `app/forecast/` or `app/vision/`, and the matching React folder in `frontend/src/`. Then run `npm run build` in `frontend/`.
- **Change colours or layout used everywhere:** `app/static/styles.css`.

## 🗺️ Development Roadmap

- [x] Identify the food waste management problem.
- [x] Design the initial web application.
- [x] Train a machine learning forecasting model.
- [x] Connect the machine learning model to the backend.
- [ ] Implement historical consumption charts.
- [ ] Add interactive chart functionality.
- [ ] Integrate automatic food recognition.
- [ ] Estimate remaining food quantities from images.
- [ ] Implement food reuse tracking.
- [ ] Test using realistic hotel operational scenarios.
- [ ] Improve the application's performance and reliability.

## 📚 Project Purpose

This project is developed as an educational and practical software engineering project to explore the application of machine learning, web development, and computer vision to a real-world industrial problem.

**Current Status:** Prototype under active development.

---

**Disclaimer:** This is an independent demonstration project and is not officially affiliated with The Kingsbury Hotel.
