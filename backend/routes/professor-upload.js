const express = require('express');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const { exec } = require('child_process'); // Still needed for question_parser.py
const axios = require('axios');
const ProfessorUpload = require('../models/ProfessorUpload');
const { authenticateToken, authorizeRoles } = require('../middleware/authMiddleware');

const router = express.Router();

const professorStorage = multer.diskStorage({
    destination: (req, file, cb) => {
        const uploadDir = path.join(__dirname, '..', '..', 'uploads', 'professor');
        if (!fs.existsSync(uploadDir)) fs.mkdirSync(uploadDir, { recursive: true });
        cb(null, uploadDir);
    },
    filename: (req, file, cb) => {
        const ext = path.extname(file.originalname);
        const name = file.fieldname;
        cb(null, `${name}-${Date.now()}${ext}`);
    }
});

const multipleProfessorUpload = multer({ storage: professorStorage }).fields([
    { name: 'questionPaper', maxCount: 1 },
    { name: 'bookAnswer', maxCount: 1 },
    { name: 'studentScript', maxCount: 100 },
    { name: 'course', maxCount: 1 },
    { name: 'subject', maxCount: 1 },
    { name: 'subjectCode', maxCount: 1 },
    { name: 'semester', maxCount: 1 },
    { name: 'year', maxCount: 1 },
    { name: 'examType', maxCount: 1 },
    { name: 'sectionType', maxCount: 1 },
]);

// executePythonScript is still used for question_parser.py
const executePythonScript = (scriptPath, args, options) => {
    return new Promise((resolve, reject) => {
        const pythonCmd = process.env.PYTHON_COMMAND || 'python';
        const command = `"${pythonCmd}" "${scriptPath}" ${args.map(a => `"${a}"`).join(' ')}`;
        console.log(`Node.js: Executing Python: ${command}`);
        const child = exec(command, options, (error, stdout, stderr) => {
            if (error) {
                console.error(`Node.js exec error for ${path.basename(scriptPath)}: ${error.message}`);
                console.error(`Node.js Python stderr (on error for ${path.basename(scriptPath)}): ${stderr}`);
                return reject({ error, stdout, stderr, code: error.code });
            }
            if (stderr) {
                console.warn(`Node.js Python stderr (non-fatal for ${path.basename(scriptPath)}): ${stderr}`);
            }
            resolve({ stdout, stderr });
        });
    });
};

router.post('/professor', authenticateToken, authorizeRoles(['professor']), multipleProfessorUpload, async (req, res) => {
    const { course, subject, subjectCode, semester, year, examType, sectionType } = req.body;
    const questionPaperFile = req.files['questionPaper'] ? req.files['questionPaper'][0] : null;
    const bookAnswerFile = req.files['bookAnswer'] ? req.files['bookAnswer'][0] : null;
    const studentScriptFiles = req.files['studentScript'] || [];

    if (!questionPaperFile || !bookAnswerFile || !course || !subject || !subjectCode || !semester || !year || !examType || !sectionType) {
        return res.status(400).send({ message: 'Required fields missing.' });
    }

    const questionPaperFilePath = questionPaperFile.path.replace(/\\/g, '/');
    const bookAnswerFilePath = bookAnswerFile.path.replace(/\\/g, '/');
    const studentScriptPaths = studentScriptFiles.map(file => file.path.replace(/\\/g, '/'));

    let professorUploadDoc; // To store the Mongoose document

    try {
        let existingUpload = await ProfessorUpload.findOne({
            course, subject, subjectCode, semester: parseInt(semester), year: parseInt(year), examType, sectionType
        });

        // --- Initial Client Response ---
        // The client gets a response quickly, and processing continues in the background.
        if (existingUpload) {
            existingUpload.studentScriptPaths.push(...studentScriptPaths);
            existingUpload.markModified('studentScriptPaths');
            // Optionally reset status if reprocessing is desired for student scripts
            // existingUpload.status = 'student_scripts_added_for_reprocessing';
            professorUploadDoc = await existingUpload.save();
            res.status(200).send({ message: 'Student scripts added to existing upload. Background processing continues.', uploadId: professorUploadDoc._id });
        } else {
            const newProfessorUpload = new ProfessorUpload({
                username: req.user.username,
                course, subject, subjectCode,
                semester: parseInt(semester),
                year: parseInt(year),
                examType,
                sectionType,
                questionPaper: questionPaperFilePath,
                bookAnswer: bookAnswerFilePath,
                studentScriptPaths: studentScriptPaths,
                processedJSON: {}, // Initialize processedJSON
                status: 'upload_received' // Initial status
            });
            professorUploadDoc = await newProfessorUpload.save();
            res.status(201).send({ message: 'Upload received. Background processing started.', uploadId: professorUploadDoc._id });
        }

        // --- Background Processing Starts Here ---
        const projectRootDir = path.join(__dirname, '..', '..');
        const pythonOptions = { cwd: projectRootDir, env: { ...process.env }, maxBuffer: 10 * 1024 * 1024 };
        const pythonScriptsDir = path.join(projectRootDir, 'backend', 'extract');

        // Step 1: Execute question_parser.py
        const questionParserScriptPath = path.join(pythonScriptsDir, 'question_parser.py').replace(/\\/g, '/');
        const relativePdfPathForPython = path.relative(projectRootDir, questionPaperFilePath).replace(/\\/g, '/');
        let parsedQuestionsData;

        try {
            console.log(`Node.js: Starting ${path.basename(questionParserScriptPath)} for doc ID ${professorUploadDoc._id}...`);
            professorUploadDoc.status = 'question_parsing_started';
            await professorUploadDoc.save();

            const { stdout: questionParserStdout } = await executePythonScript(
                questionParserScriptPath,
                [relativePdfPathForPython], // Argument for question_parser.py
                pythonOptions
            );
            parsedQuestionsData = JSON.parse(questionParserStdout.trim());
            professorUploadDoc.processedJSON = parsedQuestionsData;
            professorUploadDoc.status = 'questions_extracted';
            await professorUploadDoc.save();
            console.log(`Node.js: ${path.basename(questionParserScriptPath)} completed for doc ID ${professorUploadDoc._id}.`);

            // Step 2: Call Answer_from_book.py Flask API (http://localhost:5001)
            // This call is "fire-and-forget" in terms of the main flow here,
            // its success/failure is handled in its own .then/.catch.
            console.log(`Node.js: Calling Answer_from_book.py Flask API for doc ID ${professorUploadDoc._id}...`);
            const currentDocForFlask1 = await ProfessorUpload.findById(professorUploadDoc._id); // Re-fetch for fresh status
            if (currentDocForFlask1) {
                currentDocForFlask1.status = 'answer_book_processing_started';
                await currentDocForFlask1.save();
            }

            const relativeBookAnswerPathForFlask = path.relative(projectRootDir, bookAnswerFilePath).replace(/\\/g, '/');
            const relativeStudentScriptPathsForFlask = studentScriptPaths.map(p => path.relative(projectRootDir, p).replace(/\\/g, '/'));

            axios.post('http://localhost:5001/process-professor-data', {
                professorUploadId: professorUploadDoc._id.toString(),
                parsedQuestionData: parsedQuestionsData,
                questionPaperPath: relativePdfPathForPython,
                bookAnswerPath: relativeBookAnswerPathForFlask,
                course: professorUploadDoc.course,
                subject: professorUploadDoc.subject,
                subjectCode: professorUploadDoc.subjectCode,
                semester: professorUploadDoc.semester,
                year: professorUploadDoc.year,
                examType: professorUploadDoc.examType,
                sectionType: professorUploadDoc.sectionType,
                studentScriptPaths: relativeStudentScriptPathsForFlask
            }, { timeout: 15 * 60 * 1000 })
            .then(async apiResponse => {
                console.log(`Node.js: Answer_from_book.py Flask API call successful for ${professorUploadDoc._id}:`, apiResponse.data);
                const doc = await ProfessorUpload.findById(professorUploadDoc._id);
                if (doc) {
                    doc.status = 'answer_book_processing_completed'; // Or based on apiResponse.data
                    // Potentially update other fields based on apiResponse.data if needed
                    await doc.save();
                }
            })
            .catch(async apiError => {
                console.error(`Node.js: Answer_from_book.py Flask API error for ${professorUploadDoc._id}:`, apiError.message);
                if (apiError.response) console.error('Node.js: API Response Data (Answer_from_book):', apiError.response.data);
                const doc = await ProfessorUpload.findById(professorUploadDoc._id);
                if (doc) {
                    doc.status = 'answer_book_processing_failed';
                    doc.errorDetails = `Flask API (Answer_from_book.py) error: ${apiError.message}. ${apiError.response ? JSON.stringify(apiError.response.data) : ''}`;
                    await doc.save();
                }
            });

            // *** NEW STEP 3: Call studentScripts.py via its Flask API endpoint (http://localhost:6001) ***
            // This is also a "fire-and-forget" background task from the perspective of the main execution flow.
            console.log(`Node.js: Calling studentScripts.py (via Flask API) for doc ID ${professorUploadDoc._id}...`);
            const currentDocForFlask2 = await ProfessorUpload.findById(professorUploadDoc._id); // Re-fetch for fresh status
             if (currentDocForFlask2) {
                currentDocForFlask2.status = 'student_script_api_processing_started';
                await currentDocForFlask2.save();
            }

            axios.post('http://localhost:6001/process-professor-scripts', { // Ensure this is the correct port for python_api.py
                professorUploadId: professorUploadDoc._id.toString()
            }, { timeout: 30 * 60 * 1000 }) // Longer timeout if processing many scripts
            .then(async apiResponse => {
                console.log(`Node.js: studentScripts.py Flask API call successful for ${professorUploadDoc._id}:`, apiResponse.data);
                const doc = await ProfessorUpload.findById(professorUploadDoc._id);
                if (doc) {
                    // The Python script itself updates the 'students' array and 'processedAt'.
                    // We just update a status based on the API call's success.
                    doc.status = 'student_script_api_processing_completed';
                    // If python_api.py returns specific messages, you can add them.
                    // e.g., doc.lastMessageFromStudentScriptAPI = apiResponse.data.message;
                    await doc.save();
                }
            })
            .catch(async apiError => {
                console.error(`Node.js: studentScripts.py Flask API error for ${professorUploadDoc._id}:`, apiError.message);
                if (apiError.response) console.error('Node.js: API Response Data (studentScripts.py):', apiError.response.data);
                const doc = await ProfessorUpload.findById(professorUploadDoc._id);
                if (doc) {
                    doc.status = 'student_script_api_processing_failed';
                    doc.errorDetails = `Flask API (studentScripts.py) error: ${apiError.message}. ${apiError.response ? JSON.stringify(apiError.response.data) : ''}`;
                    await doc.save();
                }
            });

        } catch (pythonError) { // This catches errors specifically from executePythonScript (question_parser.py)
            console.error(`Node.js: Python script (question_parser.py) execution failed for doc ID ${professorUploadDoc._id}. Code:`, pythonError.code);
            console.error(`Node.js: Python stdout (question_parser.py):`, pythonError.stdout);
            console.error(`Node.js: Python stderr (question_parser.py):`, pythonError.stderr);

            // professorUploadDoc should be defined here
            professorUploadDoc.status = 'question_parsing_failed';
            professorUploadDoc.errorDetails = `Python (question_parser.py) error. Exit code: ${pythonError.code || 'N/A'}. Stderr: ${pythonError.stderr || (pythonError.error ? pythonError.error.message : 'Unknown Python error')}`;
            await professorUploadDoc.save();
        }
        
    } catch (dbError) { // This catches errors from the initial findOne or save operations
        console.error('Node.js: Database operation failed during professor upload:', dbError);
        if (!res.headersSent) { // Ensure response is sent only once
            res.status(500).send({ message: 'Server error during initial database operation.', error: dbError.message });
        }
        // If professorUploadDoc was created/found before the error, try to update its status
        if(professorUploadDoc && professorUploadDoc._id) {
            try {
                await ProfessorUpload.findByIdAndUpdate(professorUploadDoc._id, {
                    $set: { status: 'processing_error_db', errorDetails: `DB Error: ${dbError.message}` }
                });
            } catch (updateErr) {
                console.error('Node.js: Failed to update document status after a DB error:', updateErr);
            }
        }
    }
});

module.exports = router;