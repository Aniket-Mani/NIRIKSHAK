



# python_api.py

from flask import Flask, request, jsonify
from flask_cors import CORS # Import Flask-CORS
import os
import sys
import traceback # For detailed error logging

# --- Import Student Class (for /process-student-upload) ---
try:
    from Answer_Generator import Student 
except ImportError as e_student:
    print(f"Python Error (python_api): Could not import Student from Answer_Generator.py: {e_student}. Ensure the file exists and is in the Python path.", file=sys.stderr)
    # Define a dummy class if import fails, so the Flask app can still start (though endpoint will fail)
    class Student: 
        def __init__(self, student_upload_id=None):
            self.student_upload_id = student_upload_id
            print("Python (python_api): WARNING - Using DUMMY Student class due to import error for /process-student-upload.", file=sys.stderr)
        def process(self):
            print(f"Python (python_api): DUMMY Student.process called for {self.student_upload_id}. Does nothing.", file=sys.stderr)
            return False # Simulate failure

# --- Import ProfessorUploadHandler Class (for /process-professor-scripts) ---
try:
    # Assuming studentScripts.py is in the same directory (backend/extract/)
    # or accessible via Python path. This is where ProfessorUploadHandler is defined.
    from studentScripts import ProfessorUploadHandler 
except ImportError as e_prof:
    print(f"Python Error (python_api): Could not import ProfessorUploadHandler from studentScripts.py: {e_prof}. Ensure the file exists and is in the Python path.", file=sys.stderr)
    class ProfessorUploadHandler: # Dummy class
        def __init__(self, professor_upload_id=None): # Match modified signature if you adapted it
            self.professor_upload_id = professor_upload_id
            print("Python (python_api): WARNING - Using DUMMY ProfessorUploadHandler class due to import error for /process-professor-scripts.", file=sys.stderr)
        def run(self): # ProfessorUploadHandler has a 'run' method
            print(f"Python (python_api): DUMMY ProfessorUploadHandler.run called for {self.professor_upload_id}. Does nothing.", file=sys.stderr)
            return # run() method in original script doesn't return a boolean for success


app = Flask(__name__)
CORS(app) # Enable CORS for all routes on this Flask app.

# ==============================================================================
# EXISTING ENDPOINT for Student Answer Script Processing
# This endpoint's functionality is RETAINED AS IS.
# ==============================================================================
@app.route('/process-student-upload', methods=['POST']) 
def process_student_upload_endpoint(): 
    print("Python (python_api): Received request for /process-student-upload", file=sys.stderr)
    try:
        data = request.get_json()
        if not data:
            print("Python Error (python_api): No JSON data received for /process-student-upload.", file=sys.stderr)
            return jsonify({"status": "error", "message": "Request body must be JSON."}), 400

        student_upload_id = data.get('studentUploadId') 

        if not student_upload_id:
            print("Python Error (python_api): studentUploadId is missing from /process-student-upload request.", file=sys.stderr)
            return jsonify({"status": "error", "message": "studentUploadId is required."}), 400

        # Set CWD for Answer_Generator.py (Student class) if it relies on relative paths from project root
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')) 
        original_cwd = os.getcwd()
        os.chdir(project_root)
        print(f"Python (python_api): CWD for Student.process set to: {os.getcwd()}", file=sys.stderr)

        success = False # Student.process() returns a boolean
        try:
            student_processor = Student(student_upload_id=student_upload_id) 
            success = student_processor.process() 
        except Exception as e_process:
            print(f"Python Error (python_api): Error during Student.process() for ID {student_upload_id}: {e_process}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            success = False # Ensure success is false on exception
        finally:
            os.chdir(original_cwd) 
            print(f"Python (python_api): CWD for Student.process restored to: {os.getcwd()}", file=sys.stderr)

        if success:
            print(f"Python (python_api): Successfully processed student upload ID: {student_upload_id}")
            return jsonify({"status": "success", "message": "Student script processed successfully."}), 200 
        else:
            print(f"Python Error (python_api): Failed to process student upload ID: {student_upload_id}", file=sys.stderr)
            return jsonify({"status": "failed", "message": "Student script processing failed by Student.process(). Check Python API logs."}), 500 

    except Exception as e: # Catch any other unexpected errors in the endpoint logic
        print(f"Python CRITICAL Error (python_api): Unexpected error in /process-student-upload: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return jsonify({"status": "error", "message": f"Internal server error in API: {str(e)}"}), 500 

# ==============================================================================
# NEW ENDPOINT for Professor-Uploaded Scripts Processing
# ==============================================================================
@app.route('/process-professor-scripts', methods=['POST'])
def process_professor_scripts_endpoint():
    print("Python (python_api): Received request for /process-professor-scripts", file=sys.stderr)
    try:
        data = request.get_json()
        if not data:
            print("Python Error (python_api): No JSON data received for /process-professor-scripts.", file=sys.stderr)
            return jsonify({"status": "error", "message": "Request body must be JSON."}), 400

        professor_upload_id = data.get('professorUploadId') 

        if not professor_upload_id:
            print("Python Error (python_api): professorUploadId is missing from /process-professor-scripts request.", file=sys.stderr)
            return jsonify({"status": "error", "message": "professorUploadId is required."}), 400

        # Set CWD for studentScripts.py (ProfessorUploadHandler) if it relies on relative paths
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        original_cwd = os.getcwd()
        os.chdir(project_root)
        print(f"Python (python_api): CWD for ProfessorUploadHandler.run set to: {os.getcwd()}", file=sys.stderr)

        # ProfessorUploadHandler.run() does not return a boolean; it raises exceptions on failure.
        # We'll assume success if no exception is caught here from handler.run().
        api_call_successful = False
        try:
            # Ensure ProfessorUploadHandler.__init__ is adapted to take professor_upload_id
            handler = ProfessorUploadHandler(professor_upload_id=professor_upload_id)
            handler.run() 
            api_call_successful = True # If run() completes without raising an error caught here
            print(f"Python (python_api): ProfessorUploadHandler.run() completed for ID {professor_upload_id}")

        except Exception as e_process: # Catch errors from ProfessorUploadHandler instantiation or run()
            print(f"Python Error (python_api): Error during ProfessorUploadHandler.run() for ID {professor_upload_id}: {e_process}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            api_call_successful = False # Explicitly mark as failed
        finally:
            os.chdir(original_cwd)
            print(f"Python (python_api): CWD for ProfessorUploadHandler.run restored to: {os.getcwd()}", file=sys.stderr)

        if api_call_successful:
            print(f"Python (python_api): Successfully initiated/completed processing for professor upload ID: {professor_upload_id}")
            # The Python script itself updates the DB. Node.js might poll or get status separately.
            return jsonify({"status": "success", "message": "Professor scripts processing initiated/completed successfully via API."}), 200
        else:
            print(f"Python Error (python_api): Failed to process professor upload ID: {professor_upload_id} due to error in ProfessorUploadHandler.", file=sys.stderr)
            return jsonify({"status": "failed", "message": "Professor scripts processing failed by ProfessorUploadHandler.run(). Check Python API logs."}), 500

    except Exception as e: # Catch any other unexpected errors in the endpoint logic
        print(f"Python CRITICAL Error (python_api): Unexpected error in /process-professor-scripts: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return jsonify({"status": "error", "message": f"Internal server error in API: {str(e)}"}), 500

# ==============================================================================
# Main execution block for Flask app
# ==============================================================================
if __name__ == '__main__':
    port_num = 6001 
    print(f"Python (python_api): Starting Flask API server with Student and Professor endpoints on http://localhost:{port_num}", file=sys.stderr) 
    app.run(port=port_num, debug=False) # Set debug=True for development for auto-reloading