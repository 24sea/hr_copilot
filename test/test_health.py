# test.py
import requests

BASE_URL = "http://127.0.0.1:8000"

def test_health():
    r = requests.get(f"{BASE_URL}/")
    print("Health:", r.status_code, r.json())

def test_employees():
    r = requests.get(f"{BASE_URL}/employees")
    print("Employees:", r.status_code, r.json())

def test_employee(emp_id="10001"):
    r = requests.get(f"{BASE_URL}/employee/{emp_id}")
    print(f"Employee {emp_id}:", r.status_code, r.json())

def test_leave_balance(emp_id="10001"):
    r = requests.get(f"{BASE_URL}/leave-balance/{emp_id}")
    print(f"Leave Balance {emp_id}:", r.status_code, r.json())

def test_apply_leave(emp_id="10001"):
    payload = {
        "emp_id": emp_id,
        "leave_type": "casual",
        "from_date": "2025-09-10",
        "to_date": "2025-09-10",
        "reason": "Vacation"
    }
    r = requests.post(f"{BASE_URL}/apply-leave", json=payload)
    print("Apply Leave:", r.status_code, r.json())

def test_leave_history(emp_id="10001"):
    r = requests.get(f"{BASE_URL}/leave-history/{emp_id}")
    print(f"Leave History {emp_id}:", r.status_code, r.json())

if __name__ == "__main__":
    test_health()
    test_employees()
    test_employee()
    test_leave_balance()
    test_apply_leave()
    test_leave_history()
