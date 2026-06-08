# Family Driver Graph Scheduler

A smart scheduling assistant that pulls events from Google Calendar and automatically assigns drivers to events using constraint programming (OR-Tools CP-SAT) based on dynamic priorities, conflicts, and custom routing rules.

## Getting Started

Follow these steps to run the application locally on your machine:

1. **Activate the Virtual Environment**
   Ensure you are in the project root directory, then activate the Python virtual environment:
   ```powershell
   .\venv\Scripts\Activate
   ```

2. **Run the Server**
   Start the FastAPI backend server by running the main entry point:
   ```powershell
   python main.py
   ```
   *Note: This will start the server using Uvicorn on port 8000 with hot-reloading enabled.*

3. **Open the Application**
   Once the server is running, open your web browser and navigate to:
   [http://localhost:8000](http://localhost:8000)

   This will redirect you directly to the Dashboard.

## Configuration

If this is your first time running the app, make sure your `credentials.json` for the Google Calendar API is placed in the root directory. You can configure your Calendars, Drivers, and Rules via the **Config** page in the UI.