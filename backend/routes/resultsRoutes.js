









// backend/routes/resultsRoutes.js
const express = require('express');
const path = require('path');
const { exec } = require('child_process');
const mongoose = require('mongoose');
const { authenticateToken, authorizeRoles } = require('../middleware/authMiddleware'); // Ensure path is correct
const ProfessorUpload = require('../models/ProfessorUpload'); // For the status endpoint

const router = express.Router();

let individualResultsBucket; // For 'results_marksheets'
let classAggregateBucket;  // For 'class_aggregate_reports'

const initializeGridFSBuckets = () => {
    if (mongoose.connection.readyState === 1) {
        try {
            if (!individualResultsBucket) {
                individualResultsBucket = new mongoose.mongo.GridFSBucket(mongoose.connection.db, {
                    bucketName: 'results_marksheets'
                });
                console.log('Node.js (Results Route): GridFSBucket for "results_marksheets" initialized.');
            }
            if (!classAggregateBucket) {
                classAggregateBucket = new mongoose.mongo.GridFSBucket(mongoose.connection.db, {
                    bucketName: 'class_aggregate_reports'
                });
                console.log('Node.js (Results Route): GridFSBucket for "class_aggregate_reports" initialized.');
            }
        } catch (error) {
            console.error('Node.js (Results Route): Error initializing GridFSBuckets:', error);
            // Reset on error so initialization can be retried
            if (error.message.includes('results_marksheets')) individualResultsBucket = null;
            if (error.message.includes('class_aggregate_reports')) classAggregateBucket = null;
        }
    } else {
        console.warn('Node.js (Results Route): MongoDB connection not ready for GridFS init when initializeGridFSBuckets was called.');
    }
};

// Initialize GridFS buckets when MongoDB connection is ready
if (mongoose.connection.readyState === 1) {
    initializeGridFSBuckets();
} else {
    mongoose.connection.once('open', initializeGridFSBuckets);
    // Also handle re-initialization on reconnect if buckets are not set
    mongoose.connection.on('connected', () => {
        if (!individualResultsBucket || !classAggregateBucket) {
            console.log('Node.js (Results Route): Re-initializing GridFS buckets on reconnect.');
            initializeGridFSBuckets();
        }
    });
}

// Consolidated function for executing Python scripts
const executePythonScript = (scriptName, scriptPath, args, options) => {
    return new Promise((resolve, reject) => {
        const pythonCmd = process.env.PYTHON_COMMAND || 'python3'; // Default to python3
        const command = `"${pythonCmd}" "${scriptPath}" ${args.map(a => `"${String(a)}"`).join(' ')}`;

        console.log(`Node.js (Results Route): Executing Python (${scriptName}): ${command}`);
        console.log(`Node.js (Results Route): Python CWD (${scriptName}): ${options.cwd}`);

        exec(command, options, (error, stdout, stderr) => {
            if (error) {
                console.error(`Node.js (Results Route) exec error for ${scriptName}: ${error.message}`);
                console.error(`Node.js (Results Route) Python stderr (on error for ${scriptName}): ${stderr}`);
                return reject({
                    message: `Python script (${scriptName}) execution failed.`,
                    errorDetails: error.message,
                    stderr,
                    stdout, // stdout might also contain error info from Python
                    code: error.code
                });
            }
            if (stderr) {
                // Some Python warnings or progress might go to stderr
                console.warn(`Node.js (Results Route) Python stderr (non-fatal/progress for ${scriptName}): ${stderr}`);
            }
            resolve({ stdout, stderr });
        });
    });
};

// --- Endpoint for Individual Student Result (student.html) ---
// This route should also be protected if it's not public
router.post('/student-result', authenticateToken, async (req, res) => { // Added authenticateToken
    let { rollNo, subjectCode, examType, year, semester, course, sectionType } = req.body;

    if (!rollNo) {
        return res.status(400).json({ message: "Bad Request: Student roll number is required." });
    }
    if (!subjectCode || !examType || !year || !semester || !course || !sectionType) {
        return res.status(400).json({ message: 'Missing required exam criteria: course, subjectCode, examType, year, semester, or sectionType.' });
    }

    try {
        rollNo = String(rollNo).trim();
        subjectCode = String(subjectCode).trim();
        examType = String(examType).trim();
        course = String(course).trim();
        sectionType = String(sectionType).trim();
        const numYear = parseInt(year);
        const numSemester = parseInt(semester);

        if (isNaN(numYear) || isNaN(numSemester)) {
            return res.status(400).json({ message: "Year and Semester must be valid numbers."});
        }
        year = numYear;
        semester = numSemester;
    } catch (inputError) {
        console.error("Node.js (Student Result): Error processing input fields:", inputError);
        return res.status(400).json({ message: "Invalid input data format."});
    }

    const projectRootDir = path.join(__dirname, '..', '..');
    const marksheetGeneratorScriptPath = path.join(projectRootDir, 'backend', 'extract', 'Marksheet_Generator.py').replace(/\\/g, '/');
    const pythonOptions = {
        cwd: projectRootDir,
        env: { ...process.env },
        maxBuffer: 15 * 1024 * 1024
    };

    const scriptArgs = [
        "--roll_no", rollNo,
        "--course", course,
        "--subject_code", subjectCode,
        "--exam_type", examType,
        "--year", String(year),
        "--semester", String(semester),
        "--section", sectionType,
        "--mode", "student"
    ];

    try {
        const { stdout, stderr: pythonStderr } = await executePythonScript("Marksheet_Generator.py", marksheetGeneratorScriptPath, scriptArgs, pythonOptions);
        let pythonResult;
        if (!stdout || stdout.trim() === "") {
            throw {
                message: "Python script (Marksheet_Generator.py) produced no parsable output to stdout.",
                stderr: pythonStderr || "No stderr output.",
                stdout: stdout
            };
        }
        try {
            pythonResult = JSON.parse(stdout.trim());
        } catch (parseError) {
            console.error('Node.js (Student Result): Failed to parse Marksheet_Generator.py stdout as JSON:', parseError);
            console.error('Node.js (Student Result): Python stdout that failed parsing:', stdout);
            throw {
                message: `Failed to parse Marksheet_Generator.py script output. Raw stdout: ${stdout.substring(0, 500)}...`,
                stderr: pythonStderr || "No stderr output.",
                stdout: stdout
            };
        }

        console.log('Node.js (Student Result): Marksheet_Generator.py output successfully parsed:', pythonResult);
        if (pythonResult.status && pythonResult.status.startsWith('success')) {
            res.status(200).json(pythonResult);
        } else {
            let statusCode = 500;
            const statusFromPython = pythonResult.status;
            if (statusFromPython === 'error_professor_data_missing' || statusFromPython === 'error_student_data_missing') statusCode = 404;
            else if (statusFromPython === 'error_student_extraction_incomplete' || statusFromPython === 'error_scoring_failed' || statusFromPython === 'error_pdf_generation_failed' || statusFromPython === 'error_cli_value') statusCode = 422;
            const message = pythonResult.message || "Marksheet_Generator.py script reported an error.";
            console.warn(`Node.js (Student Result): Marksheet_Generator.py reported non-success: Status ${statusCode}, Message: ${message}`);
            res.status(statusCode).json({ message: message, details: pythonResult.details || pythonResult });
        }
    } catch (error) {
        console.error('Node.js (Student Result): Error during Marksheet_Generator.py execution or parsing:', error);
        const errorMessage = error.message || (error.errorDetails ? `Python Script Error: ${error.errorDetails}` : "Unknown server error during result generation.");
        res.status(500).json({
            message: errorMessage,
            errorDetails: error.stderr || error.message || "Unknown execution error from Python script.",
            stdout: error.stdout,
            code: error.code
        });
    }
});

// --- Endpoint for Combined Class Results (Professor.html) ---
router.post('/combined-class-result', authenticateToken, authorizeRoles(['professor']), async (req, res) => {
    let { course, subjectCode, examType, year, semester, sectionType } = req.body;

    if (!subjectCode || !examType || !year || !semester || !course || !sectionType) {
        return res.status(400).json({ message: 'Missing required exam criteria: course, subjectCode, examType, year, semester, or sectionType.' });
    }

    try {
        course = String(course).trim();
        subjectCode = String(subjectCode).trim();
        examType = String(examType).trim();
        sectionType = String(sectionType).trim();
        const numYear = parseInt(year);
        const numSemester = parseInt(semester);

        if (isNaN(numYear) || isNaN(numSemester)) {
            return res.status(400).json({ message: "Year and Semester must be valid numbers."});
        }
        year = numYear;
        semester = numSemester;
    } catch (inputError) {
        console.error("Node.js (Combined Result): Error processing input fields:", inputError);
        return res.status(400).json({ message: "Invalid input data format."});
    }
    
    // Step 1: Find the ProfessorUpload document to get its ID for polling
    const profCriteriaQuery = { course, subjectCode, examType, year, semester, sectionType };
    let profUploadDoc;
    try {
        profUploadDoc = await ProfessorUpload.findOne(profCriteriaQuery).select('_id').lean(); // .lean() for plain JS object
        if (!profUploadDoc) {
            return res.status(404).json({ message: "No matching professor upload found for these criteria. Please ensure files were submitted first and all criteria match an existing record." });
        }
    } catch (dbError) {
        console.error("Node.js (Combined Result): DB error finding ProfessorUpload:", dbError);
        return res.status(500).json({ message: "Server error finding exam record." });
    }
    
    const professorUploadIdForPolling = profUploadDoc._id.toString();

    const projectRootDir = path.join(__dirname, '..', '..');
    const combinedResultsScriptPath = path.join(projectRootDir, 'backend', 'extract', 'Combined_Results.py').replace(/\\/g, '/');
    const pythonOptions = {
        cwd: projectRootDir,
        env: { ...process.env },
        maxBuffer: 25 * 1024 * 1024 
    };

    const scriptArgs = [
        "--course", course,
        "--subject_code", subjectCode,
        "--exam_type", examType,
        "--year", String(year),
        "--semester", String(semester),
        "--section", sectionType
    ];

    try {
        console.log(`Node.js (Combined Result): Initiating Combined_Results.py for ProfUploadID ${professorUploadIdForPolling} with args: ${scriptArgs.join(' ')}`);
        
        exec(`"${process.env.PYTHON_COMMAND || 'python3'}" "${combinedResultsScriptPath}" ${scriptArgs.map(a => `"${String(a)}"`).join(' ')}`,
            pythonOptions,
            (error, stdout, stderr) => {
                if (error) {
                    console.error(`Node.js (Combined Result Background) exec error for Combined_Results.py (ProfUploadID: ${professorUploadIdForPolling}): ${error.message}`);
                    console.error(`Node.js (Combined Result Background) Python stderr for Combined_Results.py: ${stderr}`);
                    // Optionally, update the ProfessorUpload document to reflect this failure
                     ProfessorUpload.findByIdAndUpdate(professorUploadIdForPolling, {
                        $set: {
                            combinedResultGenerationStatus: "error_script_execution",
                            combinedResultErrorMessage: `Python script execution failed: ${error.message}. Stderr: ${stderr.substring(0,500)}`,
                            combinedResultProcessedAt: new Date()
                        }
                    }).catch(err => console.error("Error updating prof upload on script failure:", err));
                    return;
                }
                if (stderr) {
                    console.warn(`Node.js (Combined Result Background) Python stderr (non-fatal for Combined_Results.py, ProfUploadID: ${professorUploadIdForPolling}): ${stderr}`);
                }
                console.log(`Node.js (Combined Result Background) Python stdout for Combined_Results.py (ProfUploadID: ${professorUploadIdForPolling}): ${stdout}`);
                // The Python script itself should be updating the ProfessorUpload document upon its completion or detailed errors.
            }
        );

        res.status(202).json({ 
            message: 'Combined class result generation initiated. Polling for status will begin.',
            professorUploadId: professorUploadIdForPolling 
        });

    } catch (error) { 
        console.error('Node.js (Combined Result): Error during Combined_Results.py execution or setup:', error);
        res.status(500).json({
            message: "Failed to initiate combined result generation due to a server-side setup error.",
            errorDetails: error.message || "Unknown server error."
        });
    }
});

// --- Endpoint to check status of combined class result generation ---
router.get('/combined-class-status/:profUploadId', authenticateToken, authorizeRoles(['professor']), async (req, res) => {
    try {
        const { profUploadId } = req.params;
        if (!mongoose.Types.ObjectId.isValid(profUploadId)) {
            return res.status(400).json({ message: "Invalid Professor Upload ID format." });
        }

        const profUpload = await ProfessorUpload.findById(profUploadId)
            .select('combinedResultGenerationStatus combinedClassResultPdfGridFsId combinedClassResultCsvGridFsId combinedResultErrorMessage combinedResultStudentProcessedCount combinedResultStudentFailedOrSkippedCount uploadedAt subject examType') // Added some more fields for context
            .lean(); 

        if (!profUpload) {
            return res.status(404).json({ message: "Professor upload record not found." });
        }
        res.status(200).json({
            status: profUpload.combinedResultGenerationStatus || "pending",
            message: profUpload.combinedResultErrorMessage || "Status fetched successfully.",
            pdfId: profUpload.combinedClassResultPdfGridFsId,
            csvId: profUpload.combinedClassResultCsvGridFsId,
            studentsProcessed: profUpload.combinedResultStudentProcessedCount,
            studentsFailed: profUpload.combinedResultStudentFailedOrSkippedCount,
            examDetails: { // Provide some context back to the frontend
                subject: profUpload.subject,
                examType: profUpload.examType,
                uploadedAt: profUpload.uploadedAt
            }
        });
    } catch (error) {
        console.error("Node.js (Combined Status): Error fetching status:", error);
        res.status(500).json({ message: "Server error while fetching combined result status." });
    }
});


// --- Endpoint to Download Generated Files (tries both buckets) ---
router.get('/download/:fileId', async (req, res) => {                  
    if (!individualResultsBucket || !classAggregateBucket) {
        initializeGridFSBuckets(); 
        if (!individualResultsBucket || !classAggregateBucket) { 
            console.error('Node.js (Download): GridFSBuckets critically not initialized.');
            return res.status(503).send('Server error: File storage system is not ready. Please try again later.'); 
        }
    }
    try {
        const fileIdString = req.params.fileId;
        if (!mongoose.Types.ObjectId.isValid(fileIdString)) { 
            return res.status(400).json({ message: 'Invalid file ID format provided.' }); 
        }
        const fileId = new mongoose.Types.ObjectId(fileIdString);
        
        let files = await individualResultsBucket.find({ _id: fileId }).limit(1).toArray();
        let targetBucket = individualResultsBucket;
        let fileSourceBucketName = "results_marksheets";

        if (!files || files.length === 0) { 
            console.log(`Node.js (Download): File ${fileIdString} not in 'results_marksheets', trying 'class_aggregate_reports'.`);
            files = await classAggregateBucket.find({ _id: fileId }).limit(1).toArray();
            targetBucket = classAggregateBucket;
            fileSourceBucketName = "class_aggregate_reports";
        }

        if (!files || files.length === 0) { 
            console.warn(`Node.js (Download): File with ID ${fileIdString} not found in any configured GridFS bucket.`);
            return res.status(404).json({ message: 'File not found. It might have been deleted or the ID is incorrect.' });
        }
        const fileInfo = files[0];
        console.log(`Node.js (Download): Found file ${fileInfo.filename} (ID: ${fileIdString}) in bucket '${fileSourceBucketName}'.`);


        const cleanFilename = path.basename(fileInfo.filename || `file-${fileIdString}.${fileInfo.contentType === 'text/csv' ? 'csv' : 'pdf'}`).replace(/[^a-zA-Z0-9._-]/g, '_');

        res.set({
            'Content-Type': fileInfo.contentType || 'application/octet-stream', 
            'Content-Disposition': `inline; filename="${cleanFilename}"`, 
        });
        const downloadStream = targetBucket.openDownloadStream(fileId);
        
        downloadStream.on('error', (streamErr) => {
            console.error(`Node.js (Download): Error streaming file from GridFS (bucket: ${fileSourceBucketName}) for fileId ${fileIdString}:`, streamErr);
            if (!res.headersSent) { 
                res.status(500).send('Error occurred while retrieving the file content from storage.');
            } else { 
                res.end(); 
            }
        });
        downloadStream.on('finish', () => {
            console.log(`Node.js (Download): Successfully streamed file ${fileInfo.filename} (ID: ${fileIdString}) from bucket '${fileSourceBucketName}' to client.`);
        });
        downloadStream.pipe(res);

    } catch (err) {
        console.error('Node.js (Download): General error in download route for fileId ' + req.params.fileId + ':', err);
        if (!res.headersSent) { 
            res.status(500).send('Server error occurred while trying to prepare the file for download.');
        }
    }
});

module.exports = router;