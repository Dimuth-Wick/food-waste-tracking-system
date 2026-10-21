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

### Food counting and buffet cameras (`/food-counting`)

The buffet cameras photograph every meal by themselves, at its start and at its end (see [Automatic camera capture](#-automatic-camera-capture)). Every photo is checked for each food on the list, so nobody types what to count. The page shows:

- **Camera status:** each station's camera as OK or Offline, and a **Capture now** button (choose the meal, then **Start photos** or **End photos**) for testing.
- **One day's photos** (pick the date): grouped by meal, with each station's **start photos next to its end photos**. Each side shows what was found, such as "8 eggs, 3 donuts". With several photos, the start uses the **highest** count and the end the **lowest**. Click a photo to see it large with a box on every counted item.
- **Meal checks waiting for confirmation:** once a meal's start and end photos are counted, a draft appears with the pieces at the start, left at the end, eaten and saved as waste for each food. The camera cannot know how many people ate, so staff enter the **guests served**, correct any count (or add a food the camera missed, or pieces that ran short) and press **Confirm meal check**. Nothing is saved before that.
- **Foods the cameras look for:** the list (bread roll, egg, donut, cupcake, apple to start with), each with its menu dish and the **weight of one piece**, which turns leftover pieces into kilograms. Add, change or switch off foods here.

Confirming a meal check, for each food that was put out:

- adds a **waste record** for the leftovers (leftover pieces × weight per piece); nothing is added if nothing is left;
- adds a **Ran out (shortage)** record for pieces that ran short;
- stores what was eaten and the guest count, which feed the meal forecast history;
- shows on that day's page, for example "Cupcake: 3 of 6 left".

**Test the model with your own photos** (at the bottom of the page, to be removed later): upload a start and an end photo and type what to count. Nothing is saved; use it to see how well the model counts: move the **Minimum confidence** slider without re-running the model, click a pin or list row to remove a wrongly counted item, and hover a row to highlight its item.

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
| Sign in | `/login` | Manager sign-in (public); `POST /logout` signs out |
| Food counting | `/food-counting` | Camera photos by day and meal, counts, meal checks to confirm, the food list (React) |
| API docs | `/docs` | Try the JSON APIs |

| JSON API | What it does |
|---|---|
| `POST /api/predict-meal` | Predicted consumption and recommended quantity for a meal, dish and guest count |
| `GET /api/forecast-history` | Past consumption compared with the model's forecast |
| `POST /api/food-count` | Counts one kind of item in an uploaded photo (nothing is stored) |
| `POST /api/meal-checks` | Saves a meal check: leftover and shortage records, plus what was eaten |
| `POST /api/captures/run-now` | Takes the start or end photos of a meal now |
| `GET /api/captures` | One day's camera photos, counts and meal checks |
| `POST /api/captures/drafts/<id>/confirm` | Confirms a meal check counted from the cameras |
| `GET` / `PUT /api/camera-foods` | The foods the cameras look for, and their weights |

## 🛠️ Technologies Used

| Component | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn, Jinja2 templates |
| Database | SQLAlchemy 2, SQLite by default, PostgreSQL-ready |
| Frontend | Server-rendered HTML and CSS, plus React 19 built with Vite for the interactive pages and the daily chart |
| Forecast model | scikit-learn pipeline (one-hot encoding and linear regression), saved with joblib |
| Food counting model | [`google/owlv2-base-patch16-ensemble`](https://huggingface.co/google/owlv2-base-patch16-ensemble) with PyTorch and Hugging Face Transformers |
| Camera capture | OpenCV (reads the camera stream), APScheduler (meal times) |
| Tests | pytest (121 tests) |
| Version control | Git, GitHub (`main` for stable work, `dev` for practice) |

## 🤖 Machine learning

**Meal forecast.** The model in `ml_models/food_demand_model.pkl` is a scikit-learn pipeline that takes three inputs: **meal type**, **food item** and **guest count**, and predicts the **quantity consumed**. The app adds a 10% safety margin to give the recommended quantity. The model is trained outside the app and is not retrained automatically from saved records; the records feed the accuracy view instead.

**Food counting.** OWLv2 is an open-vocabulary detector, so it finds items from a text description and needs no fine-tuning (this is inference, not training). The cameras' photos are checked for every food on the list in one pass. Overlapping boxes on the same item are counted once, and an item that matches two foods is counted once, under the food it matches best. Large camera frames are shrunk for the model and the boxes are scaled back to the full photo. A food counts when the model is at least 30% sure.

- The first count downloads about 600 MB of model weights into the Hugging Face cache (`%USERPROFILE%\.cache\huggingface`). To run offline, save the model with `save_pretrained` and set `FOOD_COUNTER_MODEL_NAME` to that folder.
- Counting works for separate items photographed from above. It does not work for loose food such as rice, curry or salad, and stacked or cut-off items can be miscounted. The staff can correct any count before saving.
- **Camera photos are kept** on disk and in the database, with every box and score (including those under 30%) in the database and in a `.json` file next to each photo, so the captures folder can later become a labelled training dataset. Photos uploaded by hand for testing are not stored.

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
- **Sign-in:** managers and administrators sign in at `/login` (see [Signing in](#-signing-in)). Set a password for the demo manager first: `.venv\Scripts\python.exe scripts/set_password.py demo_manager --generate`.
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

## 📷 Automatic camera capture

The app photographs the buffet by itself at the start and end of each meal, counts the photos in the background and shows the results on the Food counting page for staff to confirm.

**1. Set the cameras.** Each camera is one buffet station. Camera addresses and passwords go in the `CAMERA_SOURCES` environment variable, never in the code: `name=address`, with several cameras separated by `;`.

```powershell
$env:CAMERA_SOURCES = "Station 1=http://192.168.8.144:8080/video"
# several stations, one with a password:
$env:CAMERA_SOURCES = "Station 1=http://192.168.8.144:8080/video;Station 2=rtsp://user:password@192.168.8.150/stream"
.venv\Scripts\python.exe run.py
```

A phone works as a test camera with an IP camera app (for example IP Webcam on Android): start its server and use the `/video` address it shows. The phone and this computer must be on the same Wi-Fi. A webcam plugged into this computer is `Station 1=0`. Without `CAMERA_SOURCES` there is no automatic capture, and the rest of the app works as usual.

**2. How many photos.** With several cameras, each capture takes one photo per camera. With one camera it takes `PHOTOS_PER_CAPTURE` photos (4), a few seconds apart. A camera that fails is tried twice more; the others carry on, and the failure shows on the page as Offline.

**3. Meal times.** The defaults are breakfast 06:00 to 10:00, lunch 12:00 to 14:30 and dinner 19:00 to 22:00, in `Asia/Colombo` time. Lunch and dinner are placeholders until the kitchen confirms them. Change them with `MEAL_SCHEDULE`:

```powershell
$env:MEAL_SCHEDULE = "breakfast=06:00/10:00;lunch=12:00/14:30;dinner=19:00/22:00"
```

The app must be running at those times: a capture more than 5 minutes late is skipped. When the app starts, the terminal lists the next time of each capture.

**4. Test without waiting for 6 a.m.** `CAPTURE_TEST_MODE` ignores the meal times and captures every 15 seconds, alternating start and end photos for the meal the clock is in:

```powershell
$env:CAMERA_SOURCES = "Station 1=http://192.168.8.144:8080/video"
$env:CAPTURE_TEST_MODE = "1"
.venv\Scripts\python.exe run.py
```

Or press **Start photos** / **End photos** on the Food counting page, or call `POST /api/captures/run-now` from <http://127.0.0.1:5000/docs>. Turn test mode off before real use: close the terminal, or run `Remove-Item Env:CAPTURE_TEST_MODE`.

**5. Where the photos go.** `instance\captures\<date>\<meal>\<start|end>\<station>_<HHMMSS>.jpg`, with the counts in a `.json` file next to each photo. The folder is ignored by git. Photos already in the folder when the app starts are picked up and counted.

**6. Counting.** Photos are counted one at a time in the background, so the pages and the schedule never wait. The model loads once, on the first photo, which takes about a minute; after that each photo takes some seconds. A station with no foods on its list shows "No foods set up" and nothing is counted.

## 🔐 Signing in

The app is for hotel **managers and administrators**. Everything except the sign-in page needs a sign-in. Visitors are sent to the **Manager sign in** page (`/login`) and come back to the page they asked for afterwards. The page has an animated picture of what Wastewise does (it stands still for people who ask their system for reduced motion) and a form with a show/hide password button, a Caps Lock warning, and clear messages.

- **Who can sign in:** users with the role `manager` or `admin`. Kitchen staff (`entry`) and switched-off accounts cannot. The top bar shows who is signed in and a **Sign out** button.
- **Records are saved in the signed-in manager's name**, and managers can edit anyone's records.
- **How long it lasts:** 8 hours, or 30 days with **Keep me signed in** (`SESSION_HOURS`, `REMEMBER_DAYS`). Changing a user's password, or switching the account off, signs them out at once.
- **Guessing is slowed down:** after 5 wrong passwords (`LOGIN_MAX_ATTEMPTS`) that username is locked for 15 minutes (`LOGIN_LOCK_MINUTES`), and one address cannot try many usernames in a row. The error never says whether the username or the password was wrong, and a wrong username takes as long to answer as a wrong password. The lock is kept in memory, so it starts again if the app restarts.
- **The cookie** is signed with `SECRET_KEY` (created once in `instance/secret_key` if you do not set one), is HttpOnly and SameSite=Lax, and holds only a user number, an end time and a password fingerprint. Pages are sent with `Cache-Control: no-store`, so Back after signing out does not show them again. The sign-in cookie is not marked Secure because the app runs on `http://127.0.0.1`; behind HTTPS, put it behind a proxy that does TLS.
- **Turn it off** for local experiments with `REQUIRE_LOGIN=0`: no sign-in is needed and everything is recorded as the demo kitchen user, as before.

**Give someone a password, or add a manager:**

```powershell
# a new password for an existing user (asks you to type it twice)
.venv\Scripts\python.exe scripts/set_password.py demo_manager
# make one up and print it once
.venv\Scripts\python.exe scripts/set_password.py demo_manager --generate
# add a manager (or --role admin)
.venv\Scripts\python.exe scripts/set_password.py anna --create --name "Anna Perera" --role manager
```

Passwords need at least 8 characters and are stored only as hashes. The demo users made by `scripts/init_db.py --seed` (`demo_manager`, `demo_admin`) print one-time passwords when they are created.

## 🗄️ Database

SQLAlchemy lets the app run on the local SQLite file by default, and on PostgreSQL by changing one setting.

| Table | Holds |
|---|---|
| `waste_records` | Every waste or shortage record: time (stored as UTC), area, reason, kilograms, who recorded it, notes |
| `meal_checks` | Buffet meal checks from photos: start and end pieces, weight per piece, guests, and the records they created |
| `captures` | Every camera photo, or failed attempt: when, meal, start or end, station, file, and how far its counting got |
| `capture_counts` | How many of each food the model found in each photo, with its boxes and scores |
| `camera_foods` | The foods the cameras look for, their menu dish and the weight of one piece |
| `meal_check_drafts` | Meals whose start and end photos are counted, waiting for staff to confirm |
| `areas`, `reasons` | The lists used in the forms and filters |
| `categories` | One hidden placeholder ("Whole waste"); records no longer have a food category, but older databases still require the column |
| `users` | Demo users with hashed passwords |

`meal_checks` and the camera tables are created automatically the first time they are needed, so older databases keep working. Existing SQLite files from the earlier Flask version work without changes.

### Settings

| Setting | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///instance/food_waste.sqlite3` | SQLAlchemy database URL |
| `ML_MODEL_SKIP` | not set | Set to `1` to start without loading the forecast model |
| `FOOD_COUNTER_MODEL_NAME` | `google/owlv2-base-patch16-ensemble` | Folder or Hugging Face name of the counting model |
| `CAMERA_SOURCES` | not set | The buffet cameras, `Station 1=http://...;Station 2=rtsp://...` |
| `MEAL_SCHEDULE` | `breakfast=06:00/10:00;lunch=12:00/14:30;dinner=19:00/22:00` | When start and end photos are taken |
| `TIMEZONE` | `Asia/Colombo` | Time zone of the meal schedule |
| `PHOTOS_PER_CAPTURE` | `4` | Photos per capture when there is one camera |
| `CAPTURE_TEST_MODE` | not set | `1` captures every 15 seconds (`CAPTURE_TEST_SECONDS`) instead of at meal times |
| `CAPTURE_DIR` | `instance/captures` | Where camera photos are saved |
| `REQUIRE_LOGIN` | on | `0` turns the sign-in off |
| `SECRET_KEY` | created in `instance/secret_key` | Signs the sign-in cookie |
| `SESSION_HOURS` / `REMEMBER_DAYS` | `8` / `30` | How long a sign-in lasts |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCK_MINUTES` | `5` / `15` | Wrong passwords allowed, and how long the lock lasts |

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
│   ├── camera/             Camera capture: taking photos, schedule, background counting, pairing, APIs
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

- It is a local prototype: sign-in is for managers and administrators only, there is no password reset page (use `scripts/set_password.py`), and the sign-in cookie is not marked Secure.
- Forecasts cover the 17 dishes and 3 meals the model was trained on.
- Counting needs a photo of separate items from above, and the weight per piece is entered by staff rather than measured from the photo.
- The cameras only find foods on the list; the counting model cannot name a food it was not told about.
- The camera cannot count guests, so staff confirm each meal check with the guest count.
- The app must be running at meal times for the automatic captures.
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
- [x] Capture photos automatically from buffet cameras at set times.
- [ ] Fine-tune the counting model with the saved camera photos.
- [ ] Estimate food weight directly from photos.
- [x] Manager sign-in with sessions, password protection and an animated sign-in page.
- [ ] Roles for kitchen staff (limited access), a password-reset page and per-user audit history.
- [ ] Track leftover food reused in later meals.
- [ ] Retrain the forecast model from saved records.
- [ ] Test with PostgreSQL and realistic hotel scenarios.

## 📚 Project Purpose

This project is developed as an educational and practical software engineering project to explore the application of machine learning, web development, and computer vision to a real-world industrial problem.

**Current Status:** Working prototype under active development.

---

**Disclaimer:** This is an independent demonstration project and is not officially affiliated with The Kingsbury Hotel.
