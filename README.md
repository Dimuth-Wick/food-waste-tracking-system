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
6. Start the FastAPI backend.
7. Open the frontend application.

*Exact installation commands will be added after the project setup is finalized.*

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
