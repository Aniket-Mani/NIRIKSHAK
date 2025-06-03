




const mongoose = require('mongoose');

// Define the schema for professor uploads.
// This schema stores information about question papers, book answers,
// associated student scripts, and the processing status/results.
const professorUploadSchema = new mongoose.Schema({
    // Username of the professor who uploaded the files
    username: {
        type: String,
        required: true,
        trim: true
    },
    // Course name (e.g., "B.Tech", "M.Sc")
    course: {
        type: String,
        required: true,
        trim: true
    },
    // Subject name (e.g., "Data Structures", "Operating Systems")
    subject: {
        type: String,
        required: true,
        trim: true
    },
    // Subject code (e.g., "CS201", "MA101")
    subjectCode: {
        type: String,
        required: true,
        trim: true
    },
    // Semester number (e.g., 1, 2, 3...)
    semester: {
        type: Number,
        required: true,
        min: 1
    },
    // Academic year of the exam
    year: {
        type: Number,
        required: true,
        min: 1900,
        max: 2100
    },
    // Type of exam (e.g., "CT1", "CT2", "FAT")
    examType: {
        type: String,
        required: true,
        enum: ['CT1', 'CT2', 'FAT']
    },
    sectionType: {
        type: String,
        required: true,
        enum: ['A', 'B']
    },
    // Path to the uploaded question paper file on the server
    questionPaper: {
        type: String,
        required: true
    },
    // Path to the uploaded book answer file on the server
    bookAnswer: {
        type: String,
        required: true
    },
    // Array of paths to associated student answer script files
    studentScriptPaths: {
        type: [String], // Array of strings
        default: [],
        required:false
    },
    // Object to store JSON results from processing (e.g., question parsing, answer generation)
    // This will hold the output from your Python scripts and their status.
    processedJSON: {
        type: Object,
        default: {}
    },
    students: {
        type: [{ // Defines an array of student data objects
            roll_no: {
                type: String,
                required: true, // Roll number is essential for identifying a student's answers
                trim: true
            },
            answers: {
                type: [{ // Each student has an array of answer objects
                    question_no: {
                        type: String, // Or Number, based on how you identify questions
                        required: true
                    },
                    answer_text: {
                        type: String,
                        required: true
                    }
                }],
                default: [] // A student might not have any answers processed yet, or no answers at all
            }
        }],
        default: [] // The main students array defaults to empty; populated by your Python script
    },
    // Timestamp when the record was created/uploaded
    uploadedAt: {
        type: Date,
        default: Date.now
    }
});

// Create and export the Mongoose model for ProfessorUpload.
// This model allows you to interact with the 'professoruploads' collection in MongoDB.
module.exports = mongoose.model('ProfessorUpload', professorUploadSchema);