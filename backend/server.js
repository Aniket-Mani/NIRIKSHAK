

process.on('uncaughtException', (error, origin) => {
    console.error(`\n\n!!!!!! SERVER CRASHED (Uncaught Exception) !!!!!!`);
    console.error('Origin:', origin);
    console.error('Error Message:', error.message);
    console.error('Error Stack:', error.stack);
    process.exit(1);
  });
  
  process.on('unhandledRejection', (reason, promise) => {
    console.error(`\n\n!!!!!! SERVER CRASHED (Unhandled Rejection) !!!!!!`);
    console.error('Unhandled Rejection at Promise:', promise);
    console.error('Reason:', reason instanceof Error ? reason.stack : reason);
    process.exit(1);
  });


require('dotenv').config(); // Load environment variables at the very top

const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const jwt = require('jsonwebtoken');// // For verifyToken

// Import route files
const studentUploadRouter = require('./routes/student-upload'); //
const professorUploadRouter = require('./routes/professor-upload'); //
const authRoutes = require('./routes/authRoutes'); //
const userRoutes = require('./routes/userRoutes'); //
const courseSubjectRoutes = require('./routes/coursesubjects'); //
const resultsRoutes = require('./routes/resultsRoutes');
const admin = require('./routes/adminCourseRoutes');

const app = express();
const port = process.env.PORT || 3000; //

// --- Middleware ---
app.use(cors()); //
app.use(express.json()); //
app.use(express.urlencoded({ extended: true })); //

// --- Database Connection ---
const mongoURI = process.env.MONGODB_URI || 'mongodb://localhost:27017/smart'; //
mongoose.connect(mongoURI) // Removed deprecated options
  .then(() => console.log('Node.js: Connected to MongoDB at', mongoURI))
  .catch(err => console.error('Node.js: Could not connect to MongoDB:', err));

// --- Ensure Upload Folders Exist ---
// Relative to this file's directory (project/backend/)
const uploadDirectories = [
    path.join(__dirname, 'uploads', 'student'), // project/backend/uploads/student
    path.join(__dirname, 'uploads', 'professor') // project/backend/uploads/professor
];
uploadDirectories.forEach(dir => {
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
        console.log(`Node.js: Created upload directory: ${dir}`);
    }
}); //

// --- Static File Serving ---
// Serves files from the project root directory (one level above 'backend')
app.use(express.static(path.join(__dirname, '..'))); //

// --- Favicon Handler ---
app.get('/favicon.ico', (req, res) => res.status(204).end()); //

// --- Base Route ---
app.get('/', (req, res) => {
    res.send('Welcome to NIRIKSHAK API! Access frontend from the root.'); //
});

// --- API Routes ---
app.use('/api/uploads', studentUploadRouter); //
app.use('/api/uploads', professorUploadRouter); //
app.use('/api', authRoutes); //
app.use('/api', userRoutes); //
app.use('/api', courseSubjectRoutes); //
app.use('/api/results', resultsRoutes);
app.use('/api', admin);


app.listen(port, () => {
    console.log(`Node.js: Server running at http://localhost:${port}`); //
    console.log(`Node.js: To access frontend, open http://127.0.0.1:${port}/login.html (e.g., home.html)`); //
});

module.exports = { app };