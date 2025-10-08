# HR Copilot — Build Document

## 1. Problem
HR tasks like leave management, employee lookup, and policy search are spread across multiple systems and require manual effort.  
This creates delays, reduces efficiency, and makes it hard for employees to quickly access HR services.

---

## 2. Solution Overview
HR Copilot is an AI-powered HR assistant that provides a single platform for employees and HR teams.  
It is built with **FastAPI**, **Streamlit**, and **MongoDB**, and integrates **NLP** using **spaCy**, **HuggingFace Transformers**, and **DateParser**.

With HR Copilot, employees can:
- Look up employee information  
- Track leave balances  
- Apply for leave using both UI forms and natural language  
- View leave history  
- Search HR policies  
- Chat with an AI assistant for HR queries  

This improves speed, reduces manual errors, and creates a conversational HR experience.

---

## 3. Tech Stack
- **Backend:** FastAPI (`main.py`)  
- **Frontend:** Streamlit (`UI/streamlit_app.py`)  
- **Database:** MongoDB (handled in `db.py`)  
- **NLP / AI Libraries:**  
  - HuggingFace Transformers → intent detection  
  - spaCy → entity recognition  
  - DateParser → parse natural language dates (e.g., “next Monday”)  
  - Pandas → CSV cleaning and validation  
- **Language:** Python 3.11+  
- **Dependencies:** Listed in `requirements.txt`

---

## 4. Architecture
[User] → [Streamlit UI] → [FastAPI Backend] → [MongoDB]  
↳ [NLP Layer (spaCy + Transformers + DateParser)]

- **Frontend (Streamlit):** Provides a simple and interactive user interface.  
- **Backend (FastAPI):** Handles all API calls for employee, leave, and policy management.  
- **Database (MongoDB):** Stores employee and leave data.  
- **NLP Layer:** Processes natural language leave requests and chatbot queries.  

---

## 5. How to Run Locally
1. Clone the repository:
   ```bash
   git clone https://github.com/24sea/hr_copilot.git
   cd hr_copilot

# Create and activate a virtual environment:
bash:
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Install dependencies:
bash:
pip install -r requirements.txt


# Start backend:
bash:
uvicorn Backend.main:app --reload

# Start frontend:
bash:
streamlit run UI/streamlit_app.py --server.port 8501

# Open in browser:- http://localhost:8501 🚀


## Demo Video
follow the onedrive link for `demo_recording_.mp4` for a quick walkthrough of the app. [PATH : C:\CodeBase\hr_copilot\Hr_copilot_recording.mp4]

