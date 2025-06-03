// backend/models/courseSubjectSchema.js
const mongoose = require('mongoose');

const courseSubjectSchema = new mongoose.Schema({
    course: String,
    semester: Number,
    subject: String,
    subjectCode: String
}, { collection: 'coursesubjects' });

module.exports = courseSubjectSchema;