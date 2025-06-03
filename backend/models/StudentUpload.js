


const mongoose = require('mongoose');

const studentUploadSchema = new mongoose.Schema({
  username: { // Move username to the top
    type: String,
    required: true,
    trim: true
  },
  course: {
    type: String,
    required: true,
    trim: true
  },
  subject: {
    type: String,
    required: true,
    trim: true
  },
  subjectCode: {
    type: String,
    required: true,
    trim: true
  },
  semester: {
    type: Number,
    required: true,
    min: 1
  },
  year: {
    type: Number,
    required: true,
    min: 1900,
    max: 2100
  },
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
  
  filePath: {
    type: String,
    required: true
  },
  extraction_status: {
    type: String,
    default: ""
  },
  extractedAnswer: {
    type: Object,
    default: {placeholder: true}
  },
  uploadedAt: {
    type: Date,
    default: Date.now
  }
});

module.exports = mongoose.model('StudentUpload', studentUploadSchema);



