# 🍽️ Wastewise: Hotel Food Waste Tracking & Forecasting

**A web application that helps large hotels record food waste, count buffet leftovers from photos, and forecast how much food to prepare.**

## 📌 About the Project

Large hotels prepare meals for hundreds of guests every day, so a small planning mistake becomes a lot of wasted food, or a buffet that runs empty. Wastewise gives kitchen staff one place to:

- Record food waste by hand, or by counting a buffet dish in photos taken at the start and end of a meal.
- See how much food was thrown away, where it came from and why, day by day.
- See the days when food **ran out**, shown separately from waste.
- Forecast how much of a dish to prepare for a meal, and check how close past forecasts were.

The project uses large-scale hotels such as **The Kingsbury, Sri Lanka**, as a reference scenario for real hotel operations. Dates and times in the app use Sri Lanka local time (UTC+5:30).

## 🔄 How it fits together

```text
  Staff add a record by hand ─────────────┐
                                          v
  Start photo + end photo ──> counted ──> Waste records ──> Waste overview, daily chart, day pages
  (buffet dish, e.g. 14 → 2 buns)   │                       (totals, breakdowns, by day)
                                    │
                                    └──> What was eaten + guests served ──> Meal forecast history
                                                                            (past forecasts vs actual)

  Meal + dish + expected guests ──> forecast model ──> how much to prepare
```

- **Leftovers become waste.** If 14 buns were put out and 2 are left, 2 buns × the weight of one bun is saved as a waste record.
- **What was eaten feeds the forecast.** The 12 buns eaten and the number of guests are stored, so the forecast page can compare what the model predicted with what really happened.
- **Running out is not waste.** If the food ran out, the missing kilograms are recorded as a shortage. Shortages are kept out of the waste totals and shown below zero on the daily chart.

## ✨ Features

### Waste overview (`/`)

- **Filters** for a date range, area and reason. One set of filters drives the totals, the chart, the breakdowns and the table.
- **Totals band:** total recorded, today, this week and this month (shortages are not counted as waste).
- **Waste each day, last 30 days:** a bar chart where bars above zero are kilograms thrown away and bars below zero are days the food ran out. It has a dashed 30-day average, summary figures (thrown away, daily average, highest day, days that ran out), a day-by-day detail box on hover, keyboard support, and a "Show as a table" view.
- **Where the waste comes from:** kilograms by area and by reason, with the largest highlighted.
- **Waste by day:** one row per day (thrown away, ran out, which of breakfast, lunch and dinner have records, number of records), newest first. It shows the newest 5 days with a **See 20 more days** button.
- **Add waste record / Edit** open as a side panel over the page. Each record has a date and time, a source area, a reason and a quantity in kilograms. Errors stay in the panel and keep what was typed.

### Day pages (`/days/<date>`)

Select a day to open its own page with:

- the day's totals: thrown away, ran out, number of records, and the meal with the most waste;
- three columns for **Breakfast, Lunch and Dinner**, each with its subtotal;
- every record with its time, whether it was **thrown away (+)** or **ran out (−)**, the area, the reason, who recorded it, and photo counts such as "Bread: 2 of 14 left";
- an Edit link on records you may edit, and **Previous day** / **Next day** buttons.

A record belongs to the meal saved with it (photo meal checks) or, for manual records, to the meal its time falls in: before 11:00 breakfast, before 16:00 lunch, otherwise dinner.

### Food counting and buffet meal checks (`/food-counting`)

Count a buffet dish in two photos, then save the result:

1. **Start-of-meal photo:** drop, paste (Ctrl+V) or browse for a photo, type what to count (`bread roll`, `cupcake`, `egg`…) and press **Count**. A numbered pin appears on every item found.
2. **End-of-meal photo:** the same, for what is left.
3. **Save the meal check:** the counts are filled in from the photos and can be corrected. Choose the meal and the dish, enter when the meal ended, the **weight of one piece** and the **guests served**, and pick the area and the reason for the leftovers. Tick **The food ran out** and say how many more pieces were needed if there was a shortage. A live summary shows what was eaten and what will be saved as waste.

Saving a meal check:

- adds a **waste record** for the leftovers (leftover pieces × weight per piece); nothing is added if nothing is left;
- adds a **Ran out (shortage)** record when the food ran out;
- stores the check, so what was eaten and the guest count feed the meal forecast history;
- opens that day's page with the new record highlighted.

The weight per piece is remembered for each dish, so staff only set it once.

In each photo you can lower or raise the **Minimum confidence** slider without re-running the model, click a pin or list row to remove a wrongly counted item (click again to bring it back), and hover a list row to highlight its item.

### Meal forecast (`/forecast`)

- Choose the **meal** (breakfast, lunch or dinner), the **dish** (17 dishes the model was trained on) and the **expected number of guests**. The page shows the **recommended quantity to prepare**, split into the predicted amount eaten and a 10% safety margin, plus the grams per guest, and it updates as you change the inputs.
- **How close past forecasts were:** for the 5 most recently served dishes, the model's prediction is compared with what was actually eaten:
  - figures for the average error in kg and in %, the days on target (within 10%) and whether the forecast leans too high or too low;
  - a smooth chart with the actual and predicted amounts for every day, the gap shaded, **green dots for on-target days** and **red dots for off days**, and a day-details box;
  - filters for **All meals / Breakfast / Lunch / Dinner** and for **All days / On target / Off days**;
  - a table view, newest day first.

### Across the app

- A consistent design: white sheets for what people enter, dark green panels for what the system answers, a tangerine accent, and colours checked to be readable by colour-blind users. The layout works on phones.
- Static files carry a version number, so browsers never show an outdated stylesheet after an update.
- Friendly error pages, and API errors returned as JSON.
- Interactive API documentation at `/docs`.

## 🌐 Pages and API

| Page | Address | What it is |
|---|---|---|
| Waste overview | `/` | Filters, totals, daily chart, breakdowns, waste by day (`/records` redirects here) |
| Add record | `/records/new` | Opens the overview with the add panel showing |
| Edit record | `/records/<id>/edit` | Opens the overview with the edit panel showing |
| Day page | `/days/<date>` | One day's records by meal |
| Meal forecast | `/forecast` | Forecast and past accuracy (React) |
| Food counting | `/food-counting` | Count photos and save meal checks (React) |
| API docs | `/docs` | Try the JSON APIs |

| JSON API | What it does |
|---|---|
| `POST /api/predict-meal` | Predicted consumption and recommended quantity for a meal, dish and guest count |
| `GET /api/forecast-history` | Past consumption compared with the model's forecast |
| `POST /api/food-count` | Counts one kind of item in an uploaded photo (nothing is stored) |
| `POST /api/meal-checks` | Saves a meal check: leftover and shortage records, plus what was eaten |

## 🛠️ Technologies Used

| Component | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn, Jinja2 templates |
| Database | SQLAlchemy 2, SQLite by default, PostgreSQL-ready |
| Frontend | Server-rendered HTML and CSS, plus React 19 built with Vite for the interactive pages and the daily chart |
| Forecast model | scikit-learn pipeline (one-hot encoding and linear regression), saved with joblib |
| Food counting model | [`google/owlv2-base-patch16-ensemble`](https://huggingface.co/google/owlv2-base-patch16-ensemble) with PyTorch and Hugging Face Transformers |
| Tests | pytest (44 tests) |
| Version control | Git, GitHub (`main` for stable work, `dev` for practice) |

## 🤖 Machine learning

**Meal forecast.** The model in `ml_models/food_demand_model.pkl` is a scikit-learn pipeline that takes three inputs: **meal type**, **food item** and **guest count**, and predicts the **quantity consumed**. The app adds a 10% safety margin to give the recommended quantity. The model is trained outside the app and is not retrained automatically from saved records; the records feed the accuracy view instead.

**Food counting.** OWLv2 is an open-vocabulary detector, so it finds items from a text description and needs no fine-tuning. Overlapping boxes on the same item are counted once, and a box inside a stronger box is treated as part of the same item.

- The first count downloads about 600 MB of model weights into the Hugging Face cache (`%USERPROFILE%\.cache\huggingface`). To run offline, save the model with `save_pretrained` and set `FOOD_COUNTER_MODEL_NAME` to that folder.
- Counting works for separate items photographed from above. It does not work for loose food such as rice, curry or salad, and stacked or cut-off items can be miscounted. The staff can correct any count before saving.
- Photos are not stored; only the counts are saved.

## 🚀 Getting Started

You need Python 3.12 or newer. Node.js is only needed if you change the React code.

```powershell
# 1. Create a virtual environment and install the dependencies
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Create the database with demo areas, reasons and a few demo records
.venv\Scripts\python.exe scripts/init_db.py --seed

# 3. Start the app
.venv\Scripts\python.exe run.py
```

Then open <http://127.0.0.1:5000/>. On macOS or Linux, use `python -m venv .venv` and `.venv/bin/python` instead.

- **The first start** needs `ml_models/food_demand_model.pkl`. Set `ML_MODEL_SKIP=1` to start without the forecast model.
- **No login:** this prototype has no sign-in. Everything is recorded as the demo kitchen staff user, and only that user's records can be edited.
- **Demo data:** `scripts/seed_demo_history.py` adds 30 days of demo records (a waste record for each of 5 dishes per day, some shortages, and the matching meal history) so the charts and forecast accuracy have something to show. It writes to your real database; run it with `--remove` to take the demo records out again.

### Run the tests

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-run
```

### Change the React pages

The built files are committed in `app/static/react/`, so `python run.py` works without Node.js. To change the React code:

```powershell
cd frontend
npm install
npm run watch   # rebuilds app/static/react on every save; refresh the browser
```

Run `npm run build` once before committing so the committed files match the source.

## 🗄️ Database

SQLAlchemy lets the app run on the local SQLite file by default, and on PostgreSQL by changing one setting.

| Table | Holds |
|---|---|
| `waste_records` | Every waste or shortage record: time (stored as UTC), area, reason, kilograms, who recorded it, notes |
| `meal_checks` | Buffet meal checks from photos: start and end pieces, weight per piece, guests, and the records they created |
| `areas`, `reasons` | The lists used in the forms and filters |
| `categories` | One hidden placeholder ("Whole waste"); records no longer have a food category, but older databases still require the column |
| `users` | Demo users with hashed passwords |

`meal_checks` is created automatically the first time it is needed, so older databases keep working. Existing SQLite files from the earlier Flask version work without changes.

### Settings

| Setting | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///instance/food_waste.sqlite3` | SQLAlchemy database URL |
| `ML_MODEL_SKIP` | not set | Set to `1` to start without loading the forecast model |
| `FOOD_COUNTER_MODEL_NAME` | `google/owlv2-base-patch16-ensemble` | Folder or Hugging Face name of the counting model |

To use PostgreSQL:

```powershell
.venv\Scripts\python.exe -m pip install "psycopg[binary]"
$env:DATABASE_URL = "postgresql+psycopg://user:password@localhost/food_waste"
.venv\Scripts\python.exe scripts/init_db.py --seed
.venv\Scripts\python.exe run.py
```

`scripts/init_db.py` only creates missing tables, so it is safe to run on an existing database. The PostgreSQL path has not yet been tested against a live server.

## 🧭 Project map

```text
food-waste-tracking-system/
├── run.py                  Starts the web app (python run.py)
├── app/                    FastAPI backend
│   ├── __init__.py         create_app(): builds the app and includes each feature's routes
│   ├── config.py           Settings, such as DATABASE_URL
│   ├── web.py              Shared page helpers: templates, URLs, error pages, upload size limit
│   ├── database/           Tables (SQLAlchemy), connection, queries and demo seed data
│   ├── waste_records/      Waste overview, day pages, and the Add and Edit record panels
│   ├── forecast/           Meal forecast page, its JSON APIs and the forecast model loader
│   ├── vision/             Food counting page, photo counting and meal-check saving, upload checks
│   ├── templates/          HTML for the server-rendered pages and the shared layout
│   └── static/             styles.css for every page; react/ holds the built React pages
├── frontend/               React source (Node.js only needed to change it)
│   └── src/                forecast/, counting/, daily/ and shared/
├── ml_models/              food_demand_model.pkl (forecast); an unused Food-101 classifier is kept
├── scripts/                init_db.py (create tables, demo data) and seed_demo_history.py
└── tests/                  pytest tests, one file per feature
```

Where to start:

- **Change a page's URL or add a page:** the `@router.get` / `@router.post` line above the view in its feature folder. A new feature's `router` is added to `ROUTERS` in `app/__init__.py`.
- **Change the overview, a day page or the record form:** `app/waste_records/` (`overview.py`, `add_record.py`, `edit_record.py`) and `app/templates/` (`overview.html`, `day.html`, `_record_panel.html`).
- **Change the forecast, counting or daily chart:** the Python view in `app/forecast/`, `app/vision/` or `app/waste_records/`, and the matching React folder in `frontend/src/`. Then run `npm run build` in `frontend/`.
- **Change colours or layout used everywhere:** `app/static/styles.css`.

## ⚠️ Limitations

- It is a local prototype: no login or roles, and one demo user records everything.
- Forecasts cover the 17 dishes and 3 meals the model was trained on.
- Counting needs a photo of separate items from above, and the weight per piece is entered by staff rather than measured from the photo.
- Photos are uploaded by hand. Automatic capture from buffet cameras is not built yet.
- The forecast model does not learn from the saved records automatically.

## 🗺️ Development Roadmap

- [x] Identify the food waste management problem.
- [x] Train a machine learning forecasting model and connect it to the backend.
- [x] Waste records with filters, totals, breakdowns and a 30-day chart.
- [x] Day-by-day pages with records grouped by meal.
- [x] Track shortages (food that ran out) separately from waste.
- [x] Count buffet leftovers from start and end photos.
- [x] Feed what was eaten back into the forecast accuracy charts.
- [x] Interactive forecast accuracy charts with on-target and off-day marking.
- [ ] Capture photos automatically from buffet cameras at set times.
- [ ] Estimate food weight directly from photos.
- [ ] Add login and roles for kitchen staff, supervisors and administrators.
- [ ] Track leftover food reused in later meals.
- [ ] Retrain the forecast model from saved records.
- [ ] Test with PostgreSQL and realistic hotel scenarios.

## 📚 Project Purpose

This project is developed as an educational and practical software engineering project to explore the application of machine learning, web development, and computer vision to a real-world industrial problem.

**Current Status:** Working prototype under active development.

---

**Disclaimer:** This is an independent demonstration project and is not officially affiliated with The Kingsbury Hotel.
