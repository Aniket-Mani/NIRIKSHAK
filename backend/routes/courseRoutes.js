const express = require('express');
const router = express.Router();
const CourseSubject = require('../models/CourseSubject');

router.get('/courses', async (req, res) => {
  try {
    const courses = await CourseSubject.find();
    res.json(courses);
  } catch (err) {
    res.status(500).json({ message: "Failed to fetch courses" });
  }
});

module.exports = router;
