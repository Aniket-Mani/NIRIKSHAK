import fitz  # PyMuPDF library for PDF processing
import pytesseract  # Python wrapper for Google's Tesseract-OCR
from PIL import Image  # Python Imaging Library for image manipulation
import io  # For handling in-memory binary streams (image data)
import os  # For interacting with the operating system
from groq import Groq  # Groq API client
from dotenv import load_dotenv
import json  # For JSON serialization and deserialization
import sys  # For system-specific parameters and functions

# --- Configuration ---
# Load .env file from the project root (../../ from current script location)
# To load .env from project/backend/
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../.env'))
load_dotenv(dotenv_path=env_path)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# --- Tesseract OCR Configuration ---
# The path to the Tesseract executable.
# Priority: 1. TESSERACT_CMD_PATH from .env file
#           2. Platform-specific common paths (add as needed)
#           3. Hardcoded Windows path (as a last resort for development)
tesseract_cmd_path_from_env = os.getenv("TESSERACT_CMD_PATH")
if tesseract_cmd_path_from_env:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd_path_from_env
    print(f"Python: Using Tesseract from TESSERACT_CMD_PATH: {tesseract_cmd_path_from_env}", file=sys.stderr)
else:
    # Platform-specific configuration (expand as needed)
    if sys.platform.startswith('win32'):
        # Common Windows path
        default_windows_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        if os.path.exists(default_windows_path):
            pytesseract.pytesseract.tesseract_cmd = default_windows_path
            print(f"Python: Using Tesseract from default Windows path: {default_windows_path}", file=sys.stderr)
        else:
            print("Python WARNING: Tesseract OCR executable path not found at C:\\Program Files\\Tesseract-OCR\\tesseract.exe and TESSERACT_CMD_PATH not set. OCR might fail.", file=sys.stderr)
    elif sys.platform.startswith('darwin'): # macOS
        # Example for Homebrew on Apple Silicon
        # default_mac_path = r'/opt/homebrew/bin/tesseract'
        # if os.path.exists(default_mac_path):
        #     pytesseract.pytesseract.tesseract_cmd = default_mac_path
        pass # Add macOS specific paths if needed
    elif sys.platform.startswith('linux'):
        # Example for Linux
        # default_linux_path = r'/usr/bin/tesseract'
        # if os.path.exists(default_linux_path):
        #     pytesseract.pytesseract.tesseract_cmd = default_linux_path
        pass # Add Linux specific paths if needed
    # If no specific path is found/set, pytesseract might still find it if it's in system PATH.

# Define the strict JSON structure prompt for the Groq LLM.
# This guides the LLM to produce output in the desired format.
JSON_STRUCTURE_PROMPT = """
[
  {
    "questionNo": "String",
    "questionText": "String",
    "marks": "Number"
  }
]

VERY IMPORTANT Instructions for the AI:

1.  Overall Goal: Analyze the provided text content from an "exam paper" and accurately populate a JSON array as defined above. Each object in the array represents a single, distinct question or sub-question. The output MUST be a flat list.

2.  *Structure of Each JSON Object:*
    * "questionNo": (String) The identifier for the question or specific sub-question.
    * "questionText": (String) The complete text of that specific question or sub-question.
    * "marks": (Number) The marks allocated to that specific question or sub-question. If marks are not specified, use `null`.

3.  *Handling Main Questions and Sub-questions (Flattening):*
    * If a main question (e.g., "1.", "II.") has sub-parts (e.g., "a)", "(i)"), each sub-part MUST be treated as a separate and distinct entry in the top-level JSON array.
    * For these cases, the "questionNo" field MUST combine the main number and the sub-part identifier WITHOUT spaces or parentheses.
    * **Correct Format Examples:**
        * Main "1.", sub "a)"  ->  "questionNo": "1a" , * Dont Add Q1a, Q2b, etc. as sub-questions. directly use "1a", "2b", etc.
        * Main "2.", sub "(b)" ->  "questionNo": "2b"
        * Main "III", sub "i"  ->  "questionNo": "3i"  (Use Arabic numerals for Roman numerals)
    * **Incorrect Format Examples (DO NOT USE):** "1 (a)", "2.b", "Q1a", "Question 3(i)"
    * If a main question (e.g., "1. Answer the following:") is just a lead-in, DO NOT create an entry for it. Only create entries for the actual sub-questions.
    * If a question is standalone without sub-parts (e.g., "4. Explain superposition."), its "questionNo" should be just the number: "4".
    * ▲▲▲ END OF KEY CHANGE ▲▲▲

4.  *Marks Allocation:*
    * Extract the marks specifically associated with each individual question or sub-question.
    * If marks are mentioned for a main question that has sub-parts, and those sub-parts also have individual marks, prioritize the marks of the individual sub-parts.
    * If it's unclear, marks for sub-parts can be `null`.

5.  *Exclusions from this JSON format:*
    * Do NOT include general exam details (institute name, course code, date, etc.).
    * Do NOT include general instructions (e.g., "Answer all questions").
    * There should be NO "subQuestions" field or any nested structures. The output must be a single, flat array.
    * Do NOT include "answer" or "code" fields.

6.  *JSON Validity and Completeness:*
    * The final output MUST be a single, valid JSON array.
    * Ensure all keys ("questionNo", "questionText", "marks") are present in each object.

7.  *Empty or Missing Information:*
    * If "marks" for a specific question/sub-question are not found, use `null`.
    * If no questions are found in the document at all, return an empty array `[]`.

Return ONLY the populated JSON array as a valid JSON string. Do NOT include any preamble, conversational text, or markdown characters (like ```json) before or after the JSON array itself.
"""


def pdf_ocr_extract(pdf_path):
    """
    Extracts text from all pages of a PDF using OCR.
    Prints progress and errors to stderr.

    Args:
        pdf_path (str): The path to the PDF file.

    Returns:
        str: The concatenated text from all pages, or None if an error occurs.
    """
    all_text = ""
    try:
        # Resolve the absolute path of the PDF for robustness.
        # The path received as an argument should be resolvable from the script's CWD.
        absolute_pdf_path = os.path.abspath(pdf_path)
        print(f"Python: Attempting to process PDF at resolved path: {absolute_pdf_path}", file=sys.stderr)

        if not os.path.exists(absolute_pdf_path):
            print(f"Python Error: PDF file not found at '{absolute_pdf_path}'. Please check the path passed to the script.", file=sys.stderr)
            return None

        doc = fitz.open(absolute_pdf_path)
        for page_num in range(len(doc)):
            print(f"Python: Processing page {page_num + 1}/{len(doc)} of '{os.path.basename(absolute_pdf_path)}'", file=sys.stderr)
            page = doc.load_page(page_num)
            # Increase DPI for better OCR quality
            pix = page.get_pixmap(dpi=300) 

            img_data = pix.tobytes("ppm") 
            image = Image.open(io.BytesIO(img_data))

            text_on_page = pytesseract.image_to_string(image)
            all_text += f"\n\n--- Page {page_num + 1} ---\n{text_on_page.strip()}"
        doc.close()
        print(f"Python: OCR completed for {absolute_pdf_path}. Total text length: {len(all_text.strip())}", file=sys.stderr)
        return all_text.strip() if all_text else ""
    except FileNotFoundError: # Should be caught by os.path.exists, but as a safeguard
        print(f"Python Error: The PDF file '{pdf_path}' was not found (FileNotFoundError).", file=sys.stderr)
        return None
    except pytesseract.TesseractNotFoundError as e:
        print(f"Python Error: Tesseract OCR executable not found or not configured correctly. "
              f"Please ensure Tesseract is installed and its path is set via TESSERACT_CMD_PATH in .env or "
              f"accessible in system PATH. Current Pytesseract cmd: '{pytesseract.pytesseract.tesseract_cmd}'. Error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Python Error: An unexpected error occurred during PDF OCR extraction for '{pdf_path}': {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return None


def generate_json_with_groq(api_key, text_content, json_prompt_template):
    """
    Generates JSON using Groq API and Llama3 model.
    Includes robust JSON extraction logic.
    Prints progress and errors to stderr.

    Args:
        api_key (str): The Groq API key.
        text_content (str): The text extracted from the document.
        json_prompt_template (str): The JSON structure and instructions for the LLM.

    Returns:
        str: The extracted and cleaned JSON string, or None if an error occurs.
    """
    if not api_key:
        print("Python Error: Groq API key is not set. Cannot call Groq API.", file=sys.stderr)
        return None
    if not text_content:
        print("Python Error: Text content for Groq API is missing or empty.", file=sys.stderr)
        return None

    client = Groq(api_key=api_key)
    messages = [
        {
            "role": "system",
            "content": "You are an expert AI assistant tasked with parsing text from exam papers and converting it into a structured JSON format according to very specific instructions. Accuracy and adherence to the requested JSON schema are paramount. Ensure all string values in the JSON are valid JSON strings, especially within arrays like 'instructions'. Do NOT include any preamble, conversational text, or markdown fences (json) before or after the JSON object itself. Only return the pure JSON object."
        },
        {
            "role": "user",
            "content": f"Here is the text extracted from an exam paper:\n\n--- TEXT START ---\n{text_content}\n--- TEXT END ---\n\nBased on the text above, please populate the following JSON structure. Follow all instructions in the JSON structure's comment block meticulously:\n\n{json_prompt_template}"
        }
    ]

    try:
        print(f"Python: Sending request to Groq API (using key ending with ...{api_key[-4:] if api_key and len(api_key) > 4 else 'N/A'})...", file=sys.stderr)
        chat_completion = client.chat.completions.create(
            messages=messages,
            model="llama3-70b-8192", # Or consider making this configurable
            temperature=0.05, 
        )
        generated_content = chat_completion.choices[0].message.content
        print("Python: Received response from Groq API.", file=sys.stderr)
        
        cleaned_content = generated_content.strip()
        print(f"Python: Raw Groq output (first 200 chars): {cleaned_content[:200]}...", file=sys.stderr)

        if cleaned_content.startswith("json"):
            json_start_index = cleaned_content.find('{', len("json"))
            json_end_index = cleaned_content.rfind('}') + 1
            if json_start_index != -1 and json_end_index != -1 and json_end_index > json_start_index:
                extracted_json = cleaned_content[json_start_index:json_end_index].strip()
                print("Python: Successfully extracted JSON from markdown block.", file=sys.stderr)
                return extracted_json
        
        first_brace = cleaned_content.find('{')
        last_brace = cleaned_content.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            # Check if the content starts with '{' or has minimal preamble before it.
            # This handles cases where the LLM might add "Here is the JSON:"
            # or if it directly outputs the JSON.
            potential_json = cleaned_content[first_brace : last_brace + 1]
            try:
                json.loads(potential_json) # Validate if this substring is valid JSON
                print("Python: Successfully extracted JSON by finding first '{' and last '}'.", file=sys.stderr)
                return potential_json.strip()
            except json.JSONDecodeError:
                print("Python: Found braces, but content between them is not valid JSON. Trying to return raw content.", file=sys.stderr)
        
        print("Python: Could not reliably extract JSON. Returning raw content for further inspection by caller.", file=sys.stderr)
        return cleaned_content # Return raw content for the caller to attempt parsing

    except Exception as e:
        print(f"Python Error: An unexpected error occurred during Groq API call or response processing: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return None


def main(pdf_input_path):
    """
    Main function to drive the OCR and JSON generation process.
    Takes PDF input path as a command-line argument.
    Prints final JSON to stdout, errors/progress to stderr.
    """
    print(f"Python: question_parser.py script started. PDF from arg: {pdf_input_path}", file=sys.stderr)

    if not GROQ_API_KEY:
        print("Python CRITICAL ERROR: Groq API key (GROQ_API_KEY) is not set in the environment. Exiting.", file=sys.stderr)
        sys.exit(1) 

    print(f"Python: Starting OCR for PDF: {pdf_input_path}...", file=sys.stderr)
    extracted_text_from_pdf = pdf_ocr_extract(pdf_input_path)

    if extracted_text_from_pdf is None or not extracted_text_from_pdf.strip():
        print("Python Error: OCR failed or resulted in empty text. Cannot proceed to JSON generation. Exiting.", file=sys.stderr)
        sys.exit(1) 
        
    print("Python: OCR process completed successfully.", file=sys.stderr)

    print("\nPython: Starting JSON generation with Groq...", file=sys.stderr)
    generated_json_string = generate_json_with_groq(GROQ_API_KEY, extracted_text_from_pdf, JSON_STRUCTURE_PROMPT)

    if generated_json_string:
        try:
            json_output_data = json.loads(generated_json_string)
            # Print the validated, possibly pretty-formatted JSON to stdout for Node.js
            print(json.dumps(json_output_data, indent=2, ensure_ascii=False))
            print("Python: Successfully parsed and sent JSON to stdout. Exiting successfully.", file=sys.stderr)
            sys.exit(0) 
        except json.JSONDecodeError as e:
            print(f"Python Error: Final content from Groq is not valid JSON. JSONDecodeError: {e}", file=sys.stderr)
            print(f"Python Problematic JSON string (first 500 chars): {generated_json_string[:500]}...", file=sys.stderr)
            print(f"Python Problematic JSON string (last 500 chars): ...{generated_json_string[-500:]}", file=sys.stderr)
            sys.exit(1) 
    else:
        print("Python Error: Failed to generate JSON string from Groq API (it was None or empty). Exiting.", file=sys.stderr)
        sys.exit(1) 

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Python Usage Error: python question_parser.py <path_to_question_paper_pdf>", file=sys.stderr)
        sys.exit(1)
    
    pdf_path_from_caller = sys.argv[1]
    main(pdf_path_from_caller)