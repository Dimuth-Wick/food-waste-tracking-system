# 🍽️ Hotel Food Waste Tracking & Forecasting System

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
| Backend          | Python, Flask             |
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
      Flask Backend
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
6. Start the Flask app with `python run.py`.
7. Open <http://127.0.0.1:5000/>.

On Windows PowerShell, create a virtual environment with `py -3.12 -m venv .venv`, install dependencies with `.venv\Scripts\python.exe -m pip install -r requirements.txt`, and run with `.venv\Scripts\python.exe run.py`. Initialize a new database with `.venv\Scripts\python.exe -m flask --app run init-db --seed`.

## Temporary Food-101 image prediction

Open <http://127.0.0.1:5000/food-prediction> and upload one food image (up to 8 MB). The page displays the three most likely Food-101 labels and their model confidence. The supplied `models/food101_mobilenetv2.keras` is loaded on the first prediction. The existing forecasting model and waste-record pages continue to use their existing routes.

Inference uses RGB pixels, `tf.image.resize(image, (224, 224))`, and `tf.keras.applications.mobilenet_v2.preprocess_input`, matching the training code. `app/food101_labels.txt` contains the ordered class names from TensorFlow Datasets' Food-101 label file. This model classifies the whole image among 101 foods; it does not locate multiple items, read CCTV, or estimate kilograms. Uploaded images and predictions are not saved to the database.

## Food item counting (OWLv2)

Open <http://127.0.0.1:5000/food-detection> (**Food counting** in the sidebar). Drop, paste (Ctrl+V) or browse for a photo, type what to count, such as `cupcake`, `egg` or `bread roll`, and press **Count**. A numbered pin drops onto each item the model finds while the total and its tally build up. You can then:

- drag the **Minimum confidence** slider to see the count change instantly, without re-running the model;
- click any pin or list row to remove a wrong item from the count, and click again to restore it;
- hover a list row to highlight its item in the photo.

The page uses the open-vocabulary detector [`google/owlv2-base-patch16-ensemble`](https://huggingface.co/google/owlv2-base-patch16-ensemble) from Hugging Face Transformers (PyTorch). It finds objects from a text description, so it can count items without fine-tuning. Overlapping boxes on the same item are counted once. The first count downloads about 600 MB of model weights into the Hugging Face cache (`%USERPROFILE%\.cache\huggingface`). To run offline, save the model with `save_pretrained` and set `FOOD_DETECTOR_MODEL_NAME` in the app config to that folder.

Counting works for separate items photographed from above. It does not work for loose food such as rice, curry or salad, and stacked or cut-off items may be miscounted. Uploaded photos and counts are not saved.

### React frontend

The Food counting page is a React app in [`frontend/`](frontend/), mounted inside the Flask layout. It calls `POST /api/food-count` (multipart `image` and `item`), which returns every match at 20% confidence or more with its box in pixels. The built bundle is committed in `app/static/food-counter/`, so `python run.py` works without Node.js. To change the React code, install [Node.js](https://nodejs.org/), then:

```powershell
cd frontend
npm install
npm run watch   # rebuilds app/static/food-counter on every save; refresh the browser
```

Run `npm run build` once before committing so the committed bundle matches the source.

Run tests with `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt` and `.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-run`.

## 🗺️ Development Roadmap

- [x] Identify the food waste management problem.
- [x] Design the initial web application.
- [x] Train a machine learning forecasting model.
- [x] Connect the machine learning model to Flask.
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
