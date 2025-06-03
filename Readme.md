# NIRIKSHAK: Automated Handwritten Answer Script Evaluation 🚀

**Natural Inspection and Reading of Image-based Knowledge from Student's Handwritten Answer scripts using Kosine similarity**



NIRIKSHAK is an innovative web application designed to **automate the evaluation of handwritten answer scripts**, providing efficient and accurate marks. It leverages advanced OCR, Natural Language Processing (NLP), and Large Language Models (LLMs) to streamline the traditionally tedious grading process for educational institutions.

---

## 🌟 Goals

-   Provide an efficient and accurate system for **automated grading** of handwritten answer scripts.  
-   Enhance **accuracy and consistency** in marking through AI and LLM integration.  
-   Generate **detailed marksheets** for individual students and comprehensive class reports.  
-   Offer a **streamlined and intuitive workflow** for students, professors, and administrators.

---

## ✨ Features

### Automated Evaluation Pipeline

-   **Intelligent Question & Marks Extraction**: Automatically parses question papers (PDF/Image) to extract individual questions and their allocated marks, forming a structured JSON representation.  
-   **Comprehensive Reference Answer Generation**: For each question, the system uses a provided "book" (reference material) to generate **three distinct types of LLM-powered answers** using Groq:  
    -   **Highly Factual**: Directly derived from relevant context paragraphs found in the book.  
    -   **Factual + Creative**: A balanced answer combining contextual information with general knowledge.  
    -   **Purely Creative**: An answer generated purely by the LLM using its expansive knowledge.  
    -   Reference answers are intelligently cached using **content-based hashing** to ensure consistency and efficiency, regardless of the book's filename.  
-   **Student Answer Script Processing**: Extracts handwritten answers from student-uploaded PDF/image scripts, accurately identifying roll numbers via OCR (Tesseract + Groq) and segmenting individual answers. Extracted student answers are grouped by roll number and stored for evaluation.  
-   **Automated Scoring with Cosine Similarity**: Matches student answers against the best of the three LLM-generated reference answers. This is achieved using **cosine similarity** based on Sentence-BERT embeddings, assigning marks accordingly.  
-   **Detailed Marksheet Generation**:  
    -   Generates **individual student marksheets** in PDF format, viewable and downloadable directly from the web interface.  
    -   Generates a **combined class marksheet** in both PDF and CSV formats, offering an aggregated view of class performance.  
    -   All generated reports are securely stored in **MongoDB GridFS** for easy retrieval and management.

### User Management & Interface

-   **Role-Based Access Control**: Features a robust login system supporting three distinct user roles:  
    -   **Student**: Can create an ID (using their roll number as username), log in, select course details, upload answer scripts, and view their individual results once processed by a professor.  
    -   **Professor**: Can create an ID and log in to select course details, upload question papers, reference books, and multiple student answer scripts. They can initiate the evaluation process and retrieve generated individual and combined class results.  
    -   **Admin**: Manages user accounts and directly adds courses to the database.  
-   **Intuitive Dashboards**: Provides dedicated dashboards (`student.html`, `professor.html`, `admin.html`) tailored to each user role for a seamless experience.  
-   **Forgot Password Functionality**: Ensures secure account recovery.

### Data Management & Efficiency

-   **MongoDB Integration**: A robust NoSQL database (`MongoDB v8.0.9`) stores all user data, course information, extracted questions, LLM-generated answers, student answer extractions, and evaluation results.  
-   **Intelligent Result Caching**: If a professor has already initiated evaluation for a specific course/exam and results exist, the system prioritizes existing calculated results, preventing redundant processing even if students re-upload scripts.  
-   **Backend Automation**: Leverages Node.js for the main server and Python Flask APIs for computationally intensive tasks like OCR, LLM inference, and report generation, ensuring a responsive user experience.

---

## 💻 Tech Stack

### Backend (Node.js & Express.js)

-   Node.js  
-   Express.js (for core API and routing)  
-   JWT (for authentication)  
-   `dotenv` (for environment variables)  
-   `mongoose` (for MongoDB ODM)

### Backend (Python Microservices)

-   Python 3.8+  
-   Flask (for specialized APIs: `Answer_from_book.py`, `python_api.py`)  
-   `Flask-CORS`  
-   `sentence-transformers` (for embeddings)  
-   `faiss-cpu` (for vector similarity search)  
-   `groq` (for LLM inference)  
-   `PyMuPDF` (`fitz`) (for PDF processing)  
-   `Pillow` (`PIL`) (for image manipulation)  
-   `pdf2image` (for PDF to image conversion)  
-   `pytesseract` (for OCR)  
-   `python-docx` (for DOCX generation)  
-   `pandas` (for data manipulation)  
-   `scikit-learn` (for cosine similarity)  
-   `pymongo` (for MongoDB driver)

### Frontend

-   HTML5  
-   CSS3 (custom stylesheets)  
-   Vanilla JavaScript  
-   `jwt-decode` (client-side JWT decoding)

### Database

-   MongoDB (v8.0.9)  
-   MongoDB GridFS (for large file storage)

### System Dependencies

-   Poppler  
-   Tesseract OCR  
-   Pandoc

---

## ⚙️ Setup & Installation

### Prerequisites

Ensure you have the following installed on your system:

-   **Node.js (LTS version recommended)**  
-   **Python 3.8+**  
-   **MongoDB (v8.0.9 recommended)**: [Download & Install MongoDB](https://docs.mongodb.com/manual/installation/)  
    -   **Crucial:** Make sure your MongoDB instance is running before starting the application.  
-   **Poppler**:  
    -   **Linux (Debian/Ubuntu):** `sudo apt-get install poppler-utils`  
    -   **macOS (Homebrew):** `brew install poppler`  
    -   **Windows:** [Download pre-built binaries](https://blog.alivate.com.au/poppler-windows/) and add the `bin` directory to your system's PATH.  
-   **Tesseract OCR**:  
    -   **Linux (Debian/Ubuntu):** `sudo apt-get install tesseract-ocr`  
    -   **macOS (Homebrew):** `brew install tesseract`  
    -   **Windows:** [Download installer](https://tesseract-ocr.github.io/tessdoc/Downloads.html) and ensure you add it to your system's PATH during installation, or explicitly set `TESSERACT_CMD_PATH` in your `.env` file.  
-   **Pandoc**:  
    -   [Download & Install Pandoc](https://pandoc.org/installing.html)

### Steps

1.  **Clone the repository:**

    ```bash
    git clone [https://github.com/your-username/NIRIKSHAK.git](https://github.com/your-username/NIRIKSHAK.git)
    cd NIRIKSHAK
    ```

2.  **Navigate to the backend directory:**

    ```bash
    cd backend
    ```

3.  **Set up Environment Variables:**

    * Copy the example environment file:
        ```bash
        cp .env.example .env
        ```
    * Open the newly created `.env` file and fill in your actual values. **It's critical to configure `TESSERACT_CMD_PATH` accurately for your system.**

        ```env
        # .env
        JWT_SECRET=your_jwt_secret_here
        MONGODB_URI=your_mongodb_connection_string
        GROQ_API_KEY=your_groq_api_key_here
        GROQ_API_KEY_OCR=your_groq_api_key_ocr_here
        GROQ_API_KEY_ROLL=your_groq_api_key_roll_here
        PORT=3000
        TESSERACT_CMD_PATH=/path/to/your/tesseract/executable # e.g., /opt/homebrew/bin/tesseract for macOS Homebrew
        PYTHON_COMMAND=python3 # or 'python'
        ```

4.  **Install Node.js Dependencies:**

    ```bash
    npm install
    ```

5.  **Install Python Dependencies:**

    * Navigate back to the project root (where `requirements.txt` is located):
        ```bash
        cd ..
        ```
    * Install Python packages:
        ```bash
        pip install -r requirements.txt
        ```

---

## 🚀 Running the Application

NIRIKSHAK requires three separate processes to run concurrently for full functionality.

1.  **Initialize Database with Course Data:**

    * Navigate to the `backend` directory:
        ```bash
        cd backend
        ```
    * Run the seeding script. This populates your MongoDB with initial course data, essential for dropdowns in the UI:
        ```bash
        node seedcourses.js
        ```

2.  **Open Three Parallel Terminal Windows:**

    **Terminal 1 (Python API for Student Script Processing):**
    * Navigate to the `backend/extract` directory:
        ```bash
        cd backend/extract
        ```
    * Start the Flask API that handles student answer script extraction:
        ```bash
        python python_api.py
        ```

    **Terminal 2 (Python API for Book Answer Generation):**
    * Navigate to the `backend/extract` directory:
        ```bash
        cd backend/extract
        ```
    * Start the Flask API that handles question paper parsing and LLM answer generation from the book:
        ```bash
        python Answer_from_book.py
        ```

    **Terminal 3 (Node.js Server):**
    * Navigate to the `backend` directory:
        ```bash
        cd backend
        ```
    * Start the main Node.js server:
        ```bash
        node server.js
        ```

Once all three terminals are running without errors, open your web browser and go to:

`http://localhost:3000/login.html` (or `http://localhost:3000/home.html`)

---

## 📖 Usage Instructions

### General Workflow

1.  **Admin**: Log in and add necessary courses via the admin dashboard if `seedcourses.js` wasn't used or if new courses are needed.  
2.  **Professor**:  
    * Log in and navigate to the Professor Dashboard.  
    * Select the relevant **Course, Semester, Year, Exam Type, and Section**.  
    * Upload the **Question Paper**, **Reference Book**, and **Student Answer Scripts**.  
    * The backend will automatically parse questions, extract answers from the book, and process student scripts.  
    * Click **"Get Results"** to trigger the scoring process. Individual and combined marksheets will be generated and made available for download.  
3.  **Student**:  
    * Ensure your username (used for login) matches your roll number in your answer script.  
    * Log in and navigate to the Student Dashboard.  
    * Select the relevant **Course, Semester, Year, Exam Type, and Section**.  
    * Upload your **Answer Script**.  
    * Once the professor has processed the results for your exam, you can click **"See Results"** to view and download your individual marksheet. The system prioritizes the professor's processed results if they exist.

### Important Notes

-   **Roll Number Matching:** For student answer script processing, ensure the student's login **username is their exact roll number** as it appears on their answer script. This is crucial for correct matching and processing.  
-   **File Formats:** Ensure all uploaded PDFs and images are clear and readable for optimal OCR accuracy.

---

## 🤝 Contributing

We warmly welcome contributions! If you're passionate about improving NIRIKSHAK, please fork the repository and submit a pull request. For substantial changes or new features, consider opening an issue first to discuss your ideas.