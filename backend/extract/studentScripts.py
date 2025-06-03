


"""
professor_upload_handler.py (now studentScripts.py)

Handles BOTH professor upload modes:
1. One combined PDF for the whole class.
2. Multiple PDFs (one per student).

Updates the SAME document in `professoruploads`
to include a `students` array in the exact schema you requested.
Can be initialized with a specific professor_upload_id for targeted processing.
"""

import os
from datetime import datetime
from typing import List, Dict
import time
import argparse # For CLI argument parsing

from pdf2image import convert_from_path
from pymongo.errors import PyMongoError
from bson.objectid import ObjectId # <-- IMPORT THIS

# 👉 Your existing student-side implementation
from Answer_Generator import Student   # must be import-able


class ProfessorUploadHandler(Student):
    """
    Extends `Student` just to reuse its OCR helpers.
    We override __init__ so we DON'T run Student.load_exam_metadata()
    in the same way, and can target a specific professor upload document.
    """

    _CALL_LIMIT = 30
    _WINDOW_SEC = 60

    # ─────────────────────── set-up ─────────────────────── #

    def __init__(self, professor_upload_id: str | None = None): # <-- MODIFIED
        # Initialise Mongo + Groq clients from Student
        # The Student class's initialize_clients() sets up self.db
        self.initialize_clients()

        self._window_start = time.time()
        self._call_count = 0

        self.prof_col = self.db["professoruploads"] # self.db comes from Student.initialize_clients

        if professor_upload_id:
            print(f"Python (ProfessorUploadHandler): Initializing with specific ID: {professor_upload_id}")
            self.prof_doc = self.prof_col.find_one({"_id": ObjectId(professor_upload_id)})
        else:
            # Fallback for direct CLI testing without an ID or if API somehow doesn't pass it
            print("Python (ProfessorUploadHandler): No specific ID provided, fetching latest document.")
            self.prof_doc = self.prof_col.find_one(sort=[("uploadedAt", -1)])

        if not self.prof_doc:
            id_info = f"with ID '{professor_upload_id}'" if professor_upload_id else "as latest"
            raise RuntimeError(f"No professor upload document found {id_info} in DB.")
        
        print(f"Python (ProfessorUploadHandler): Processing document ID: {self.prof_doc['_id']}")

        # 1) list of script paths
        raw_paths = self.prof_doc.get("studentScriptPaths")
        if not raw_paths: # Can be an empty list, but not None/missing
            raise ValueError(f"Field `studentScriptPaths` is missing or empty in document {self.prof_doc['_id']}.")

        # Assuming paths are stored relative to project root, and CWD will be set to project root by API.
        # os.path.abspath() will then resolve them correctly from that CWD.
        self.script_paths = [os.path.abspath(p.replace("\\", "/")) for p in raw_paths]
        if not self.script_paths and isinstance(raw_paths, list): # If raw_paths was an empty list
             print(f"Python (ProfessorUploadHandler): Warning - studentScriptPaths is an empty list for doc {self.prof_doc['_id']}. No scripts to process.")
             # Depending on desired behavior, you might raise an error or allow proceeding
             # For now, it will proceed and likely result in "No student data extracted".

        # 2) exam-level metadata from the same document
        self.course_code = self.prof_doc.get("subjectCode")
        self.course_name = self.prof_doc.get("subject")
        self.exam_type   = self.prof_doc.get("examType")
        self.year        = str(self.prof_doc.get("year")) # Ensure year is string
        self.section     = self.prof_doc.get("sectionType")

        # Updated check to include self.section
        if not all([self.course_code, self.course_name, self.exam_type, self.year, self.section]):
            missing_fields = [
                f for f, v in {
                    "subjectCode": self.course_code, "subject": self.course_name,
                    "examType": self.exam_type, "year": self.year, "sectionType": self.section
                }.items() if not v
            ]
            raise ValueError(f"Exam metadata incomplete in doc {self.prof_doc['_id']}. Missing: {missing_fields}")

    # ─────────────────────── helpers ─────────────────────── #

    def extract_text_from_image(self, img, *args, **kwargs): # Content is identical to original
        now = time.time()
        if now - self._window_start >= self._WINDOW_SEC:
            self._window_start = now
            self._call_count   = 0
        if self._call_count >= self._CALL_LIMIT:
            wait = self._WINDOW_SEC - (now - self._window_start)
            if wait > 0:
                print(f"Groq API limit reached — sleeping {wait:.1f}s")
                time.sleep(wait)
            self._window_start = time.time()
            self._call_count   = 0
        self._call_count += 1
        return super().extract_text_from_image(img, *args, **kwargs)

    def _answers_schema(self, answers_raw: List[Dict]) -> List[Dict]: # Content is identical to original
        """Map Student.segment_answers → requested keys."""
        return [
            {
                "question_no":       a["question_id"],
                "answer_text":       a["answer_text"],
            }
            for a in answers_raw
        ]

    def _split_chunks(self, images: List) -> List[List]: # Content is identical to original
        """Split combined script into per-student page lists."""
        chunks, cur = [], []
        for img_idx, img in enumerate(images): # Added index for logging
            print(f"Python (ProfessorUploadHandler): Splitting chunks, processing image {img_idx + 1}/{len(images)}")
            txt = self.extract_text_from_image(img)
            if self.is_first_page(txt):
                if cur:
                    chunks.append(cur)
                cur = [img]
            else:
                cur.append(img)
        if cur:
            chunks.append(cur)
        return chunks

    # ─────────────────────── processing paths ─────────────────────── #

    def _process_single_pdf(self, pdf_path: str) -> Dict: # Content is mostly identical
        """Treat `pdf_path` as one student's entire script."""
        print(f"Python (ProfessorUploadHandler): Processing single PDF: {pdf_path}")
        # Ensure Poppler is configured if convert_from_path needs it explicitly on your system
        # poppler_path = r"C:\path\to\poppler\bin" # Example, if needed
        # images = convert_from_path(pdf_path, poppler_path=poppler_path)
        images = convert_from_path(pdf_path)
        if not images:
            raise RuntimeError(f"PDF-to-image failed: {pdf_path}")

        txt_first = self.extract_text_from_image(images[0])
        if self.is_first_page(txt_first):
            roll_no = self.extract_roll_number(images[0])
            answer_pages = images[1:] if len(images) > 1 else []
        else:
            roll_no = self.extract_roll_number(images[0])
            answer_pages = images

        if not answer_pages: # Handle case where only a header page exists
             print(f"Python (ProfessorUploadHandler): Warning - No answer pages found for {roll_no} in {pdf_path} (only header or empty).")
             answers = []
        else:
            combined = "\n".join(self.extract_text_from_image(p) for p in answer_pages)
            answers_raw = self.segment_answers(combined) # This might raise ValueError if no markers
            answers     = self._answers_schema(answers_raw)

        return {"roll_no": roll_no, "answers": answers}

    def _process_combined_pdf(self, pdf_path: str) -> List[Dict]: # Content is mostly identical
        """Split combined script & return students list."""
        print(f"Python (ProfessorUploadHandler): Processing combined PDF: {pdf_path}")
        # Ensure Poppler is configured if convert_from_path needs it explicitly on your system
        # poppler_path = r"C:\path\to\poppler\bin" # Example, if needed
        # images = convert_from_path(pdf_path, poppler_path=poppler_path)
        images = convert_from_path(pdf_path)
        if not images:
            raise RuntimeError(f"PDF-to-image failed: {pdf_path}")

        students = []
        chunks = self._split_chunks(images)
        if not chunks:
            print(f"Python (ProfessorUploadHandler): Warning - No student chunks identified in combined PDF: {pdf_path}")
            return []

        for i, chunk in enumerate(chunks):
            print(f"Python (ProfessorUploadHandler): Processing chunk {i+1}/{len(chunks)}")
            try:
                if not chunk: # Should not happen if _split_chunks is correct
                    print(f"Python (ProfessorUploadHandler):   ⚠ skipped empty chunk")
                    continue
                roll_no = self.extract_roll_number(chunk[0])
                
                answer_content_pages = chunk[1:]
                if not answer_content_pages:
                    print(f"Python (ProfessorUploadHandler): • {roll_no} | pages: {len(chunk)} | answers: 0 (no content pages after header)")
                    answers = []
                else:
                    combined = "\n".join(
                        self.extract_text_from_image(p) for p in answer_content_pages
                    )
                    answers_raw = self.segment_answers(combined) # This might raise ValueError
                    answers = self._answers_schema(answers_raw)
                
                students.append({"roll_no": roll_no, "answers": answers})
                print(f"Python (ProfessorUploadHandler): • {roll_no} | pages: {len(chunk)} | answers: {len(answers)}")
            except ValueError as ve: # Catch specific errors from segment_answers or roll_number
                 print(f"Python (ProfessorUploadHandler):   ⚠ skipped chunk due to ValueError: {ve}")
            except Exception as e:
                print(f"Python (ProfessorUploadHandler):   ⚠ skipped chunk due to unexpected error: {e}")
                # import traceback # For more detailed debugging if needed
                # traceback.print_exc()
        return students

    # ─────────────────────── public entry point ─────────────────────── #

    def run(self) -> None: # Content is identical to original, but now uses the targeted self.prof_doc
        """Main driver — decides mode & updates DB."""
        if not self.script_paths: # Check if script_paths ended up empty
            print(f"Python (ProfessorUploadHandler): No student script paths found or resolved for doc {self.prof_doc['_id']}. Aborting run.")
            # Not raising an error here, as an empty list is a valid state if no scripts were uploaded.
            # The update logic below will handle an empty students_payload.
            # If an error *should* be raised, do it in __init__ or here.
            students_payload = []
        elif len(self.script_paths) == 1:
            print(f"Python (ProfessorUploadHandler): 📝 Found 1 script path. Treating as ONE combined PDF for doc {self.prof_doc['_id']}.")
            students_payload = self._process_combined_pdf(self.script_paths[0])
        else:
            print(f"Python (ProfessorUploadHandler): 📝 Found {len(self.script_paths)} script paths. Treating as MANY PDFs for doc {self.prof_doc['_id']}.")
            students_payload = []
            for path_idx, path_val in enumerate(self.script_paths):
                print(f"Python (ProfessorUploadHandler):   → Processing PDF {path_idx+1}/{len(self.script_paths)}: {os.path.basename(path_val)}")
                try:
                    students_payload.append(self._process_single_pdf(path_val))
                except Exception as e:
                    print(f"Python (ProfessorUploadHandler):   ⚠ skipped {os.path.basename(path_val)}: {e}")

        if not students_payload:
            # This can happen if script_paths was empty or all PDFs failed processing.
            # The current script raises an error. For an API, you might want to handle this differently,
            # e.g., update the DB with an empty students array and a specific status.
            # For now, keeping original behavior:
            print(f"Python (ProfessorUploadHandler): No student data extracted for doc {self.prof_doc['_id']}. Aborting DB update for 'students' field.")
            # To avoid erroring out if no student data is found (e.g. professor uploaded empty/bad PDFs)
            # you could choose to update with an empty array and a specific status.
            # However, the original script raised an error, so let's keep it unless API needs a softer failure.
            # For API use, it's often better not to raise RuntimeError here but let the API decide how to respond.
            # Let's try to update with empty students array and let the API report success of operation,
            # but the data payload will show 0 students.
            #
            # If you want to strictly follow "raise RuntimeError" from original:
            # raise RuntimeError(f"No student data extracted for doc {self.prof_doc['_id']} — aborting update.")
            #
            # If allowing empty payload (more API friendly):
            print(f"Python (ProfessorUploadHandler): No student data extracted. Proceeding to update doc {self.prof_doc['_id']} with empty students list.")
            # students_payload remains an empty list

        # MongoDB update on the SAME professor document (self.prof_doc)
        try:
            update_fields = {
                "students": students_payload,
                "processedAt": datetime.utcnow()
            }
            if not students_payload:
                update_fields["status"] = "student_scripts_processed_nodata" # Example status

            result = self.prof_col.update_one(
                {"_id": self.prof_doc["_id"]},
                {"$set": update_fields},
            )
            if result.matched_count == 0:
                 print(f"Python (ProfessorUploadHandler): ⛔ MongoDB update failed: Document with ID {self.prof_doc['_id']} not found for update.")
            elif result.modified_count == 0 and result.matched_count == 1:
                 print(f"Python (ProfessorUploadHandler): 🤔 MongoDB: Document {self.prof_doc['_id']} found but not modified (data might be the same, or empty payload resulted in no change). Storing {len(students_payload)} students.")
            else:
                 print(f"Python (ProfessorUploadHandler): ✅ MongoDB updated for doc {self.prof_doc['_id']}: {len(students_payload)} students stored.")

        except PyMongoError as e:
            # For an API, raising RuntimeError might be too harsh. Log it.
            # The Flask API wrapper will catch this and return a 500.
            print(f"Python (ProfessorUploadHandler): ⛔ MongoDB write failed for doc {self.prof_doc['_id']}: {e}")
            raise # Re-raise for the API to catch and handle


# ─────────────────── CLI / quick test ─────────────────── #

if __name__ == "__main__":
    # For CLI execution, allow passing an ID or default to latest.
    parser = argparse.ArgumentParser(description="Process professor-uploaded student scripts.")
    parser.add_argument("--id", help="MongoDB ObjectId of the professor upload document to process.")
    cli_args = parser.parse_args()

    print(f"Python (studentScripts.py CLI): Running with ID: {cli_args.id if cli_args.id else 'Latest (default)'}")
    
    try:
        handler = ProfessorUploadHandler(professor_upload_id=cli_args.id)
        handler.run()
        print("Python (studentScripts.py CLI): Processing finished.")
    except Exception as e_main:
        print(f"Python (studentScripts.py CLI): CRITICAL ERROR - {e_main}")
        # import traceback # Uncomment for full traceback during CLI testing
        # traceback.print_exc()