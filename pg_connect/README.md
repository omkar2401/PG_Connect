# PG Connect — PG Finder & Booking MVP

A local Flask + SQLite web app for students and working professionals to discover PG accommodation, compare rent/facilities/commute, inspect floor/room/bed availability, and send booking requests. Owners can manage listings and update bed counts.

## Features
- Student/employee and PG-owner registration/login with hashed passwords.
- Search by city, area, rent, room type, facility, destination/landmark, commute time, and minimum available beds.
- PG details with floor, room number, room type, total beds, and available beds.
- Owner dashboard to publish PGs, add rooms, update availability, and approve/reject booking requests.
- Demo listings are seeded automatically on first run.

## Run on Windows
1. Install Python 3.10 or newer from https://www.python.org/downloads/ and select **Add Python to PATH**.
2. Extract this ZIP.
3. Open Command Prompt/Terminal in the extracted `pg_connect` folder.
4. Create and activate a virtual environment (recommended):
   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   ```
5. Install dependencies:
   ```bat
   pip install -r requirements.txt
   ```
6. Run:
   ```bat
   python app.py
   ```
7. Open http://127.0.0.1:5000 in your browser.

## Demo accounts
- Owner: `owner@example.com` / `Owner@123`
- Student: `student@example.com` / `Student@123`

Register your own account to test the flow. Demo accounts are only for local development.

## Database
The SQLite database `pg_connect.db` is created automatically on first run. To reset demo data, stop the app and delete `pg_connect.db`; it will be recreated on next launch.

## Before production
This is an MVP, not a production-ready booking/payment service. Before public deployment:
- Set a strong random `SECRET_KEY` environment variable.
- Turn off Flask debug mode and use a production WSGI server.
- Add CSRF protection, rate limiting, email/phone verification, password reset, logging, backups, and security headers.
- Add photo upload/storage with file validation rather than accepting arbitrary image URLs.
- Add proper booking state transitions, expiry, concurrency-safe bed reservation, cancellation, and owner verification.
- Add map/geocoding integration for real distance/route calculations. The current commute filter uses owner-entered estimated minutes; it does not calculate actual travel time.
- Publish privacy terms and protect user contact details. Do not store payment card data.
