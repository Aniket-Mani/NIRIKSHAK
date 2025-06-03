
const express = require('express');
const router = express.Router();
const mongoose = require('mongoose');
const courseSubjectSchema = require('../models/courseSubjectSchema'); // Adjust path as needed

// Get the CourseSubject model using the defined schema.
const CourseSubject = mongoose.model('CourseSubject', courseSubjectSchema);

// --- ADMIN PANEL SPECIFIC API ENDPOINTS ---

// GET /admin/courses/unique-names - Get all unique course names for the admin filter dropdown
router.get('/admin/courses/unique-names', async (req, res) => {
    try {
        const courses = await CourseSubject.distinct('course');
        // Trim each course name and then get distinct values (case-sensitive)
        const trimmedCourses = [...new Set(courses.map(c => c.trim()))];
        res.status(200).json(trimmedCourses.sort());
    } catch (err) {
        console.error('Error fetching unique course names for admin:', err);
        res.status(500).json({ message: 'Server error fetching unique course names.' });
    }
});

// GET /admin/courses/semesters-by-course/:course - Get unique semesters for a given course for the admin filter dropdown
router.get('/admin/courses/semesters-by-course/:course', async (req, res) => {
    const { course } = req.params;
    try {
        if (!course) {
            return res.status(400).json({ message: 'Course parameter is required.' });
        }
        const trimmedCourse = course.trim();
        const uniqueSemesters = await CourseSubject.distinct('semester', { course: trimmedCourse });
        res.status(200).json(uniqueSemesters.sort((a, b) => a - b));
    } catch (err) {
        console.error('Error fetching semesters for admin:', err);
        res.status(500).json({ message: 'Server error fetching semesters.' });
    }
});

// GET /admin/courses/all-details - Get all course details (with optional filtering by course and semester)
router.get('/admin/courses/all-details', async (req, res) => {
    try {
        const { course, semester } = req.query; // Extract query parameters
        let query = {};

        if (course) {
            query.course = course.trim(); // Filter by course, ensure trimmed
        }
        if (semester) {
            query.semester = Number(semester); // Filter by semester, ensure it's a number
        }

        const courses = await CourseSubject.find(query); // Apply the constructed query
        res.status(200).json(courses);
    } catch (err) {
        console.error('Error fetching course details for admin table:', err);
        res.status(500).json({ message: 'Server error fetching course details.' });
    }
});

// POST /admin/courses/add - Add new course structure
router.post('/admin/courses/add', async (req, res) => {
    console.log('Received request body:', req.body);

    try {
        // Changed 'subjectName' to 'subject' to match the key sent from the frontend
        const { course, semester, subject, subjectCode } = req.body; 

        // Basic validation for required fields
        // Now checks for 'subject' instead of 'subjectName'
        if (!course || !semester || !subject || !subjectCode) { 
            return res.status(400).json({ message: 'All fields are required.' });
        }

        const newCourse = new CourseSubject({
            course: course.trim(),
            semester: Number(semester),
            subject: subject.trim(), // Using 'subject' here, which now correctly holds the value
            subjectCode: subjectCode.trim()
        });

        const savedCourse = await newCourse.save();
        console.log('Course saved successfully:', savedCourse); // Added for debugging
        res.status(201).json({
            message: 'Course added successfully',
            course: savedCourse
        });
    } catch (err) {
        console.error('Error adding course:', err);
        if (err.code === 11000) {
            return res.status(409).json({ message: 'Subject code already exists. Please use a unique subject code.' });
        }
        console.error('Full save error:', err); // Added for debugging
        res.status(500).json({ message: err.message || 'Server error during course addition.' });
    }
});

// DELETE /admin/courses/delete - Delete course(s) by IDs
router.delete('/admin/courses/delete', async (req, res) => {
    try {
        const { ids } = req.body;
        if (!ids || !Array.isArray(ids) || ids.length === 0) {
            return res.status(400).json({ message: 'Please provide an array of course IDs to delete.' });
        }

        const result = await CourseSubject.deleteMany({ _id: { $in: ids } });

        if (result.deletedCount > 0) {
            res.json({
                message: `Deleted ${result.deletedCount} course(s) successfully`
            });
        } else {
            res.status(404).json({ message: 'No courses found with the provided IDs.' });
        }
    } catch (err) {
        console.error('Error deleting courses:', err);
        res.status(500).json({ message: err.message || 'Server error during course deletion.' });
    }
});

module.exports = router;