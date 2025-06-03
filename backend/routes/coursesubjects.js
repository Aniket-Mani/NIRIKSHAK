


const express = require('express');
const router = express.Router();
const mongoose = require('mongoose');
const courseSubjectSchema = require('../models/courseSubjectSchema'); /// Import the schema

// Model
const CourseSubject = mongoose.model('CourseSubject', courseSubjectSchema);

// ----------------------------------------
// GET /api/courses - Get all unique courses
router.get('/courses', async (req, res) => {
    try {
        const courses = await CourseSubject.distinct('course');
        res.json(courses);
    } catch (err) {
        res.status(500).json({ error: 'Error fetching courses' });
    }
});

// ----------------------------------------
// GET /api/semesters?course=XYZ - Get semesters for a course
router.get('/semesters', async (req, res) => {
    const { course } = req.query;
    try {
        const semesters = course
            ? await CourseSubject.find({ course }).distinct('semester')
            : await CourseSubject.distinct('semester');
        res.json(semesters);
    } catch (err) {
        res.status(500).json({ error: 'Error fetching semesters' });
    }
});

// ----------------------------------------
// GET /api/subjects?course=XYZ&semester=1 - Get subject names
router.get('/subjects', async (req, res) => {
    const { course, semester } = req.query;
    if (!course || !semester) {
        return res.status(400).json({ error: 'course and semester are required' });
    }

    try {
        const subjects = await CourseSubject.find({
            course,
            semester: Number(semester)
        }).select('subject subjectCode -_id');

        const response = subjects.map(s => ({
            name: s.subject,
            code: s.subjectCode
        }));

        res.json(response);
    } catch (err) {
        res.status(500).json({ error: 'Error fetching subjects' });
    }
});

// ----------------------------------------
// GET /api/subject-codes?course=XYZ&semester=1&subject=ABC
router.get('/subject-codes', async (req, res) => {
    const { course, semester, subject } = req.query;
    if (!course || !semester || !subject) {
        return res.status(400).json({ error: 'course, semester, and subject are required' });
    }

    try {
        const record = await CourseSubject.findOne({
            course,
            semester: Number(semester),
            subject
        });

        if (!record) {
            return res.status(404).json({ error: 'No subject code found' });
        }

        res.json([record.subjectCode]);
    } catch (err) {
        res.status(500).json({ error: 'Error fetching subject code' });
    }
});

module.exports = router;