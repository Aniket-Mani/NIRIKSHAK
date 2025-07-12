import os
import re
import json
import base64
from io import BytesIO
from typing import Dict, List
from pdf2image import convert_from_path
from groq import Groq
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from PIL import Image
from bson.objectid import ObjectId
from datetime import datetime
import time
from dotenv import load_dotenv
from groq import Groq



# ───────────────────────── Configuration ───────────────────────── #
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../.env'))
load_dotenv(dotenv_path=env_path)


KEYWORD_THRESHOLD = 4
MONGO_CONNECTION_STRING = os.getenv("MONGO_CONNECTION_STRING", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("MONGO_DB_NAME", "smart")
COLLECTION_NAME = "studentuploads"
GROQ_API_KEY_OCR  = os.getenv("GROQ_API_KEY_OCR")
GROQ_API_KEY_ROLL = os.getenv("GROQ_API_KEY_ROLL")
# ────────────────────────────────────────────────────────────────── #

class Student:
    """
    Process a student-uploaded answer-script PDF:
      • extract roll number + answers via OCR/LLM
      • verify roll number = username stored in Mongo
      • update the Mongo record only on a match
    """

    def __init__(self, student_upload_id: str | None = None):
        self.student_upload_id = student_upload_id
        self.mongo_client  = None
        self.db            = None
        self.collection    = None
        self.ocr_client    = None
        self.roll_client   = None

        self.course_code   = None
        self.course_name   = None
        self.exam_type     = None
        self.year          = None
        self.pdf_path      = None

        self.expected_roll_no = None     

        self.initialize_clients()
        self.load_exam_metadata()

    # ───────────────────────── Initialisation ───────────────────────── #

    def initialize_clients(self):
        try:
            self.mongo_client = MongoClient(
                MONGO_CONNECTION_STRING,
                serverSelectionTimeoutMS=5_000,
                connectTimeoutMS=30_000,
                socketTimeoutMS=30_000,
            )
            self.mongo_client.admin.command("ping")
            self.db         = self.mongo_client[DATABASE_NAME]
            self.collection = self.db[COLLECTION_NAME]
            print("✔ Connected to MongoDB.")

            self.ocr_client  = Groq(api_key=GROQ_API_KEY_OCR)
            self.roll_client = Groq(api_key=GROQ_API_KEY_ROLL)
            print("✔ Connected to Groq API.")
        except PyMongoError as e:
            raise ConnectionError(f"MongoDB connection failed: {e}")
        except Exception as e:
            raise RuntimeError(f"Client initialization failed: {e}")

    def load_exam_metadata(self):
        try:
            if self.student_upload_id:
                print(f"Fetching document ID: {self.student_upload_id}")
                doc = self.collection.find_one({"_id": ObjectId(self.student_upload_id)})
            else:
                print("No ID specified – loading latest document.")
                doc = self.collection.find_one(sort=[("uploadedAt", -1)])

            if not doc:
                raise ValueError("No matching MongoDB document found.")

            # exam metadata
            self.course_code = doc.get("subjectCode")
            self.course_name = doc.get("subject")
            self.exam_type   = doc.get("examType")
            self.year        = str(doc.get("year"))

            # >>> NEW – stash expected roll number from 'username'
            self.expected_roll_no = str(doc.get("username", "")).strip()
            if not self.expected_roll_no:
                raise ValueError("'username' (expected roll number) missing in MongoDB document.")

            # pdf path
            raw_path = doc.get("filePath")
            if not raw_path:
                raise ValueError("'filePath' missing in MongoDB document.")

            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            self.pdf_path = os.path.join(project_root, raw_path)
            print(f"DEBUG: PDF path → {self.pdf_path}")

            # retry until file appears
            for attempt in range(10):
                if os.path.exists(self.pdf_path):
                    break
                wait = 0.5 * (1.5 ** attempt)
                print(f"⏳ PDF not found. Retry {attempt+1}/10 in {wait:.1f}s")
                time.sleep(wait)
            else:
                raise FileNotFoundError(f"PDF still missing at {self.pdf_path}")

            if not all([self.course_code, self.course_name, self.exam_type, self.year]):
                raise ValueError("Missing exam metadata fields.")

            print(f"✔ Metadata loaded. Expected roll (username) = {self.expected_roll_no}")

        except PyMongoError as e:
            raise RuntimeError(f"MongoDB error during metadata load: {e}")
        except Exception as e:
            raise RuntimeError(f"Metadata loading failed: {e}")

    # ───────────────────────── Utility helpers ───────────────────────── #

    @staticmethod
    def encode_image(img: Image.Image) -> str:
        buf = BytesIO()
        img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        buf.close()
        return b64

    @staticmethod
    def correct_roll_number(raw: str) -> str:
        if not raw:
            return ""
        first_map = {'i':'1','I':'1','l':'1','L':'1','7':'1','9':'2','B':'8','S':'5','o':'0','O':'0'}
        corrected_first = first_map.get(raw[0], raw[0])
        remaining = re.sub(r"\D", "", raw[1:])
        return (corrected_first + remaining)[:9]

    # ───────────────────────── OCR wrappers ───────────────────────── #

    def extract_text_from_image(self, img: Image.Image) -> str:
        b64 = self.encode_image(img)
        rsp = self.ocr_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role":"user","content":[
                    {"type":"text","text":"Extract the exact text from this image without changing formatting."},
                    {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
                ]},
                {"role":"user","content":"Don't analyze or summarize. Just output the raw text as it appears."}
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        if not rsp.choices:
            raise RuntimeError("Groq OCR returned no choices.")
        return rsp.choices[0].message.content.strip()

    def extract_roll_number(self, img: Image.Image) -> str:
        b64 = self.encode_image(img)
        rsp = self.roll_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role":"user","content":[
                    {"type":"text","text":"Extract only the 9-digit roll number from this image."},
                    {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
                ]},
                {"role":"user","content":"Return only the digits with no extra text."}
            ],
            temperature=0.1,
            max_tokens=100,
        )
        if not rsp.choices:
            raise RuntimeError("Groq roll-number OCR returned no choices.")
        raw = rsp.choices[0].message.content.strip()
        roll_no = self.correct_roll_number(raw)
        if not re.fullmatch(r"[1-4]\d{8}", roll_no):
            raise ValueError(f"OCR roll number invalid: '{raw}' → '{roll_no}'")
        return roll_no

    # ───────────────────────── Page helpers ───────────────────────── #

    @staticmethod
    def is_first_page(text: str) -> bool:
        kws = ["roll number","degree","department","semester","course code","date of examination"]
        return sum(k in text.lower() for k in kws) >= KEYWORD_THRESHOLD

    @staticmethod
    def segment_answers(text: str) -> List[Dict]:
        """
        Normalize various answer/question heading formats into 'Answer <id>\n' and extract answers.
        Supports formats like: Q2, Answer-3a, 4b), 5. and even bare 6 headings.
        """
        # Normalize full labels like "Answer 1", "Q-3", etc.
        text = re.sub(
            r"(?i)\b(?:answer|ans|question|ques|q|solution)[\s\-]*([0-9]+[a-z]?)\b[\.\):]?",
            r"Answer \1\n", text
        )

        # Normalize sub-question formats like "2a)", "4f)"
        text = re.sub(
            r"\b([0-9]+[a-z])\)", r"Answer \1\n", text, flags=re.IGNORECASE
        )

        # Normalize "1." or "3a." style
        text = re.sub(r"\b([0-9]+[a-z]?)\.\s", r"Answer \1\n", text)
        text = re.sub(r"\b([0-9]+[a-z]?)\)\s", r"Answer \1\n", text)

        # ✅ New: Normalize bare numbers at start of line like "3 Context..."
        text = re.sub(r"(?m)^\s*([0-9]+[a-z]?)\s", r"Answer \1\n", text)

        # Segment answers
        pattern = re.compile(r"Answer\s+([0-9]+[a-z]?)\s*\n", flags=re.IGNORECASE)
        matches = list(pattern.finditer(text))
        if not matches:
            raise ValueError("No answer markers found after normalization.")

        answers = []
        for i, m in enumerate(matches):
            q_id = m.group(1)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            answer_text = text[start:end].strip()
            if answer_text:
                answers.append({"question_id": q_id, "answer_text": answer_text})

        return answers

    # ───────────────────────── Core pipeline ───────────────────────── #

    def convert_pdf_to_images(self) -> List[Image.Image]:
        try:
            pages = convert_from_path(self.pdf_path)
            if not pages:
                raise RuntimeError("PDF→image conversion produced no pages.")
            print(f"✔ Converted PDF to {len(pages)} images.")
            return pages
        except Exception as e:
            raise RuntimeError(f"convert_from_path failed: {e}")
        


    def process_pdf(self) -> Dict:
        pages = self.convert_pdf_to_images()
        roll_no = ""
        answer_pages_text = []

        for i, img in enumerate(pages):
            print(f"▸ OCR page {i+1}/{len(pages)}")
            text = self.extract_text_from_image(img)

            if self.is_first_page(text) and not roll_no:
                try:
                    roll_no = self.extract_roll_number(img)
                    print(f"✔ Detected roll number on page {i+1}: {roll_no}")
                except Exception as e:
                    print(f"⚠ Roll extraction failed on page {i+1}: {e}")
                    answer_pages_text.append(text)
            else:
                answer_pages_text.append(text)

        if not roll_no:
            raise ValueError("Roll number was not detected in any page.")
        if not answer_pages_text:
            raise ValueError("No answer pages detected.")

        # >>> NEW – verify against username
        if roll_no != self.expected_roll_no:
            raise ValueError(
                f"Roll-number mismatch: OCR='{roll_no}' vs username='{self.expected_roll_no}'. "
                "Aborting further processing."
            )

        answers = self.segment_answers("\n".join(answer_pages_text))
        return {
            "course_code": self.course_code,
            "course_name": self.course_name,
            "year":        self.year,
            "exam":        self.exam_type,
            "roll_no":     roll_no,
            "answers":     answers,
        }
    

    def is_already_extracted(self) -> bool:
        if not self.student_upload_id:
            return False
        record = self.collection.find_one(
            {"_id": ObjectId(self.student_upload_id)},
            {"extraction_status": 1}
        )
        return record and record.get("extraction_status") == "completed"

    # ───────────────────────── MongoDB update ───────────────────────── #

    def update_student_record_in_db(self, roll_no: str, answers: List[Dict]):
        try:
            if not self.student_upload_id:
                print("⚠ No student_upload_id – skipping DB update.")
                return
            self.collection.update_one(
                {"_id": ObjectId(self.student_upload_id)},
                {"$set": {
                    "extraction_status" : "completed",
                    "extractedAnswer": {
                        "answers":    answers,
                    }
                }}
            )
            print(f"✔ MongoDB record updated for ID {self.student_upload_id}")
        except Exception as e:
            print(f"⛔ MongoDB update failed: {e}")
            if self.student_upload_id:
                self.collection.update_one(
                    {"_id": ObjectId(self.student_upload_id)},
                    {"$set": {"extraction_status": "failed"}}
                )

    # ───────────────────────── Public entry point ───────────────────────── #

    def process(self) -> bool:
        try:
            print("\n=== Answer-extraction run started ===")
            print(f"Target Mongo document: {self.student_upload_id or 'latest'}")

            if self.is_already_extracted():
                print("Answers already found.")
                return

            student_data = self.process_pdf()   # may raise on mismatch
            self.update_student_record_in_db(
                student_data["roll_no"], student_data["answers"]
            )

            print("=== Extraction finished successfully ===")
            return True

        except Exception as e:
            print(f"⛔ Extraction aborted: {e}")
            import traceback
            traceback.print_exc()
            return False