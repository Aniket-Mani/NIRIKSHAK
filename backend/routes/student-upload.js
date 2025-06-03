

const express = require('express');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const StudentUpload = require('../models/StudentUpload');
const axios = require('axios');
const { authenticateToken, authorizeRoles } = require('../middleware/authMiddleware');

const router = express.Router();

// Define the Python API URL as a constant for easy modification and clarity
// Ensure this port matches exactly what your Python API is running on.
const PYTHON_API_URL_STRING = 'http://localhost:6001/process-student-upload';
let PYTHON_API_URL_VALIDATED;

// Validate the Python API URL at startup
try {
    PYTHON_API_URL_VALIDATED = new URL(PYTHON_API_URL_STRING);
    console.log(`Node.js (student-upload): Python API URL configured and validated: ${PYTHON_API_URL_VALIDATED.href}`);
} catch (urlError) {
    console.error(`Node.js (student-upload) CRITICAL ERROR: Invalid Python API URL string: "${PYTHON_API_URL_STRING}"`);
    console.error(`Node.js (student-upload) URL Parsing Error: ${urlError.message}`);
    // If the URL is invalid at startup, we can't proceed with calls to it.
    // You might choose to throw an error here to prevent the app from starting with a bad config,
    // or handle it gracefully in the route if preferred. For now, it will fail in the route.
    PYTHON_API_URL_VALIDATED = null; // Mark as invalid
}

// Configure Multer for file storage
const studentStorage = multer.diskStorage({
    destination: (req, file, cb) => {
        const uploadDir = path.join(__dirname, '..', 'uploads', 'student');
        // console.log(`Node.js (student-upload) Multer Destination Path: ${uploadDir}`); // Can be verbose

        if (!fs.existsSync(uploadDir)) {
            try {
                fs.mkdirSync(uploadDir, { recursive: true });
                console.log(`Node.js (student-upload) ✔ Created upload directory: ${uploadDir}`);
            } catch (mkdirErr) {
                console.error(`Node.js (student-upload) ⛔ ERROR: Failed to create upload directory ${uploadDir}:`, mkdirErr);
                return cb(new Error(`Failed to create upload directory: ${mkdirErr.message}`));
            }
        }
        cb(null, uploadDir);
    },
    filename: (req, file, cb) => {
        const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
        const fileExtension = path.extname(file.originalname);
        const newFilename = file.fieldname + '-' + uniqueSuffix + fileExtension;
        // console.log(`Node.js (student-upload) Multer Generated Filename: ${newFilename}`); // Can be verbose
        cb(null, newFilename);
    }
});

const studentUpload = multer({
    storage: studentStorage,
    fileFilter: (req, file, cb) => {
        // Example file filter (optional): Allow only PDFs and common image types
        if (file.mimetype === 'application/pdf' || file.mimetype.startsWith('image/')) {
            cb(null, true);
        } else {
            console.warn(`Node.js (student-upload) ⚠ WARNING: Invalid file type uploaded: ${file.mimetype} for ${file.originalname}`);
            cb(new Error('Invalid file type. Only PDF and images are allowed.'), false);
        }
    }
});

// POST /api/uploads/student
router.post(
    '/student',
    authenticateToken,
    authorizeRoles(['student']),
    studentUpload.single('answerScript'), // Multer middleware for single file upload
    async (req, res) => {
        console.log('Node.js (student-upload) --- Student Upload Request Received ---');
        console.log('Node.js (student-upload) Request Body:', req.body); // Submitted form fields
        console.log('Node.js (student-upload) Authenticated User (from JWT):', req.user.username, 'Role:', req.user.role);

        if (!req.file) {
            console.error('Node.js (student-upload) ⛔ ERROR: No answer script file provided by client.');
            return res.status(400).json({ message: 'No answer script file provided.' }); // Send JSON response
        }

        console.log('Node.js (student-upload) Multer req.file object:', {
            fieldname: req.file.fieldname,
            originalname: req.file.originalname,
            mimetype: req.file.mimetype,
            destination: req.file.destination,
            filename: req.file.filename,
            path: req.file.path,
            size: req.file.size
        });

        let newUpload; // To store the mongoose document

        try {
            newUpload = new StudentUpload({
                username: req.user.username,
                course: req.body.course,
                subject: req.body.subject,
                subjectCode: req.body.subjectCode,
                semester: req.body.semester,
                year: req.body.year,
                examType: req.body.examType,
                sectionType: req.body.sectionType,
                filePath: req.file.path, // Path where Multer saved the file
                extractedAnswer: { status: 'pending', timestamp: new Date() }
            });

            await newUpload.save();
            const studentUploadId = newUpload._id.toString();

            console.log(`Node.js (student-upload) ✔ Student script metadata saved to DB. Document ID: ${studentUploadId}`);

            if (!PYTHON_API_URL_VALIDATED) {
                console.error('Node.js (student-upload) ⛔ CRITICAL ERROR: Python API URL is not configured or invalid. Cannot call Python API.');
                // Update DB record to reflect this configuration error
                await StudentUpload.findByIdAndUpdate(studentUploadId, {
                    $set: {
                        'extractedAnswer.status': 'config_error_python_url_invalid',
                        'extractedAnswer.error': 'Python API URL is not configured or invalid on Node.js server.',
                        'extractedAnswer.timestamp': new Date(),
                    }
                });
                return res.status(500).json({ // Send JSON response
                    message: 'Server configuration error: Python API URL is invalid. Please contact admin.',
                    uploadId: studentUploadId
                });
            }

            console.log(`Node.js (student-upload) Attempting to call Python API at [${PYTHON_API_URL_VALIDATED.href}] for processing upload ID: ${studentUploadId}`);

            try {
                const pythonApiResponse = await axios.post(PYTHON_API_URL_VALIDATED.href, {
                    studentUploadId: studentUploadId
                });

                console.log('Node.js (student-upload) Python API raw response status:', pythonApiResponse.status);
                console.log('Node.js (student-upload) Python API raw response data:', pythonApiResponse.data);

                if (pythonApiResponse.status === 200 && pythonApiResponse.data && pythonApiResponse.data.status === 'success') {
                    await StudentUpload.findByIdAndUpdate(studentUploadId, {
                        $set: {
                            'extractedAnswer.status': 'extraction_completed_via_api',
                            'extractedAnswer.message': pythonApiResponse.data.message,
                            'extractedAnswer.timestamp': new Date(),
                        }
                    });
                    console.log(`Node.js (student-upload) ✔ Successfully processed by Python API for ${studentUploadId}`);
                    return res.status(201).json({ // Send JSON response
                        message: 'Student script uploaded successfully. Answer extraction initiated via API.',
                        uploadId: studentUploadId,
                        pythonStatus: pythonApiResponse.data.message
                    });
                } else {
                    const errorMessage = pythonApiResponse.data ? (pythonApiResponse.data.message || JSON.stringify(pythonApiResponse.data)) : `Python API returned status ${pythonApiResponse.status}`;
                    console.error(`Node.js (student-upload) ⚠ Python API reported an issue for ${studentUploadId}:`, errorMessage);
                    await StudentUpload.findByIdAndUpdate(studentUploadId, {
                        $set: {
                            'extractedAnswer.status': 'extraction_failed_via_api',
                            'extractedAnswer.error': `Python API Issue: ${errorMessage}`,
                            'extractedAnswer.timestamp': new Date(),
                        }
                    });
                    return res.status(500).json({ // Send JSON response
                        message: 'Student script uploaded, but Python processing reported an issue.',
                        uploadId: studentUploadId,
                        pythonError: errorMessage
                    });
                }

            } catch (apiError) {
                console.error(`Node.js (student-upload) ⛔ ERROR communicating with Python API for ${studentUploadId}: ${apiError.message}`);
                if (apiError.isAxiosError) {
                    console.error('Node.js (student-upload) Axios error - Config:', JSON.stringify(apiError.config, null, 2));
                    if (apiError.response) {
                        console.error('Node.js (student-upload) Axios error - Response Status:', apiError.response.status);
                        console.error('Node.js (student-upload) Axios error - Response Data:', JSON.stringify(apiError.response.data, null, 2));
                    } else if (apiError.request) {
                        console.error('Node.js (student-upload) Axios error - No response received, Request details:', apiError.request);
                    }
                } else {
                     console.error('Node.js (student-upload) Non-Axios error details:', apiError);
                }

                if (newUpload && newUpload._id) { // Ensure newUpload exists before trying to update
                    await StudentUpload.findByIdAndUpdate(studentUploadId, { // Use studentUploadId which is confirmed
                        $set: {
                            'extractedAnswer.status': 'api_call_failed',
                            'extractedAnswer.error': apiError.message,
                            'extractedAnswer.timestamp': new Date(),
                        }
                    });
                }
                return res.status(500).json({ // Send JSON response
                    message: 'Server error: Failed to communicate with Python processing API.',
                    error: apiError.message,
                    details: apiError.isAxiosError && apiError.response ? apiError.response.data : 'No additional details from Python API response.'
                });
            }

        } catch (err) {
            console.error('Node.js (student-upload) ⛔ CRITICAL ERROR during file upload processing or DB save:', err.stack);
            // Check if the response has already been sent, which can happen if Multer calls cb(error)
            // and Express default error handler sends a response before this catch block.
            if (!res.headersSent) {
                return res.status(500).json({ // Send JSON response
                    message: 'Server error during upload or DB save.',
                    error: err.message
                });
            }
        }
    }
);

// Handle Multer errors specifically (e.g., file type error from fileFilter)
router.use((err, req, res, next) => {
    if (err instanceof multer.MulterError) {
        console.error("Node.js (student-upload) MulterError:", err);
        return res.status(400).json({ message: `File upload error: ${err.message}`, field: err.field });
    } else if (err) { // Other errors that might have been passed to next(err)
        console.error("Node.js (student-upload) General error in student upload route:", err);
        return res.status(500).json({ message: "Server error processing request.", error: err.message });
    }
    next();
});


module.exports = router;