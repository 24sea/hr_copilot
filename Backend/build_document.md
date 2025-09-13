# HR Copilot — Build Document (Hackathon Submission)

## 1. Problem
HR tasks like leave management, employee lookup, and policy search are spread across multiple systems and require manual effort. This creates delays, reduces efficiency, and makes it hard for employees to quickly access HR services.

## 2. Solution Overview
HR Copilot is an AI-powered HR assistant that provides a single platform for employees and HR teams.  
It is built with FastAPI, Streamlit, and MongoDB, and integrates NLP using spaCy and HuggingFace Transformers.  

With HR Copilot, employees can:
- Look up employee information  
- Track leave balances  
- Apply for leave using both UI forms and natural language  
- View leave history  
- Search HR policies  
- Chat with an AI assistant for HR queries  

This improves speed, reduces manual errors, and creates a conversational HR experience.

## 3. Tech Stack
- **Backend:** FastAPI (`main.py`)  
- **Frontend:** Streamlit (`UI/streamlit_app.py`)  
- **Database:** MongoDB (handled in `db.py`)  
- **NLP:** HuggingFace Transformers, spaCy (`nlp_utils.py`)  
- **Language:** Python 3.11+  
- **Dependencies:** Listed in `requirements.txt`

## 4. Architecture
[User] → [Streamlit UI] → [FastAPI Backend] → [MongoDB]
↳ [NLP (spaCy + Transformers)]


- **Frontend (Streamlit):** Provides a simple and interactive user interface.  
- **Backend (FastAPI):** Handles all API calls for employee, leave, and policy management.  
- **Database (MongoDB):** Stores employee and leave data.  
- **NLP Layer:** Processes natural language leave requests and chatbot queries.  

## 5. How to Run Locally
1. Clone the repository:
   ```bash
   git clone https://github.com/<your-username>/hr_copilot.git
   cd hr_copilot
Create and activate a virtual environment:

bash
Copy code
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
uvicorn main:app --reload --host 0.0.0.0 --port 8000 

# Start frontend:
bash:
streamlit run UI/streamlit_app.py --server.port 8501

# Open in browser:- http://localhost:8501 🚀