
from flask import Flask, request, jsonify
import os
import sys
import json
import hashlib # For PDF content hashing
import re
import pickle
from typing import List, Dict, Union, Tuple, Any
import subprocess # For calling question_parser.py

from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

import fitz # PyMuPDF for PDF processing (used for RAG book processing)
# Tesseract and PIL are not directly used in this script's core logic for question parsing,
# as that's handled by question_parser.py. They are still needed if the RAG book PDF
# itself requires OCR, though extract_and_group_paragraphs uses fitz's text extraction.
from dotenv import load_dotenv
from groq import Groq

from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError
from bson.objectid import ObjectId
import traceback # For detailed error logging
from datetime import datetime

app = Flask(__name__)

# --- Configuration ---
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../.env'))
load_dotenv(dotenv_path=env_path)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONGO_CONNECTION_STRING = os.getenv("MONGO_CONNECTION_STRING", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("MONGO_DB_NAME", "smart")
PROFESSOR_COLLECTION_NAME = "professoruploads"

# Path to your question_parser.py script.
QUESTION_PARSER_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "question_parser.py")

# --- RAG Configuration ---
WINDOW_SIZE = 15
STEP_SIZE = 5
MIN_PARAGRAPH_WORDS = 40
MODEL_NAME = 'all-MiniLM-L6-v2'
EMBEDDING_BATCH_SIZE = 256
SIMILARITY_THRESHOLD = 0.40 # For retrieving relevant paragraphs
MAX_CONTEXT_PARAGRAPHS = 5 # Max paragraphs to use as context for LLM

# --- LLM Configuration (Groq) ---
GROQ_MODEL = "llama3-70b-8192"
TEMP_FACTUAL = 0.1
TEMP_BALANCED = 0.4
TEMP_CREATIVE = 0.7

os.environ["TOKENIZERS_PARALLELISM"] = "false"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR_BOOK_RAG = os.path.join(SCRIPT_DIR, "cache_book_rag_faiss")
os.makedirs(CACHE_DIR_BOOK_RAG, exist_ok=True)
print(f"Python (Answer_from_book): RAG Cache directory for books: {CACHE_DIR_BOOK_RAG}", file=sys.stderr)

# Global instances
groq_client = None
mongo_client = None
db_smart = None
professor_collection_instance = None
embedding_model_instance = None

def initialize_globals():
    global groq_client, mongo_client, db_smart, professor_collection_instance, embedding_model_instance
    print("Python (Answer_from_book): Initializing global resources...", file=sys.stderr)

    if not GROQ_API_KEY:
        print("Python Error (Answer_from_book): GROQ_API_KEY not set. Groq client will not be initialized.", file=sys.stderr)
    elif groq_client is None:
        try:
            groq_client = Groq(api_key=GROQ_API_KEY)
            print("Python (Answer_from_book): Groq client initialized.", file=sys.stderr)
        except Exception as e:
            print(f"Python Error (Answer_from_book): Failed to initialize Groq client: {e}", file=sys.stderr)
            groq_client = None

    if mongo_client is None:
        try:
            mongo_client = MongoClient(MONGO_CONNECTION_STRING, serverSelectionTimeoutMS=5000)
            mongo_client.admin.command('ping')
            db_smart = mongo_client[DATABASE_NAME]
            professor_collection_instance = db_smart[PROFESSOR_COLLECTION_NAME]
            print(f"Python (Answer_from_book): Connected to MongoDB (DB: {DATABASE_NAME}, Collection: {PROFESSOR_COLLECTION_NAME}).", file=sys.stderr)
        except Exception as e:
            print(f"Python Error (Answer_from_book): Could not connect to MongoDB or initialize collection: {e}", file=sys.stderr)
            mongo_client = None
            db_smart = None
            professor_collection_instance = None

    if embedding_model_instance is None:
        try:
            print(f"Python (Answer_from_book): Loading Sentence Transformer model '{MODEL_NAME}'...", file=sys.stderr)
            embedding_model_instance = SentenceTransformer(MODEL_NAME)
            print("Python (Answer_from_book): Sentence Transformer model loaded.", file=sys.stderr)
        except Exception as e:
            print(f"Python Error (Answer_from_book): Failed to load Sentence Transformer model '{MODEL_NAME}': {e}", file=sys.stderr)
            embedding_model_instance = None

with app.app_context():
    initialize_globals()

def calculate_pdf_content_hash(pdf_path: str) -> Union[str, None]:
    """Calculates a SHA256 hash of the PDF file's content."""
    try:
        hasher = hashlib.sha256()
        with open(pdf_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except FileNotFoundError:
        print(f"Python Error (Answer_from_book): PDF not found at {pdf_path} for hashing.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Python Error (Answer_from_book): Error hashing PDF {pdf_path}: {e}", file=sys.stderr)
        return None

# --- RAG Helper Functions ---
def sanitize_filename(filename_base: str, max_length: int = 100) -> str:
    s = str(filename_base).strip().replace(" ", "_")
    s = re.sub(r"(?u)[^-\w.]", "", s)
    return s[:max_length] if s else "untitled"

def get_book_rag_cache_filenames(pdf_content_hash: str, window_size: int, step_size: int, min_words: int) -> Tuple[str, str]:
    model_name_sanitized = MODEL_NAME.replace('/', '-')
    cache_prefix = f"content_{pdf_content_hash}_w{window_size}_s{step_size}_m{min_words}_{model_name_sanitized}"
    pickle_filename = f"{cache_prefix}_paras.pkl"
    faiss_filename = f"{cache_prefix}_index.faiss"
    return os.path.join(CACHE_DIR_BOOK_RAG, pickle_filename), os.path.join(CACHE_DIR_BOOK_RAG, faiss_filename)

def extract_and_group_paragraphs(pdf_path: str, window_size: int, step_size: int, min_paragraph_words: int) -> List[str]:
    print(f"Python (Answer_from_book): Extracting paragraphs from RAG book PDF: {pdf_path}", file=sys.stderr)
    if not os.path.exists(pdf_path):
        print(f"Python Error (Answer_from_book): RAG book PDF not found at {pdf_path}", file=sys.stderr)
        return []
    doc = fitz.open(pdf_path)
    cleaned_lines = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        lines_on_page = page.get_text("text").split('\n')
        for line in lines_on_page:
            line = line.strip()
            if line and len(line.split()) > 1 and not line.isnumeric():
                cleaned_lines.append(line)
    doc.close()

    if not cleaned_lines: return []
    paragraphs = []
    for i in range(0, len(cleaned_lines) - window_size + 1, step_size):
        chunk_lines = cleaned_lines[i:i + window_size]
        chunk_text = ' '.join(chunk_lines)
        if len(chunk_text.split()) >= min_paragraph_words:
            paragraphs.append(chunk_text)
    print(f"Python (Answer_from_book): Generated {len(paragraphs)} RAG paragraphs for {os.path.basename(pdf_path)}.", file=sys.stderr)
    return paragraphs

def get_paragraphs_and_faiss_index(rag_pdf_path: str, window_size: int, step_size: int, min_paragraph_words: int, force_regenerate: bool = False) -> Tuple[List[str], Union[faiss.Index, None]]:
    if embedding_model_instance is None:
        print("Python Error (Answer_from_book): Embedding model not initialized. Cannot create FAISS index for RAG book.", file=sys.stderr)
        return [], None

    pdf_content_hash = calculate_pdf_content_hash(rag_pdf_path)
    if not pdf_content_hash:
        print(f"Python Error (Answer_from_book): Could not generate content hash for RAG book {rag_pdf_path}.", file=sys.stderr)
        return [], None

    pickle_cache_file, faiss_cache_file = get_book_rag_cache_filenames(pdf_content_hash, window_size, step_size, min_paragraph_words)

    if not force_regenerate and os.path.exists(pickle_cache_file) and os.path.exists(faiss_cache_file):
        print(f"Python (Answer_from_book): Loading RAG data for book (hash: {pdf_content_hash[:10]}...) from cache...", file=sys.stderr)
        try:
            with open(pickle_cache_file, "rb") as f: data = pickle.load(f)
            paragraphs = data.get('paragraphs', [])
            faiss_index_loaded = faiss.read_index(faiss_cache_file)
            if paragraphs and faiss_index_loaded and faiss_index_loaded.ntotal == len(paragraphs):
                print("Python (Answer_from_book): RAG Book Cache loaded successfully.", file=sys.stderr)
                return paragraphs, faiss_index_loaded
            else: print("Python (Answer_from_book): RAG Book Cache inconsistent. Regenerating.", file=sys.stderr)
        except Exception as e:
            print(f"Python (Answer_from_book): Error loading RAG Book cache ({e}). Regenerating...", file=sys.stderr)

    print(f"Python (Answer_from_book): Regenerating RAG context for book (hash: {pdf_content_hash[:10]}...)...", file=sys.stderr)
    paragraphs = extract_and_group_paragraphs(rag_pdf_path, window_size, step_size, min_paragraph_words)
    if not paragraphs: return [], None

    embedding_dimension = embedding_model_instance.get_sentence_embedding_dimension()
    faiss_index = faiss.IndexFlatIP(embedding_dimension)
    
    print(f"Python (Answer_from_book): Embedding {len(paragraphs)} RAG book paragraphs in batches...", file=sys.stderr)
    for i in range(0, len(paragraphs), EMBEDDING_BATCH_SIZE):
        batch_paragraphs = paragraphs[i:i + EMBEDDING_BATCH_SIZE]
        try:
            batch_vectors = embedding_model_instance.encode(batch_paragraphs, convert_to_numpy=True, show_progress_bar=False)
            if batch_vectors is not None and len(batch_vectors) > 0:
                faiss.normalize_L2(batch_vectors)
                faiss_index.add(batch_vectors.astype(np.float32))
        except Exception as e:
            print(f"Python Error (Answer_from_book): during RAG book embedding/FAISS add for batch: {e}", file=sys.stderr)
            continue 
    
    if faiss_index.ntotal == 0:
        print("Python Warning (Answer_from_book): No vectors added to FAISS index for RAG book.", file=sys.stderr)
        return paragraphs, None
    
    try:
        with open(pickle_cache_file, "wb") as f: pickle.dump({'paragraphs': paragraphs}, f)
        faiss.write_index(faiss_index, faiss_cache_file)
        print("Python (Answer_from_book): RAG Book Cache saved.", file=sys.stderr)
    except Exception as e: print(f"Python Warning (Answer_from_book): Error saving RAG Book cache: {e}", file=sys.stderr)
        
    return paragraphs, faiss_index

# --- LLM Answer Generation ---
def get_groq_llm_response(full_prompt: str, temperature: float) -> str:
    if groq_client is None: return "Error: Groq client not initialized."
    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are an AI assistant. Answer the user's question based on the provided information and instructions. Be concise and accurate."},
                {"role": "user", "content": full_prompt}
            ],
            model=GROQ_MODEL, temperature=temperature, max_tokens=1024,
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Python Error (Answer_from_book): Groq LLM communication error: {e}", file=sys.stderr)
        return f"Error: Groq LLM communication error: {str(e)}"

def process_single_question_item(question_item_data: Dict[str, Any], all_paragraphs: List[str], faiss_idx: Union[faiss.Index, None]):
    """
    Processes a single question item, generates three answers, and adds them to the item.
    The 'marks' field from the parser remains untouched.
    """
    question_text = question_item_data.get("questionText", "")
    
    # Initialize Answers field with error messages or placeholders
    error_answer = "Error: Could not generate answer."
    answers_list = [error_answer, error_answer, error_answer]

    if not question_text:
        answers_list = ["Skipped - Empty question text."]*3
        question_item_data["Answers"] = answers_list
        return # No further processing if question text is empty

    if embedding_model_instance is None:
        answers_list = ["Error: Embedding model not initialized."]*3
        question_item_data["Answers"] = answers_list
        return

    query_vector = embedding_model_instance.encode([question_text], convert_to_numpy=True)
    combined_context_for_llm = ""
    context_found_for_rag = False

    if faiss_idx and faiss_idx.ntotal > 0 and query_vector.ndim > 1:
        faiss.normalize_L2(query_vector)
        query_vector_float32 = query_vector.astype(np.float32)
        k_search = min(MAX_CONTEXT_PARAGRAPHS * 2, faiss_idx.ntotal)
        try:
            scores, indices = faiss_idx.search(query_vector_float32, k=k_search)
            relevant_paras_indices = [i for i, s_val in zip(indices[0], scores[0]) if i < len(all_paragraphs) and s_val >= SIMILARITY_THRESHOLD]
            if relevant_paras_indices:
                relevant_paras = [all_paragraphs[i] for i in relevant_paras_indices]
                combined_context_for_llm = "\n\n---\n\n".join(relevant_paras[:MAX_CONTEXT_PARAGRAPHS])
                context_found_for_rag = True
        except Exception as e:
            print(f"Python Error (Answer_from_book): FAISS search failed for '{question_text[:30]}...': {e}", file=sys.stderr)
    
    # Generate the three types of answers
    ans_factual_rag = get_groq_llm_response(f"Context: {combined_context_for_llm if context_found_for_rag else 'None available.'}\nQuestion: {question_text}\nAnswer factually based ONLY on the provided context. If context is 'None available' or insufficient, state that.", TEMP_FACTUAL)
    ans_combined = get_groq_llm_response(f"Context (optional, use if helpful): {combined_context_for_llm if context_found_for_rag else 'No specific context provided.'}\nQuestion: {question_text}\nAnswer comprehensively, using general knowledge if context is insufficient or not provided.", TEMP_BALANCED)
    ans_creative = get_groq_llm_response(f"Question: {question_text}\nAnswer creatively using general knowledge:", TEMP_CREATIVE)
    
    question_item_data["Answers"] = [ans_factual_rag, ans_combined, ans_creative]
    # The original "marks" field from question_parser.py remains untouched.
    # No new "marks" are awarded or calculated here.

def process_all_questions(parsed_questions_list: List[Dict[str, Any]], all_paragraphs: List[str], faiss_idx: Union[faiss.Index, None]):
    """
    Processes a flat list of questions from question_parser.py.
    Each item in the list is modified in-place by adding an "Answers" field.
    """
    for question_item in parsed_questions_list:
        process_single_question_item(question_item, all_paragraphs, faiss_idx)

def update_professor_record_in_db(upload_id_str: str, final_processed_question_list: List[Dict[str, Any]], status_message: str = "processed_with_answers"):
    """
    Updates the MongoDB record.
    `final_processed_question_list` contains items with original 'questionNo', 'questionText', 'marks'
    and the newly added 'Answers' list.
    """
    if professor_collection_instance is None:
        print("Python Error (Answer_from_book): MongoDB collection not initialized. Cannot update DB.", file=sys.stderr)
        return False
    try:
        object_id = ObjectId(upload_id_str)
        update_result = professor_collection_instance.update_one(
            {"_id": object_id},
            {"$set": {
                "processedJSON": final_processed_question_list, # This list has the 4 required fields per question
                "status": status_message, # Top-level status for the overall processing job
                "processedAt": datetime.utcnow() # Top-level timestamp
            }}
        )
        if update_result.matched_count > 0:
            print(f"Python (Answer_from_book): Successfully updated ProfessorUpload {upload_id_str} in DB. Status: {status_message}", file=sys.stderr)
            return True
        else:
            print(f"Python Error (Answer_from_book): ProfessorUpload {upload_id_str} not found in DB for update.", file=sys.stderr)
            return False
    except Exception as e:
        print(f"Python Error (Answer_from_book): Failed to update MongoDB for {upload_id_str}: {e}", file=sys.stderr)
        return False

# --- Function to call question_parser.py ---
def get_parsed_questions_from_parser(question_paper_pdf_abs_path: str) -> Union[List[Dict[str, Any]], None]:
    if not os.path.exists(QUESTION_PARSER_SCRIPT_PATH):
        print(f"Python Error (Answer_from_book): Question parser script not found at {QUESTION_PARSER_SCRIPT_PATH}", file=sys.stderr)
        return None
    if not os.path.exists(question_paper_pdf_abs_path):
        print(f"Python Error (Answer_from_book): Question paper PDF not found at {question_paper_pdf_abs_path} for parser.", file=sys.stderr)
        return None

    command = [sys.executable, QUESTION_PARSER_SCRIPT_PATH, question_paper_pdf_abs_path]
    print(f"Python (Answer_from_book): Executing question parser: {' '.join(command)}", file=sys.stderr)

    try:
        process = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8')
        
        if process.stderr:
            print(f"Python (Answer_from_book): Stderr from question_parser.py:\n{process.stderr.strip()}", file=sys.stderr)

        if process.returncode != 0:
            print(f"Python Error (Answer_from_book): question_parser.py exited with error code {process.returncode}.", file=sys.stderr)
            return None
        
        if not process.stdout.strip():
            print("Python Error (Answer_from_book): question_parser.py produced no stdout output.", file=sys.stderr)
            return None
            
        try:
            parsed_questions = json.loads(process.stdout)
            print("Python (Answer_from_book): Successfully parsed JSON output from question_parser.py.", file=sys.stderr)
            if not isinstance(parsed_questions, list):
                print("Python Error (Answer_from_book): question_parser.py output is not a JSON list.", file=sys.stderr)
                return None
            # Ensure each item is a dict, basic validation
            for item in parsed_questions:
                if not isinstance(item, dict):
                    print("Python Error (Answer_from_book): Item in question_parser.py output list is not a dictionary.", file=sys.stderr)
                    return None
            return parsed_questions
        except json.JSONDecodeError as e:
            print(f"Python Error (Answer_from_book): Failed to decode JSON from question_parser.py stdout: {e}", file=sys.stderr)
            print(f"Python (Answer_from_book): question_parser.py stdout was:\n{process.stdout[:1000]}...", file=sys.stderr)
            return None

    except FileNotFoundError:
        print(f"Python Error (Answer_from_book): Python executable or parser script not found. Command: '{' '.join(command)}'", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Python Error (Answer_from_book): Failed to run question_parser.py: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None

# --- Main Flask Endpoint ---
@app.route('/process-professor-data', methods=['POST'])
def process_professor_data_endpoint():
    print("Python (Answer_from_book): Received request for /process-professor-data", file=sys.stderr)
    
    if (groq_client is None or 
        mongo_client is None or 
        db_smart is None or 
        professor_collection_instance is None or 
        embedding_model_instance is None):
        
        error_details = []
        if groq_client is None: error_details.append("Groq client not initialized.")
        if mongo_client is None: error_details.append("MongoDB client not initialized.")
        if db_smart is None: error_details.append("MongoDB database object not initialized.")
        if professor_collection_instance is None: error_details.append("MongoDB professor collection not initialized.")
        if embedding_model_instance is None: error_details.append("Embedding model not initialized.")
        
        full_error_message = "Internal server error: Core services not ready. Details: " + " ".join(error_details)
        print(f"Python Error (Answer_from_book): {full_error_message}", file=sys.stderr)
        return jsonify({"status": "error", "message": full_error_message}), 500
        
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON data received"}), 400

    professor_upload_id = data.get("professorUploadId")
    question_paper_path_relative = data.get("questionPaperPath") 
    book_answer_path_relative = data.get("bookAnswerPath") 
    
    if not all([professor_upload_id, question_paper_path_relative, book_answer_path_relative]):
        return jsonify({"status": "error", "message": "Missing required data: professorUploadId, questionPaperPath, or bookAnswerPath"}), 400

    parsed_questions_list_from_parser = None 

    try:
        project_root_dir = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
        
        absolute_question_paper_path = os.path.normpath(os.path.join(project_root_dir, question_paper_path_relative))
        print(f"Python (Answer_from_book): Attempting to parse question paper PDF from: {absolute_question_paper_path}", file=sys.stderr)

        parsed_questions_list_from_parser = get_parsed_questions_from_parser(absolute_question_paper_path)
        
        if parsed_questions_list_from_parser is None:
            # Error message already printed. Update DB with parsing failure.
            # Provide an empty list or error object for processedJSON in this failure case
            update_professor_record_in_db(professor_upload_id, 
                                          [{"error": "Failed to parse question paper PDF using question_parser.py"}], 
                                          "error_question_parser_failed")
            return jsonify({"status": "error", "message": "Failed to parse question paper PDF."}), 500
        
        if not parsed_questions_list_from_parser: # Empty list from parser
             print(f"Python Warning (Answer_from_book): question_parser.py returned an empty list of questions for {absolute_question_paper_path}.", file=sys.stderr)
             update_professor_record_in_db(professor_upload_id, [], "processed_no_questions_found_by_parser")
             return jsonify({"status": "success", "message": "Question paper processed, but no questions were found by the parser."}), 200

        absolute_book_answer_path = os.path.normpath(os.path.join(project_root_dir, book_answer_path_relative))
        print(f"Python (Answer_from_book): Attempting to use RAG book PDF from: {absolute_book_answer_path}", file=sys.stderr)
        if not os.path.exists(absolute_book_answer_path):
            print(f"Python Error (Answer_from_book): RAG book PDF not found at resolved path: {absolute_book_answer_path}", file=sys.stderr)
            # Parsed questions exist, but book is missing. Update DB with this state.
            update_professor_record_in_db(professor_upload_id, parsed_questions_list_from_parser, "error_book_pdf_not_found_for_rag")
            return jsonify({"status": "error", "message": f"RAG Book PDF not found at {absolute_book_answer_path}."}), 400

        print(f"Python (Answer_from_book): Processing RAG for book: {absolute_book_answer_path}", file=sys.stderr)
        all_paragraphs, faiss_index = get_paragraphs_and_faiss_index(
            absolute_book_answer_path, WINDOW_SIZE, STEP_SIZE, MIN_PARAGRAPH_WORDS, force_regenerate=False
        )

        if faiss_index is None or not all_paragraphs:
            print("Python Error (Answer_from_book): RAG index or text for book PDF not available. Cannot generate answers.", file=sys.stderr)
            # Parsed questions exist, RAG book processing failed.
            update_professor_record_in_db(professor_upload_id, parsed_questions_list_from_parser, "error_rag_book_setup_failed")
            return jsonify({"status": "error", "message": "Failed to prepare RAG index for book."}), 500
        print("Python (Answer_from_book): Book RAG embeddings and FAISS index are ready.", file=sys.stderr)

        # Process the flat list of questions, adding "Answers" to each item
        process_all_questions(parsed_questions_list_from_parser, all_paragraphs, faiss_index)
        print("Python (Answer_from_book): LLM answers generated for all questions.", file=sys.stderr)
        
        # parsed_questions_list_from_parser now contains the questions with original marks and new "Answers"
        if update_professor_record_in_db(professor_upload_id, parsed_questions_list_from_parser):
            return jsonify({"status": "success", "message": "Professor data processed, answers generated, and DB updated successfully."}), 200
        else:
            # Data was processed, but DB update failed.
            return jsonify({"status": "error", "message": "Answer generation complete, but failed to update database."}), 500

    except Exception as e:
        error_message = f"Unexpected error in Answer_from_book.py endpoint: {str(e)}"
        print(f"Python CRITICAL Error (Answer_from_book): {error_message}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        
        # Attempt to update DB with failure status.
        # Use parsed_questions_list_from_parser if available, else a generic error object.
        data_for_db_on_error = parsed_questions_list_from_parser if parsed_questions_list_from_parser is not None else [{"error_detail": "Processing failed in python endpoint."}]
        
        # Add error details to the data being saved, if possible
        if isinstance(data_for_db_on_error, list) and data_for_db_on_error and isinstance(data_for_db_on_error[0], dict):
            data_for_db_on_error[0]['_endpoint_processing_error'] = error_message 
        elif isinstance(data_for_db_on_error, dict) : # Should be a list, but as a fallback
            data_for_db_on_error['_endpoint_processing_error'] = error_message


        if professor_upload_id:
             update_professor_record_in_db(professor_upload_id, data_for_db_on_error, "processing_failed_in_python_endpoint")
        return jsonify({"status": "error", "message": error_message}), 500

if __name__ == '__main__':
    print("Python (Answer_from_book): Starting Flask API server on http://localhost:5001", file=sys.stderr)
    # Use 0.0.0.0 to make it accessible on your network, not just localhost
    app.run(host='0.0.0.0', port=5001, debug=False)